from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mini_sqlite.btree import BTree
from mini_sqlite.catalog import Catalog
from mini_sqlite.constants import META_PAGE_ID
from mini_sqlite.planner import Planner
from mini_sqlite.sql import Parser
from mini_sqlite.storage.meta import DatabaseMeta
from mini_sqlite.storage.pager import Pager
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
    """Facade joining SQL frontend, planner, VM, B+Tree, and Pager."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.pager = Pager(self.path)
        self.meta = self._open_or_initialize()
        self.catalog = Catalog(self.pager, self.meta, self._persist_meta)
        self.planner = Planner(self.catalog)
        self.compiler = Compiler()
        self.vm = VirtualMachine(self.pager, self.catalog)
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

    def _persist_meta(self, meta: DatabaseMeta) -> None:
        self.meta = meta
        self.pager.write_page(META_PAGE_ID, meta.encode())

    def execute(self, sql: str) -> QueryResult:
        stmt = Parser(sql).parse()
        plan = self.planner.plan(stmt)
        code = self.compiler.compile(plan)
        self._last_code = code
        self._last_explain = self.planner.explain(plan)
        vm_result = self.vm.execute(code)
        # v0.1 uses statement-level autocommit durability. Atomic rollback on crash
        # arrives with the rollback journal in v0.2.
        self.pager.flush_all()

        columns: list[str] = []
        projection_names = getattr(plan, "projection_names", None)
        if projection_names is not None:
            columns = list(projection_names)
        return QueryResult(vm_result.rows, columns, vm_result.rowcount)

    def explain(self, sql: str) -> str:
        stmt = Parser(sql).parse()
        plan = self.planner.plan(stmt)
        return self.planner.explain(plan)

    def bytecode(self, sql: str | None = None) -> str:
        if sql is not None:
            stmt = Parser(sql).parse()
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
        return "\n".join(chunks)

    def btree_dump(self, table_name: str) -> str:
        schema = self.catalog.get_table(table_name)
        tree = BTree(self.pager, schema.root_page)
        return tree.dump()

    def pages_text(self) -> str:
        from mini_sqlite.btree.node import BTreeNode

        lines = ["PAGE  TYPE       CELLS  PARENT  RIGHT"]
        lines.append(f"{0:>4}  {'META':<10} {'-':>5}  {'-':>6}  {'-':>5}")
        for page_id in range(1, self.pager.page_count):
            try:
                node = BTreeNode.decode(page_id, self.pager.get_page(page_id))
                lines.append(
                    f"{page_id:>4}  {node.node_type.name:<10} {node.cell_count:>5}  "
                    f"{node.parent:>6}  {node.right_sibling:>5}"
                )
            except Exception:
                lines.append(f"{page_id:>4}  {'UNKNOWN':<10} {'?':>5}  {'?':>6}  {'?':>5}")
        return "\n".join(lines)

    def flush(self) -> None:
        self.pager.flush_all()

    def close(self) -> None:
        self.pager.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
