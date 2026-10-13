from __future__ import annotations

import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from mini_sqlite import Database
from mini_sqlite.concurrency import lock_paths
from mini_sqlite.errors import BusyError, JournalModeConflictError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="v1.1 uses POSIX flock")


def _seed(path: str, mode: str = "rollback") -> None:
    with Database(path, journal_mode=mode) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        db.execute("INSERT INTO t VALUES (1, 'one');")


def _reader_session(path: str, mode: str, conn) -> None:
    try:
        with Database(path, journal_mode=mode) as db:
            db.execute("BEGIN;")
            conn.send(("ready", db.execute("SELECT * FROM t ORDER BY id;").rows))
            while True:
                command = conn.recv()
                if command == "read":
                    conn.send(("rows", db.execute("SELECT * FROM t ORDER BY id;").rows))
                elif command == "commit":
                    db.execute("COMMIT;")
                    conn.send(("committed", db.execute("SELECT * FROM t ORDER BY id;").rows))
                    return
                elif command == "rollback":
                    db.execute("ROLLBACK;")
                    conn.send(("rolled_back", None))
                    return
    except BaseException as exc:  # pragma: no cover - surfaced to parent
        try:
            conn.send(("error", repr(exc)))
        finally:
            conn.close()


def _timed_reader(path: str, seconds: float, ready) -> None:
    with Database(path) as db:
        db.execute("BEGIN;")
        ready.set()
        time.sleep(seconds)
        db.execute("COMMIT;")


def _wal_writer_session(path: str, conn) -> None:
    try:
        with Database(path, journal_mode="wal") as db:
            db.execute("BEGIN;")
            db.execute("INSERT INTO t VALUES (2, 'two');")
            conn.send(("ready", None))
            assert conn.recv() == "commit"
            db.execute("COMMIT;")
            conn.send(("committed", None))
    except BaseException as exc:  # pragma: no cover
        conn.send(("error", repr(exc)))


def _idle_connection(path: str, mode: str, conn) -> None:
    try:
        with Database(path, journal_mode=mode):
            conn.send(("ready", None))
            assert conn.recv() == "close"
            conn.send(("closed", None))
    except BaseException as exc:  # pragma: no cover
        conn.send(("error", repr(exc)))


def _crash_dirty_rollback_writer(path: str, ready) -> None:
    db = Database(path)
    db.execute("BEGIN;")
    db.execute("INSERT INTO t VALUES (2, 'uncommitted');")
    # Rollback mode permits dirty pages in the main DB only after the before-image
    # journal is durable. This creates a real hot-journal recovery case.
    db.flush()
    ready.set()
    os._exit(0)


def _try_open_rollback(path: str, conn) -> None:
    try:
        with Database(path):
            conn.send(("opened", None))
    except BaseException as exc:
        conn.send(("error", type(exc).__name__))


def _spawn_ctx():
    return mp.get_context("spawn")


def _recv_ready(conn, timeout: float = 5.0):
    assert conn.poll(timeout), "child process did not become ready"
    message = conn.recv()
    assert message[0] == "ready", message
    return message[1]


def test_cross_process_rollback_reader_blocks_writer(tmp_path: Path) -> None:
    path = str(tmp_path / "rollback-reader.db")
    _seed(path)
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_reader_session, args=(path, "rollback", child))
    proc.start()
    assert _recv_ready(parent) == [(1, "one")]
    try:
        with Database(path) as writer:
            with pytest.raises(BusyError):
                writer.execute("INSERT INTO t VALUES (2, 'two');")
            parent.send("commit")
            assert parent.poll(5)
            assert parent.recv()[0] == "committed"
            writer.execute("INSERT INTO t VALUES (2, 'two');")
            assert writer.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,)]
    finally:
        if proc.is_alive():
            parent.send("rollback")
        proc.join(5)
        assert proc.exitcode == 0


def test_cross_process_busy_timeout_waits_for_reader(tmp_path: Path) -> None:
    path = str(tmp_path / "busy-timeout.db")
    _seed(path)
    ctx = _spawn_ctx()
    ready = ctx.Event()
    proc = ctx.Process(target=_timed_reader, args=(path, 0.18, ready))
    proc.start()
    assert ready.wait(5)
    started = time.monotonic()
    with Database(path, busy_timeout_ms=1000) as writer:
        writer.execute("INSERT INTO t VALUES (2, 'two');")
    elapsed = time.monotonic() - started
    proc.join(5)
    assert proc.exitcode == 0
    assert elapsed >= 0.12


