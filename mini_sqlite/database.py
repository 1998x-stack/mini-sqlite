from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from mini_sqlite.btree import BTree
from mini_sqlite.catalog import Catalog
from mini_sqlite.constants import META_PAGE_ID
from mini_sqlite.index import ByteKeyBTree
from mini_sqlite.planner import Planner
from mini_sqlite.planner.plan import SelectPlan
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import BeginStmt, CommitStmt, RollbackStmt
from mini_sqlite.storage.meta import DatabaseMeta
from mini_sqlite.storage.pager import Pager
from mini_sqlite.transaction import TransactionManager
from mini_sqlite.vm import Compiler, VirtualMachine


@dataclass(frozen=True)
class QueryResult:
    rows: list[tuple[Any, ...]]
    columns: list[str]
    rowcount: int

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


class Database:
    """Facade joining SQL frontend, planner, VM, B+Tree, Pager and transactions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.pager = Pager(self.path)
        self.meta = self._open_or_initialize()
        self.tx = TransactionManager(self.pager)
        self._install_runtime()
        self._last_code = []
        self._last_explain = ""

    def _open_or_initialize(self) -> DatabaseMeta:
        if self.pager.page_count == 0:
            meta_page = self.pager.allocate_page()
            assert meta_page == META_PAGE_ID
            catalog_tree = BTree.create(self.pager)
            meta = DatabaseMeta(catalog_root_page=catalog_tree.root_page)
            self.pager.write_page(META_PAGE_ID, meta.encode())
            self.pager.flush_all()
            return meta
        return DatabaseMeta.decode(self.pager.get_page(META_PAGE_ID))

    def _install_runtime(self) -> None:
        self.catalog = Catalog(self.pager, self.meta, self._persist_meta)
        self.planner = Planner(self.catalog)
        self.compiler = Compiler()
        self.vm = VirtualMachine(self.pager, self.catalog)

    def _reload_runtime(self) -> None:
        self.meta = DatabaseMeta.decode(self.pager.get_page(META_PAGE_ID))
        self._install_runtime()

    def _persist_meta(self, meta: DatabaseMeta) -> None:
        self.meta = meta
        self.pager.write_page(META_PAGE_ID, meta.encode())

    @property
    def in_transaction(self) -> bool:
        return self.tx.active

    def begin(self) -> None:
        self.tx.begin()

    def commit(self) -> None:
        self.tx.commit()

    def rollback(self) -> None:
        self.tx.rollback()
        # Catalog/meta objects may have been changed by CREATE TABLE or a B+Tree
        # root split. Rebuild them from the restored page cache after rollback.
        self._reload_runtime()

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        self.begin()
        try:
            yield self
        except BaseException:
            if self.in_transaction:
                self.rollback()
            raise
        else:
            self.commit()

    def execute(self, sql: str) -> QueryResult:
        stmt = Parser(sql).parse()

        if isinstance(stmt, BeginStmt):
            self.begin()
            return QueryResult([], [], 0)
        if isinstance(stmt, CommitStmt):
            self.commit()
            return QueryResult([], [], 0)
        if isinstance(stmt, RollbackStmt):
            self.rollback()
            return QueryResult([], [], 0)

        plan = self.planner.plan(stmt)
        code = self.compiler.compile(plan)
        self._last_code = code
        self._last_explain = self.planner.explain(plan)

        # Read-only statements need no rollback journal in autocommit mode.
        # Any write statement outside BEGIN gets its own durable transaction.
        autocommit_write = not self.in_transaction and not isinstance(plan, SelectPlan)
        if autocommit_write:
            self.begin()

        try:
            vm_result = self.vm.execute(code)
            if autocommit_write:
                self.commit()
        except BaseException:
            # v0.2+ chooses a simple, safe policy: execution failure aborts the
            # whole active transaction rather than implementing statement savepoints.
            if self.in_transaction:
                self.rollback()
            raise

        columns: list[str] = []
        projection_names = getattr(plan, "projection_names", None)
        if projection_names is not None:
            columns = list(projection_names)
        return QueryResult(vm_result.rows, columns, vm_result.rowcount)

    def explain(self, sql: str) -> str:
        stmt = Parser(sql).parse()
        if isinstance(stmt, (BeginStmt, CommitStmt, RollbackStmt)):
            return type(stmt).__name__.removesuffix("Stmt").upper()
        plan = self.planner.plan(stmt)
        return self.planner.explain(plan)

    def bytecode(self, sql: str | None = None) -> str:
        if sql is not None:
            stmt = Parser(sql).parse()
            if isinstance(stmt, (BeginStmt, CommitStmt, RollbackStmt)):
                return "transaction control is handled by the connection, not the VM"
            plan = self.planner.plan(stmt)
            code = self.compiler.compile(plan)
        else:
            code = self._last_code
        return self.compiler.disassemble(code)

    def schema_text(self) -> str:
        chunks: list[str] = []
        for table in self.catalog.list_tables():
            cols = []
            for col in table.columns:
                suffix = " PRIMARY KEY" if col.primary_key else ""
                cols.append(f"{col.name} {col.type.value}{suffix}")
            chunks.append(f"CREATE TABLE {table.name} ({', '.join(cols)});")
            for index in table.indexes:
                chunks.append(
                    f"CREATE INDEX {index.name} ON {table.name}({index.column});"
                )
        return "\n".join(chunks)

    def indexes_text(self) -> str:
        rows = [
            f"{index.name}: table={table.name} column={index.column} root={index.root_page}"
            for table, index in self.catalog.list_indexes()
        ]
        return "\n".join(rows)

    def btree_dump(self, table_name: str) -> str:
        schema = self.catalog.get_table(table_name)
        tree = BTree(self.pager, schema.root_page)
        return tree.dump()

    def index_dump(self, index_name: str) -> str:
        _table, schema = self.catalog.get_index(index_name)
        tree = ByteKeyBTree(self.pager, schema.root_page)
        return tree.dump()

    def pages_text(self) -> str:
        from mini_sqlite.btree.node import BTreeNode
        from mini_sqlite.index.node import IndexNode

        lines = ["PAGE  TYPE          CELLS  PARENT  RIGHT"]
        lines.append(f"{0:>4}  {'META':<13} {'-':>5}  {'-':>6}  {'-':>5}")
        for page_id in range(1, self.pager.page_count):
            raw = self.pager.get_page(page_id)
            try:
                node = BTreeNode.decode(page_id, raw)
                kind = node.node_type.name
            except Exception:
                try:
                    node = IndexNode.decode(page_id, raw)
                    kind = f"IDX_{node.node_type.name}"
                except Exception:
                    lines.append(
                        f"{page_id:>4}  {'UNKNOWN':<13} {'?':>5}  {'?':>6}  {'?':>5}"
                    )
                    continue
            lines.append(
                f"{page_id:>4}  {kind:<13} {node.cell_count:>5}  "
                f"{node.parent:>6}  {node.right_sibling:>5}"
            )
        return "\n".join(lines)

    def transaction_status(self) -> str:
        stats = self.pager.stats()
        return (
            f"state={self.tx.state.value} journal={self.pager.journal_path.name} "
            f"journaled_pages={stats['journaled_pages']} "
            f"recovered_on_open={stats['recovery_performed']}"
        )

    def flush(self) -> None:
        """Force dirty pages to disk without committing an active transaction.

        This exists mainly to make the rollback protocol observable in teaching
        and crash tests. A hot journal still guarantees recovery after this call.
        """
        self.pager.flush_all()

    def close(self) -> None:
        # TransactionManager mirrors Pager state; close must preserve "uncommitted
        # means rolled back" semantics while leaving no stale manager state.
        if self.in_transaction:
            self.rollback()
        self.pager.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
