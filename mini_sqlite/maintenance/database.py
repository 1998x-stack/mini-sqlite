from __future__ import annotations

import os
import time

from mini_sqlite.btree import BTree
from mini_sqlite.concurrency import LockRegistry, lock_paths
from mini_sqlite.database import Database as CoreDatabase
from mini_sqlite.errors import BusyError, SchemaError, TransactionError
from mini_sqlite.maintenance.diagnostics import ExplainAnalyzeResult, VacuumResult
from mini_sqlite.maintenance.integrity import IntegrityChecker, IntegrityReport
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import SelectStmt as SelectStmtAst
from mini_sqlite.storage.pager import Pager
from mini_sqlite.transaction import TransactionManager


class Database(CoreDatabase):
    """v1.0 lifecycle extension over the frozen v0.9 connection engine."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # v1.1: release the constructor-only rollback reader guard and
            # downgrade globally-first MODE-EX only after Pager/runtime bootstrap.
            LockRegistry.finish_registration(self.path, self.connection_id)
        except BaseException:
            super().close()
            raise
        self._maintenance_in_progress = False
        # Rebind liveness so a same-connection VACUUM may temporarily close the
        # old Pager while atomically replacing the database file.
        LockRegistry.bind_liveness(
            self.path,
            self.connection_id,
            lambda: self._registered
            and (self._maintenance_in_progress or not self.pager._file.closed),
        )

    def lock_status(self) -> str:
        state = LockRegistry.snapshot(self.path, self.connection_id)
        return (
            f"connection={state['connection_id']} pid={state['pid']} "
            f"mode={state['journal_mode']} backend={state['backend']} "
            f"mine={state['my_lock']} connections={state['connections']} "
            f"readers={state['shared_readers']} reserved={state['reserved_holder']} "
            f"exclusive={state['exclusive_holder']} wal_writer={state['wal_writer']} "
            f"os_readers={state['readers_lock']} os_writer={state['writer_lock']} "
            f"busy_timeout_ms={self.busy_timeout_ms}"
        )

    def _run_maintenance_write(self, callback):
        """Run a storage-maintenance mutation with normal transaction semantics."""
        autocommit = not self.in_transaction
        try:
            if autocommit:
                self._acquire_autocommit_write()
                self.tx.begin()
            else:
                self._upgrade_explicit_write()
            result = callback()
            if autocommit:
                self.commit()
            return result
        except BaseException:
            if self.in_transaction:
                self.rollback()
            elif autocommit:
                LockRegistry.release_all(self.path, self.connection_id)
                self._snapshot_wal_signature = None
            raise

    def reindex(self, index_name: str | None = None) -> int:
        """Rebuild one or all secondary indexes atomically."""
        return int(self._run_maintenance_write(lambda: self.catalog.reindex(index_name)))

    def integrity_check(self) -> IntegrityReport:
        """Validate all reachable trees, rows, and secondary-index contents."""
        if self.in_transaction:
            return IntegrityChecker(self.pager, self.catalog, self.meta).run()
        self._acquire_shared_snapshot()
        try:
            return IntegrityChecker(self.pager, self.catalog, self.meta).run()
        finally:
            LockRegistry.release_all(self.path, self.connection_id)
            self._snapshot_wal_signature = None

    def explain_analyze(self, sql: str) -> ExplainAnalyzeResult:
        """Execute a SELECT once and report estimated plan + actual runtime metrics."""
        stmt = Parser(sql).parse()
        if not isinstance(stmt, SelectStmtAst):
            raise SchemaError("EXPLAIN ANALYZE currently accepts SELECT statements only")

        acquired = False
        if not self.in_transaction:
            self._acquire_shared_snapshot()
            acquired = True
        try:
            plan = self.planner.plan(stmt)
            code = self.compiler.compile(plan)
            before = self.pager.buffer_stats()
            start = time.perf_counter_ns()
            result = self.vm.execute(code)
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            after = self.pager.buffer_stats()
            return ExplainAnalyzeResult(
                plan=self.planner.explain(plan),
                bytecode=self.compiler.disassemble(code),
                actual_rows=len(result.rows),
                elapsed_ms=elapsed_ms,
                buffer_hits=int(after["hits"]) - int(before["hits"]),
                buffer_misses=int(after["misses"]) - int(before["misses"]),
                buffer_evictions=int(after["evictions"]) - int(before["evictions"]),
                buffer_dirty_evictions=int(after["dirty_evictions"])
                - int(before["dirty_evictions"]),
            )
        finally:
            if acquired:
                LockRegistry.release_all(self.path, self.connection_id)
                self._snapshot_wal_signature = None

    def vacuum(self) -> VacuumResult:
        """Rewrite the logical database into a compact replacement file."""
        if self.in_transaction:
            raise TransactionError("VACUUM cannot run inside a transaction")
        state = LockRegistry.snapshot(self.path, self.connection_id)
        if state["connections"] != 1:
            raise BusyError("VACUUM requires the only live connection to the database")

        try:
            if self.pager.journal_mode == "rollback":
                LockRegistry.acquire_reserved(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
                LockRegistry.acquire_exclusive(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
            else:
                LockRegistry.acquire_checkpoint(
                    self.path, self.connection_id, timeout_ms=self.busy_timeout_ms
                )
        except BaseException:
            # Cross-process acquisition may fail after WRITER-EX/RESERVED was
            # obtained but while readers are still draining. Never leak that
            # partial lock into the next statement on this connection.
            LockRegistry.release_all(self.path, self.connection_id)
            raise

        self._maintenance_in_progress = True
        temp_path = self.path.with_name(f".{self.path.name}.vacuum-{self.connection_id}.tmp")
        temp_journal = temp_path.with_name(temp_path.name + "-journal")
        temp_wal = temp_path.with_name(temp_path.name + "-wal")
        temp_lock_paths = lock_paths(temp_path).all()
        try:
            self._refresh_view()
            if self.pager.journal_mode == "wal":
                self.pager.checkpoint()
                self._refresh_view()

            before_pages = self.pager.page_count
            tables = self.catalog.list_tables()
            table_payloads: list[tuple[object, list[tuple[int, bytes]]]] = []
            for table in tables:
                tree = BTree(self.pager, table.root_page)
                table_payloads.append((table, list(tree.scan())))

            for path in (temp_path, temp_journal, temp_wal, *temp_lock_paths):
                if path.exists():
                    path.unlink()

            with type(self)(
                temp_path,
                journal_mode="rollback",
                buffer_pages=int(self.pager.buffer_stats()["capacity"]),
                replacement_policy=str(self.pager.buffer_stats()["policy"]),
                busy_timeout_ms=0,
            ) as compact:
                for source_table, rows in table_payloads:
                    new_schema = compact.catalog.create_table(
                        source_table.name, list(source_table.columns)
                    )
                    new_tree = BTree(
                        compact.pager,
                        new_schema.root_page,
                        on_root_change=lambda root, table_id=new_schema.table_id: compact.catalog.update_root_page(
                            table_id, root
                        ),
                    )
                    for rowid, raw in rows:
                        new_tree.insert(rowid, raw)
                    for index in source_table.indexes:
                        compact.catalog.create_index(index.name, source_table.name, index.column)
                    if source_table.stats is not None:
                        compact.catalog.analyze(source_table.name)
                compact.flush()

            buffer_stats = self.pager.buffer_stats()
            journal_mode = self.pager.journal_mode
            self.pager.close()
            os.replace(temp_path, self.path)
            for sidecar in (
                self.path.with_name(self.path.name + "-journal"),
                self.path.with_name(self.path.name + "-wal"),
            ):
                if sidecar.exists():
                    sidecar.unlink()

            self.pager = Pager(
                self.path,
                journal_mode=journal_mode,
                buffer_pages=int(buffer_stats["capacity"]),
                replacement_policy=str(buffer_stats["policy"]),
                recover=False,
            )
            self.meta = self._open_or_initialize()
            self.tx = TransactionManager(self.pager)
            self._install_runtime()
            self._last_code = []
            self._last_explain = ""
            self._snapshot_wal_signature = None
            return VacuumResult(before_pages=before_pages, after_pages=self.pager.page_count)
        finally:
            self._maintenance_in_progress = False
            LockRegistry.release_all(self.path, self.connection_id)
            for path in (temp_path, temp_journal, temp_wal, *temp_lock_paths):
                if path.exists():
                    path.unlink()
