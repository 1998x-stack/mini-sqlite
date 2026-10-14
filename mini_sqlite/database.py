from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from mini_sqlite.btree import BTree
from mini_sqlite.catalog import Catalog
from mini_sqlite.constants import META_PAGE_ID
from mini_sqlite.concurrency import LockRegistry
from mini_sqlite.errors import BusySnapshotError
from mini_sqlite.index import ByteKeyBTree
from mini_sqlite.planner import Planner
from mini_sqlite.planner.plan import JoinSelectPlan, SelectPlan
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import BeginStmt, CommitStmt, RollbackStmt, SelectStmt as SelectStmtAst
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

    def __init__(
        self,
        path: str | Path,
        *,
        journal_mode: str = "rollback",
        buffer_pages: int = 64,
        replacement_policy: str = "clock",
        busy_timeout_ms: int = 0,
    ):
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        normalized_mode = journal_mode.lower().strip()
        registration = LockRegistry.register(
            self.path, normalized_mode, timeout_ms=busy_timeout_ms
        )
        self.connection_id = registration.connection_id
        self._registered = True
        self._snapshot_wal_signature: tuple[int, int] | None = None
        try:
            self.pager = Pager(
                self.path,
                journal_mode=normalized_mode,
                buffer_pages=buffer_pages,
                replacement_policy=replacement_policy,
                recover=registration.first_connection,
            )
            LockRegistry.bind_liveness(
                self.path,
                self.connection_id,
                lambda: not self.pager._file.closed and self._registered,
            )
            self.meta = self._open_or_initialize()
            self.tx = TransactionManager(self.pager)
            self._install_runtime()
            self._last_code = []
            self._last_explain = ""
        except BaseException:
            LockRegistry.unregister(self.path, self.connection_id)
            self._registered = False
            raise

    def _open_or_initialize(self) -> DatabaseMeta:
        if self.pager.page_count == 0:
            meta_page = self.pager.allocate_page()
            assert meta_page == META_PAGE_ID
            catalog_tree = BTree.create(self.pager)
            meta = DatabaseMeta(catalog_root_page=catalog_tree.root_page)
            self.pager.write_page(META_PAGE_ID, meta.encode())
            self.pager.flush_all()
            return meta
        with self.pager.pin_page(META_PAGE_ID) as page:
            return DatabaseMeta.decode(page)

    def _install_runtime(self) -> None:
        self.catalog = Catalog(self.pager, self.meta, self._persist_meta)
        self.planner = Planner(self.catalog)
        self.compiler = Compiler()
        self.vm = VirtualMachine(self.pager, self.catalog)

    def _reload_runtime(self) -> None:
        with self.pager.pin_page(META_PAGE_ID) as page:
            self.meta = DatabaseMeta.decode(page)
        self._install_runtime()

    def _persist_meta(self, meta: DatabaseMeta) -> None:
        self.meta = meta
        self.pager.write_page(META_PAGE_ID, meta.encode())

    @property
    def in_transaction(self) -> bool:
        return self.tx.active

    def _refresh_view(self) -> None:
        self.pager.refresh_from_disk()
        if self.pager.page_count == 0:
            return
        self._reload_runtime()

    def _acquire_shared_snapshot(self) -> None:
        LockRegistry.acquire_shared(
            self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
        )
        try:
            self._refresh_view()
            self._snapshot_wal_signature = self.pager.wal_signature()
        except BaseException:
            LockRegistry.release_all(self.path, self.connection_id)
            raise

    def _acquire_autocommit_write(self) -> None:
        try:
            if self.pager.journal_mode == "rollback":
                LockRegistry.acquire_reserved(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
                LockRegistry.acquire_exclusive(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
            else:
                LockRegistry.acquire_wal_writer(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
            self._refresh_view()
            self._snapshot_wal_signature = self.pager.wal_signature()
        except BaseException:
            LockRegistry.release_all(self.path, self.connection_id)
            raise

    def _upgrade_explicit_write(self) -> None:
        if self.pager.journal_mode == "rollback":
            try:
                LockRegistry.acquire_reserved(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
                LockRegistry.acquire_exclusive(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
            except BaseException:
                LockRegistry.downgrade_to_shared(self.path, self.connection_id)
                raise
            return

        LockRegistry.acquire_wal_writer(
            self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
        )
        if (
            self._snapshot_wal_signature is not None
            and self.pager.wal_signature() != self._snapshot_wal_signature
        ):
            LockRegistry.downgrade_to_shared(self.path, self.connection_id)
            raise BusySnapshotError(
                "WAL snapshot is stale; rollback and retry the write transaction"
            )

    def begin(self) -> None:
        if self.in_transaction:
            self.tx.begin()
            return
        self._acquire_shared_snapshot()
        try:
            self.tx.begin()
        except BaseException:
            LockRegistry.release_all(self.path, self.connection_id)
            self._snapshot_wal_signature = None
            raise

    def commit(self) -> None:
        self.tx.commit()
        LockRegistry.release_all(self.path, self.connection_id)
        self._snapshot_wal_signature = None

    def rollback(self) -> None:
        try:
            self.tx.rollback()
            self._reload_runtime()
        finally:
            LockRegistry.release_all(self.path, self.connection_id)
            self._snapshot_wal_signature = None

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

    def _execute_planned(self, stmt, *, autocommit_write: bool) -> QueryResult:
        plan = self.planner.plan(stmt)
        code = self.compiler.compile(plan)
        self._last_code = code
        self._last_explain = self.planner.explain(plan)
        vm_result = self.vm.execute(code)
        if autocommit_write:
            self.commit()

        columns: list[str] = []
        projection_names = getattr(plan, "projection_names", None)
        if projection_names is not None:
            columns = list(projection_names)
        return QueryResult(vm_result.rows, columns, vm_result.rowcount)

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

        read_only = isinstance(stmt, SelectStmtAst)

        if read_only and not self.in_transaction:
            self._acquire_shared_snapshot()
            try:
                return self._execute_planned(stmt, autocommit_write=False)
            finally:
                LockRegistry.release_all(self.path, self.connection_id)
                self._snapshot_wal_signature = None

        autocommit_write = not read_only and not self.in_transaction
        try:
            if autocommit_write:
                self._acquire_autocommit_write()
                self.tx.begin()
            elif not read_only:
                self._upgrade_explicit_write()
            return self._execute_planned(stmt, autocommit_write=autocommit_write)
        except BaseException:
            if self.in_transaction:
                self.rollback()
            elif autocommit_write:
                LockRegistry.release_all(self.path, self.connection_id)
                self._snapshot_wal_signature = None
            raise

    @contextmanager
    def _metadata_snapshot(self) -> Iterator[None]:
        if self.in_transaction:
            yield
            return
        self._acquire_shared_snapshot()
        try:
            yield
        finally:
            LockRegistry.release_all(self.path, self.connection_id)
            self._snapshot_wal_signature = None

    def explain(self, sql: str) -> str:
        stmt = Parser(sql).parse()
        if isinstance(stmt, (BeginStmt, CommitStmt, RollbackStmt)):
            return type(stmt).__name__.removesuffix("Stmt").upper()
        with self._metadata_snapshot():
            plan = self.planner.plan(stmt)
            return self.planner.explain(plan)

    def bytecode(self, sql: str | None = None) -> str:
        if sql is not None:
            stmt = Parser(sql).parse()
            if isinstance(stmt, (BeginStmt, CommitStmt, RollbackStmt)):
                return "transaction control is handled by the connection, not the VM"
            with self._metadata_snapshot():
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
                    f"CREATE INDEX {index.name} ON {table.name}({', '.join(index.columns)});"
                )
        return "\n".join(chunks)

    def indexes_text(self) -> str:
        rows = [
            f"{index.name}: table={table.name} columns=({', '.join(index.columns)}) root={index.root_page}"
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
            with self.pager.pin_page(page_id) as raw:
                raw_copy = bytes(raw)
            try:
                node = BTreeNode.decode(page_id, raw_copy)
                kind = node.node_type.name
            except Exception:
                try:
                    node = IndexNode.decode(page_id, raw_copy)
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

    def buffer_status(self) -> str:
        stats = self.pager.buffer_stats()
        hit_rate = stats["hit_rate_milli"] / 10
        return (
            f"policy={stats['policy']} capacity={stats['capacity']} "
            f"resident={stats['resident']} dirty={stats['dirty']} pinned={stats['pinned']} "
            f"hits={stats['hits']} misses={stats['misses']} hit_rate={hit_rate:.1f}% "
            f"evictions={stats['evictions']} dirty_evictions={stats['dirty_evictions']}"
        )

    def buffer_frames_text(self) -> str:
        rows = ["PAGE  DIRTY  PIN  REF  LAST_TOUCH"]
        for frame in self.pager.buffer_snapshot():
            rows.append(
                f"{frame['page_id']:>4}  {str(frame['dirty']):<5}  "
                f"{frame['pin_count']:>3}  {str(frame['referenced']):<5}  "
                f"{frame['last_touch']:>10}"
            )
        return "\n".join(rows)

    def transaction_status(self) -> str:
        stats = self.pager.stats()
        if self.pager.journal_mode == "wal":
            wal = self.pager.wal_stats()
            lock = LockRegistry.snapshot(self.path, self.connection_id)["my_lock"]
            return (
                f"state={self.tx.state.value} mode=wal lock={lock} "
                f"wal={self.pager.wal_path.name} dirty_pages={stats['transaction_dirty_pages']} "
                f"committed_frames={wal['committed_frames']} "
                f"recovered_on_open={stats['recovery_performed']}"
            )
        lock = LockRegistry.snapshot(self.path, self.connection_id)["my_lock"]
        return (
            f"state={self.tx.state.value} mode=rollback lock={lock} "
            f"journal={self.pager.journal_path.name} journaled_pages={stats['journaled_pages']} "
            f"recovered_on_open={stats['recovery_performed']}"
        )

    def wal_status(self) -> str:
        stats = self.pager.wal_stats()
        return (
            f"mode={stats['mode']} wal={self.pager.wal_path.name} "
            f"exists={stats['wal_exists']} txns={stats['committed_transactions']} "
            f"frames={stats['committed_frames']} overlay_pages={stats['overlay_pages']} "
            f"bytes={stats['wal_bytes']}"
        )

    def checkpoint(self) -> int:
        if self.in_transaction:
            return self.pager.checkpoint()
        if self.pager.journal_mode != "wal":
            return self.pager.checkpoint()
        LockRegistry.acquire_checkpoint(
            self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
        )
        try:
            self._refresh_view()
            return self.pager.checkpoint()
        finally:
            LockRegistry.release_all(self.path, self.connection_id)

    def lock_status(self) -> str:
        state = LockRegistry.snapshot(self.path, self.connection_id)
        return (
            f"connection={state['connection_id']} mode={state['journal_mode']} "
            f"mine={state['my_lock']} connections={state['connections']} "
            f"readers={state['shared_readers']} reserved={state['reserved_holder']} "
            f"exclusive={state['exclusive_holder']} wal_writer={state['wal_writer']} "
            f"busy_timeout_ms={self.busy_timeout_ms}"
        )

    def flush(self) -> None:
        self.pager.flush_all()

    def close(self) -> None:
        if not getattr(self, "_registered", False):
            return
        try:
            if self.in_transaction:
                self.rollback()
            else:
                LockRegistry.release_all(self.path, self.connection_id)
            self.pager.close()
        finally:
            LockRegistry.unregister(self.path, self.connection_id)
            self._registered = False

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