def test_cross_process_wal_reader_keeps_snapshot_while_writer_commits(tmp_path: Path) -> None:
    path = str(tmp_path / "wal-snapshot.db")
    _seed(path, "wal")
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_reader_session, args=(path, "wal", child))
    proc.start()
    assert _recv_ready(parent) == [(1, "one")]
    try:
        with Database(path, journal_mode="wal") as writer:
            writer.execute("INSERT INTO t VALUES (2, 'two');")
        parent.send("read")
        assert parent.poll(5)
        assert parent.recv() == ("rows", [(1, "one")])
        parent.send("commit")
        assert parent.poll(5)
        assert parent.recv() == ("committed", [(1, "one"), (2, "two")])
    finally:
        proc.join(5)
        assert proc.exitcode == 0


def test_cross_process_wal_allows_only_one_writer(tmp_path: Path) -> None:
    path = str(tmp_path / "wal-writer.db")
    _seed(path, "wal")
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_wal_writer_session, args=(path, child))
    proc.start()
    _recv_ready(parent)
    try:
        with Database(path, journal_mode="wal") as second:
            with pytest.raises(BusyError):
                second.execute("INSERT INTO t VALUES (3, 'three');")
            parent.send("commit")
            assert parent.poll(5)
            assert parent.recv()[0] == "committed"
            second.execute("INSERT INTO t VALUES (3, 'three');")
            assert second.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,), (3,)]
    finally:
        proc.join(5)
        assert proc.exitcode == 0


def test_cross_process_checkpoint_waits_for_wal_reader(tmp_path: Path) -> None:
    path = str(tmp_path / "wal-checkpoint.db")
    _seed(path, "wal")
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_reader_session, args=(path, "wal", child))
    proc.start()
    _recv_ready(parent)
    try:
        with Database(path, journal_mode="wal") as maint:
            with pytest.raises(BusyError):
                maint.checkpoint()
            parent.send("commit")
            assert parent.poll(5)
            assert parent.recv()[0] == "committed"
            assert maint.checkpoint() >= 1
    finally:
        proc.join(5)
        assert proc.exitcode == 0


def test_cross_process_crash_releases_lock_and_hot_journal_recovers(tmp_path: Path) -> None:
    path = str(tmp_path / "crash.db")
    _seed(path)
    ctx = _spawn_ctx()
    ready = ctx.Event()
    proc = ctx.Process(target=_crash_dirty_rollback_writer, args=(path, ready))
    proc.start()
    assert ready.wait(5)
    proc.join(5)
    assert proc.exitcode == 0

    # Kernel flock state died with the process. The globally-first new opener may
    # therefore own recovery even though the tiny sidecar files still exist.
    assert all(p.exists() for p in lock_paths(path).all())
    with Database(path) as recovered:
        assert recovered.execute("SELECT * FROM t ORDER BY id;").rows == [(1, "one")]
        recovered.execute("INSERT INTO t VALUES (2, 'after-crash');")
        assert recovered.execute("SELECT id FROM t ORDER BY id;").rows == [(1,), (2,)]


def test_cross_process_live_journal_modes_must_match(tmp_path: Path) -> None:
    path = str(tmp_path / "mode.db")
    _seed(path)
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_idle_connection, args=(path, "rollback", child))
    proc.start()
    _recv_ready(parent)
    try:
        with pytest.raises(JournalModeConflictError):
            Database(path, journal_mode="wal")
        parent.send("close")
        assert parent.poll(5)
        assert parent.recv()[0] == "closed"
    finally:
        proc.join(5)
        assert proc.exitcode == 0

    # Stale lock files do not pin a mode. With no live kernel holder, the next
    # globally-first opener may overwrite mode metadata.
    with Database(path, journal_mode="wal") as db:
        assert db.execute("SELECT * FROM t;").rows == [(1, "one")]


def test_cross_process_rollback_writer_blocks_new_pager_open(tmp_path: Path) -> None:
    path = str(tmp_path / "open-guard.db")
    _seed(path)
    with Database(path) as writer:
        writer.execute("BEGIN;")
        writer.execute("INSERT INTO t VALUES (2, 'uncommitted');")
        ctx = _spawn_ctx()
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=_try_open_rollback, args=(path, child))
        proc.start()
        assert parent.poll(5)
        assert parent.recv() == ("error", "BusyError")
        proc.join(5)
        assert proc.exitcode == 0
        writer.execute("ROLLBACK;")


def test_cross_process_vacuum_requires_global_exclusivity(tmp_path: Path) -> None:
    path = str(tmp_path / "vacuum.db")
    _seed(path)
    ctx = _spawn_ctx()
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_reader_session, args=(path, "rollback", child))
    proc.start()
    _recv_ready(parent)
    try:
        with Database(path) as maint:
            with pytest.raises(BusyError):
                maint.vacuum()
            # Failed maintenance acquisition must not leak WRITER-EX locally.
            assert "mine=none" in maint.lock_status()
        parent.send("commit")
        assert parent.poll(5)
        parent.recv()
    finally:
        proc.join(5)
        assert proc.exitcode == 0

    with Database(path) as maint:
        result = maint.vacuum()
        assert result.after_pages <= result.before_pages
