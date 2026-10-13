from __future__ import annotations

import threading
import time

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import BusyError, BusySnapshotError, DuplicateKeyError, JournalModeConflictError


def seed(path, *, journal_mode="rollback") -> None:
    with Database(path, journal_mode=journal_mode) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        db.execute("INSERT INTO t VALUES (1, 'one');")


def test_rollback_readers_share_lock_without_creating_journal(tmp_path):
    path = tmp_path / "readers.db"
    seed(path)
    with Database(path) as a, Database(path) as b:
        a.execute("BEGIN;")
        b.execute("BEGIN;")
        assert a.execute("SELECT * FROM t;").rows == [(1, "one")]
        assert b.execute("SELECT * FROM t;").rows == [(1, "one")]
        assert not a.pager.journal_path.exists()
        assert "readers=2" in a.lock_status()
        a.execute("COMMIT;")
        b.execute("COMMIT;")


def test_rollback_reader_blocks_writer_then_writer_refreshes(tmp_path):
    path = tmp_path / "reader-writer.db"
    seed(path)
    with Database(path) as reader, Database(path) as writer:
        reader.execute("BEGIN;")
        with pytest.raises(BusyError):
            writer.execute("INSERT INTO t VALUES (2, 'two');")
        assert not writer.in_transaction
        reader.execute("COMMIT;")
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        assert writer.execute("SELECT * FROM t ORDER BY id;").rows == [
            (1, "one"),
            (2, "two"),
        ]


def test_rollback_writer_blocks_reader_until_commit(tmp_path):
    path = tmp_path / "writer-reader.db"
    seed(path)
    with Database(path) as writer, Database(path) as reader:
        writer.execute("BEGIN;")
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        assert "mine=exclusive" in writer.lock_status()
        with pytest.raises(BusyError):
            reader.execute("SELECT * FROM t;")
        writer.execute("COMMIT;")
        assert reader.execute("SELECT * FROM t ORDER BY id;").rows == [
            (1, "one"),
            (2, "two"),
        ]


def test_busy_timeout_waits_and_wakes_after_reader_releases(tmp_path):
    path = tmp_path / "timeout.db"
    seed(path)
    reader = Database(path)
    writer = Database(path, busy_timeout_ms=1000)
    reader.execute("BEGIN;")
    outcome: dict[str, object] = {}

    def do_write() -> None:
        started = time.monotonic()
        try:
            writer.execute("INSERT INTO t VALUES (2, 'two');")
            outcome["ok"] = True
        except BaseException as exc:
            outcome["error"] = exc
        outcome["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=do_write)
    thread.start()
    time.sleep(0.05)
    assert thread.is_alive()
    reader.execute("COMMIT;")
    thread.join(timeout=2)
    try:
        assert not thread.is_alive()
        assert outcome.get("ok") is True, outcome.get("error")
        assert float(outcome["elapsed"]) >= 0.04
        assert writer.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,)]
    finally:
        reader.close()
        writer.close()


def test_busy_timeout_expires_deterministically(tmp_path):
    path = tmp_path / "timeout-expire.db"
    seed(path)
    with Database(path) as reader, Database(path, busy_timeout_ms=40) as writer:
        reader.execute("BEGIN;")
        started = time.monotonic()
        with pytest.raises(BusyError, match="timeout"):
            writer.execute("INSERT INTO t VALUES (2, 'two');")
        assert time.monotonic() - started >= 0.03
        reader.execute("ROLLBACK;")


def test_wal_reader_snapshot_coexists_with_writer(tmp_path):
    path = tmp_path / "wal-reader-writer.db"
    seed(path, journal_mode="wal")
    with Database(path, journal_mode="wal") as reader, Database(path, journal_mode="wal") as writer:
        reader.execute("BEGIN;")
        assert reader.execute("SELECT * FROM t ORDER BY id;").rows == [(1, "one")]
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        assert reader.execute("SELECT * FROM t ORDER BY id;").rows == [(1, "one")]
        assert writer.execute("SELECT * FROM t ORDER BY id;").rows == [
            (1, "one"),
            (2, "two"),
        ]
        reader.execute("COMMIT;")
        assert reader.execute("SELECT * FROM t ORDER BY id;").rows == [
            (1, "one"),
            (2, "two"),
        ]


def test_wal_single_writer_conflict(tmp_path):
    path = tmp_path / "wal-writers.db"
    seed(path, journal_mode="wal")
    with Database(path, journal_mode="wal") as first, Database(path, journal_mode="wal") as second:
        first.execute("BEGIN;")
        first.execute("INSERT INTO t VALUES (2, 'two');")
        assert "mine=wal-write" in first.lock_status()
        with pytest.raises(BusyError):
            second.execute("INSERT INTO t VALUES (3, 'three');")
        first.execute("COMMIT;")
        second.execute("INSERT INTO t VALUES (3, 'three');")
        assert second.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,), (3,)]


def test_wal_stale_read_snapshot_cannot_upgrade_to_writer(tmp_path):
    path = tmp_path / "wal-stale.db"
    seed(path, journal_mode="wal")
    with Database(path, journal_mode="wal") as stale, Database(path, journal_mode="wal") as writer:
        stale.execute("BEGIN;")
        assert stale.execute("SELECT * FROM t;").rows == [(1, "one")]
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        with pytest.raises(BusySnapshotError):
            stale.execute("INSERT INTO t VALUES (3, 'three');")
        assert not stale.in_transaction
        assert stale.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,)]


def test_wal_checkpoint_waits_for_explicit_reader_snapshot(tmp_path):
    path = tmp_path / "checkpoint-reader.db"
    seed(path, journal_mode="wal")
    with Database(path, journal_mode="wal") as reader, Database(path, journal_mode="wal") as maint:
        reader.execute("BEGIN;")
        with pytest.raises(BusyError):
            maint.checkpoint()
        reader.execute("COMMIT;")
        assert maint.checkpoint() >= 1


def test_statement_error_releases_writer_lock(tmp_path):
    path = tmp_path / "error-release.db"
    seed(path)
    with Database(path) as first, Database(path) as second:
        first.execute("BEGIN;")
        with pytest.raises(DuplicateKeyError):
            first.execute("INSERT INTO t VALUES (1, 'duplicate');")
        assert not first.in_transaction
        second.execute("INSERT INTO t VALUES (2, 'two');")
        assert second.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,)]


def test_live_connections_must_agree_on_journal_mode(tmp_path):
    path = tmp_path / "mode.db"
    seed(path)
    rollback = Database(path, journal_mode="rollback")
    try:
        with pytest.raises(JournalModeConflictError):
            Database(path, journal_mode="wal")
    finally:
        rollback.close()
    with Database(path, journal_mode="wal") as wal:
        assert wal.execute("SELECT * FROM t;").rows == [(1, "one")]
