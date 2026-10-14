from __future__ import annotations

import os
from pathlib import Path

import pytest

from mini_sqlite import Database
from mini_sqlite.storage.freelist import FreePage
from mini_sqlite.storage.meta import DatabaseMeta


def seed_indexed(db: Database, rows: int = 399) -> None:
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
    db.execute("CREATE INDEX idx_v ON t(v);")
    for i in range(1, rows + 1):
        db.execute(f"INSERT INTO t VALUES ({i}, 'v{i % 7}');")


def test_meta_round_trip_preserves_free_list_head() -> None:
    meta = DatabaseMeta(catalog_root_page=7, next_table_id=9, free_list_head=12)
    decoded = DatabaseMeta.decode(meta.encode())
    assert decoded.catalog_root_page == 7
    assert decoded.next_table_id == 9
    assert decoded.free_list_head == 12


def test_reindex_returns_old_index_pages_to_freelist(tmp_path: Path) -> None:
    path = tmp_path / "reindex-free.db"
    with Database(path) as db:
        seed_indexed(db, 180)
        before = db.pager.page_count
        db.reindex("idx_v")
        free_pages = db.pager.free_list_pages()
        assert free_pages
        assert db.pager.page_count >= before
        report = db.integrity_check()
        assert report.ok
        assert report.free_pages == len(free_pages)
        assert report.orphan_pages == ()


def test_allocation_prefers_free_page_without_growing_file(tmp_path: Path) -> None:
    path = tmp_path / "reuse.db"
    with Database(path) as db:
        seed_indexed(db, 180)
        db.reindex("idx_v")
        free_before = db.pager.free_list_pages()
        assert free_before
        page_count = db.pager.page_count
        db.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, v TEXT);")
        assert db.pager.page_count == page_count
        assert db.catalog.get_table("u").root_page == free_before[0]
        assert len(db.pager.free_list_pages()) == len(free_before) - 1


def test_rollback_restores_freelist_after_reindex(tmp_path: Path) -> None:
    path = tmp_path / "rollback.db"
    with Database(path) as db:
        seed_indexed(db, 160)
        old_root = db.catalog.get_index("idx_v")[1].root_page
        original_free = db.pager.free_list_pages()
        db.execute("BEGIN;")
        db.reindex("idx_v")
        assert db.catalog.get_index("idx_v")[1].root_page != old_root
        assert db.pager.free_list_pages() != original_free
        db.execute("ROLLBACK;")
        assert db.catalog.get_index("idx_v")[1].root_page == old_root
        assert db.pager.free_list_pages() == original_free
        assert db.integrity_check().ok


def test_wal_freelist_survives_reopen_and_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "wal-free.db"
    with Database(path, journal_mode="wal") as db:
        seed_indexed(db, 180)
        db.reindex("idx_v")
        expected = db.pager.free_list_pages()
        assert expected

    with Database(path, journal_mode="wal") as db:
        assert db.pager.free_list_pages() == expected
        assert db.integrity_check().ok
        db.checkpoint()

    with Database(path, journal_mode="rollback") as db:
        assert db.pager.free_list_pages() == expected
        assert db.integrity_check().ok


def prepare_tail_free_pages(db: Database) -> int:
    seed_indexed(db, 399)
    db.reindex("idx_v")
    db.reindex("idx_v")
    free_pages = db.pager.free_list_pages()
    assert free_pages
    assert db.pager.page_count - 1 in free_pages
    return db.pager.page_count


def test_incremental_vacuum_truncates_contiguous_free_tail(tmp_path: Path) -> None:
    path = tmp_path / "incremental.db"
    with Database(path) as db:
        before = prepare_tail_free_pages(db)
        result = db.incremental_vacuum()
        assert result.before_pages == before
        assert result.reclaimed_pages > 0
        assert result.after_pages < before
        assert db.pager.page_count == result.after_pages
        assert path.stat().st_size == result.after_pages * db.pager.page_size
        assert db.integrity_check().ok


def test_incremental_vacuum_respects_max_pages(tmp_path: Path) -> None:
    path = tmp_path / "incremental-limit.db"
    with Database(path) as db:
        before = prepare_tail_free_pages(db)
        first = db.incremental_vacuum(2)
        assert first.reclaimed_pages == 2
        assert first.after_pages == before - 2
        second = db.incremental_vacuum()
        assert second.reclaimed_pages > 0
        assert db.integrity_check().ok


def test_wal_incremental_vacuum_commits_smaller_page_count(tmp_path: Path) -> None:
    path = tmp_path / "wal-vacuum.db"
    with Database(path, journal_mode="wal") as db:
        before = prepare_tail_free_pages(db)
        result = db.incremental_vacuum()
        assert result.reclaimed_pages > 0
        assert result.after_pages < before
        assert path.stat().st_size == result.after_pages * db.pager.page_size
        expected_rows = db.execute("SELECT COUNT(*) FROM t;").rows

    with Database(path, journal_mode="rollback") as db:
        assert db.execute("SELECT COUNT(*) FROM t;").rows == expected_rows
        assert db.integrity_check().ok


def test_integrity_detects_freelist_cycle(tmp_path: Path) -> None:
    path = tmp_path / "cycle.db"
    with Database(path) as db:
        seed_indexed(db, 160)
        db.reindex("idx_v")
        head = db.pager.free_list_head
        assert head
        db.execute("BEGIN;")
        db.pager.write_page(head, FreePage(head).encode(db.pager.page_size))
        db.execute("COMMIT;")
        report = db.integrity_check()
        assert not report.ok
        assert any("free-list" in error for error in report.errors)


def test_hot_journal_recovers_crash_during_tail_truncation(tmp_path: Path) -> None:
    path = tmp_path / "truncate-crash.db"
    db = Database(path)
    original_count = prepare_tail_free_pages(db)
    original_free = db.pager.free_list_pages()

    db._acquire_autocommit_write()
    db.tx.begin()
    reclaimed = db.pager.trim_free_tail()
    assert reclaimed > 0
    target = db.pager._pending_truncate_page_count
    assert target is not None and target < original_count
    db.pager._sync_journal_if_needed()
    db.pager.flush_all(sync=True)
    db.pager._file.truncate(target * db.pager.page_size)
    db.pager._file.flush()
    os.fsync(db.pager._file.fileno())
    db.pager._file.close()

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.pager.page_count == original_count
        assert recovered.pager.free_list_pages() == original_free
        assert recovered.integrity_check().ok


def test_v1_metadata_opens_and_upgrades_when_freelist_semantics_are_persisted(tmp_path: Path) -> None:
    path = tmp_path / "legacy-v1.db"
    with Database(path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        db.execute("CREATE INDEX idx_v ON t(v);")
        for i in range(1, 80):
            db.execute(f"INSERT INTO t VALUES ({i}, 'v{i % 3}');")
        legacy = DatabaseMeta(
            page_size=db.meta.page_size,
            catalog_root_page=db.meta.catalog_root_page,
            next_table_id=db.meta.next_table_id,
            version=1,
            free_list_head=0,
        )
        db.pager.write_page(0, legacy.encode())
        db.flush()

    with Database(path) as db:
        assert db.meta.version == 3
        db.reindex("idx_v")
        assert db.pager.free_list_pages()
        with db.pager.pin_page(0) as raw:
            persisted = DatabaseMeta.decode(raw)
        assert persisted.version == 3
        assert persisted.free_list_head == db.pager.free_list_head
