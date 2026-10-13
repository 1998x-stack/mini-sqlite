from __future__ import annotations

from pathlib import Path

import pytest

from mini_sqlite import Database
from mini_sqlite.btree import BTree
from mini_sqlite.errors import BusyError, SchemaError
from mini_sqlite.index.secondary import SecondaryIndex
from mini_sqlite.storage import RecordCodec


def make_users(db: Database, count: int = 80) -> None:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER, name TEXT);")
    for i in range(1, count + 1):
        db.execute(f"INSERT INTO users VALUES ({i}, {i % 7}, 'user-{i:03d}');")
    db.execute("CREATE INDEX idx_users_age ON users(age);")


def test_integrity_check_healthy_database(tmp_path: Path) -> None:
    path = tmp_path / "healthy.db"
    with Database(path) as db:
        make_users(db, 40)
        db.execute("ANALYZE users;")
        report = db.integrity_check()
        assert report.ok
        assert report.tables == 1
        assert report.rows == 40
        assert report.indexes == 1
        assert report.index_entries == 40
        assert not report.errors
        assert report.render().startswith("ok\n")


def test_integrity_check_detects_secondary_index_mismatch_and_reindex_repairs_it(tmp_path: Path) -> None:
    path = tmp_path / "repair.db"
    with Database(path) as db:
        make_users(db, 24)
        table, index_schema = db.catalog.get_index("idx_users_age")
        index = SecondaryIndex(db.pager, table, index_schema)
        row = RecordCodec.decode(BTree(db.pager, table.root_page).get_required(3))
        assert index.delete(row, 3)
        db.flush()
        broken = db.integrity_check()
        assert not broken.ok
        assert any("contents disagree" in error for error in broken.errors)
        assert db.reindex("idx_users_age") == 1
        repaired = db.integrity_check()
        assert repaired.ok
        assert db.execute("SELECT id FROM users WHERE age = 3;").rows


def test_reindex_all_is_atomic_and_rollback_restores_old_roots(tmp_path: Path) -> None:
    path = tmp_path / "rollback-reindex.db"
    with Database(path) as db:
        make_users(db, 120)
        db.execute("CREATE INDEX idx_users_name ON users(name);")
        before = {index.name: index.root_page for _table, index in db.catalog.list_indexes()}
        before_pages = db.pager.page_count
        db.begin()
        assert db.reindex() == 2
        during = {index.name: index.root_page for _table, index in db.catalog.list_indexes()}
        assert during != before
        assert db.pager.page_count > before_pages
        db.rollback()
        after = {index.name: index.root_page for _table, index in db.catalog.list_indexes()}
        assert after == before
        assert db.pager.page_count == before_pages
        assert db.integrity_check().ok


def test_integrity_warns_for_stale_statistics_and_orphan_pages(tmp_path: Path) -> None:
    path = tmp_path / "warnings.db"
    with Database(path) as db:
        make_users(db, 100)
        db.execute("ANALYZE users;")
        assert db.reindex("idx_users_age") == 1
        db.execute("INSERT INTO users VALUES (101, 3, 'late');")
        report = db.integrity_check()
        assert report.ok
        assert report.free_pages > 0
        assert report.orphan_pages == ()
        assert any("statistics" in warning and "stale" in warning for warning in report.warnings)


def test_vacuum_reclaims_unreachable_pages_and_preserves_schema_data_indexes_stats(tmp_path: Path) -> None:
    path = tmp_path / "vacuum.db"
    with Database(path, buffer_pages=4) as db:
        make_users(db, 260)
        db.execute("ANALYZE users;")
        for i in range(41, 261):
            db.execute(f"DELETE FROM users WHERE id = {i};")
        db.reindex("idx_users_age")
        before_report = db.integrity_check()
        assert before_report.ok
        assert before_report.free_pages > 0
        assert not before_report.orphan_pages
        before_pages = db.pager.page_count
        rows_before = db.execute("SELECT id, age, name FROM users ORDER BY id;").rows
        result = db.vacuum()
        assert result.before_pages == before_pages
        assert result.after_pages < result.before_pages
        assert result.reclaimed_pages > 0
        assert db.execute("SELECT id, age, name FROM users ORDER BY id;").rows == rows_before
        assert "idx_users_age" in db.indexes_text()
        report = db.integrity_check()
        assert report.ok
        assert report.orphan_pages == ()
        assert db.catalog.get_table("users").stats is not None
    with Database(path) as reopened:
        assert reopened.integrity_check().ok
        assert reopened.execute("SELECT COUNT(*) FROM users;").rows == [(40,)]


def test_vacuum_wal_checkpoint_and_mode_reopen(tmp_path: Path) -> None:
    path = tmp_path / "vacuum-wal.db"
    with Database(path, journal_mode="wal", buffer_pages=4) as db:
        make_users(db, 90)
        db.execute("INSERT INTO users VALUES (91, 6, 'wal-only-before-vacuum');")
        assert db.pager.wal_stats()["committed_frames"] > 0
        result = db.vacuum()
        assert result.after_pages > 0
        assert db.execute("SELECT name FROM users WHERE id = 91;").rows == [("wal-only-before-vacuum",)]
        assert db.integrity_check().ok
    with Database(path, journal_mode="wal") as reopened:
        assert reopened.execute("SELECT id FROM users WHERE id = 91;").rows == [(91,)]
        assert reopened.integrity_check().ok


def test_vacuum_requires_only_live_connection(tmp_path: Path) -> None:
    path = tmp_path / "busy-vacuum.db"
    with Database(path) as first:
        make_users(first, 5)
        with Database(path) as second:
            with pytest.raises(BusyError, match="only live connection"):
                first.vacuum()
            assert second.execute("SELECT COUNT(*) FROM users;").rows == [(5,)]


def test_vacuum_rejected_inside_transaction(tmp_path: Path) -> None:
    path = tmp_path / "txn-vacuum.db"
    with Database(path) as db:
        make_users(db, 5)
        db.begin()
        with pytest.raises(Exception, match="VACUUM cannot run inside"):
            db.vacuum()
        db.rollback()


def test_explain_analyze_reports_plan_actual_rows_and_buffer_deltas(tmp_path: Path) -> None:
    path = tmp_path / "explain-analyze.db"
    with Database(path, buffer_pages=3) as db:
        make_users(db, 100)
        db.execute("ANALYZE users;")
        report = db.explain_analyze("SELECT id FROM users WHERE age = 3 ORDER BY id LIMIT 5;")
        assert "EST rows=" in report.plan
        assert report.actual_rows == 5
        assert report.elapsed_ms >= 0
        assert report.buffer_hits >= 0
        assert report.buffer_misses >= 0
        assert "OPEN_" in report.bytecode
        rendered = report.render()
        assert "PLAN " in rendered
        assert "ACTUAL rows=5" in rendered
        assert "BYTECODE" in rendered


def test_explain_analyze_rejects_non_select(tmp_path: Path) -> None:
    path = tmp_path / "explain-write.db"
    with Database(path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        with pytest.raises(SchemaError, match="SELECT statements only"):
            db.explain_analyze("INSERT INTO t VALUES (1, 'x');")
