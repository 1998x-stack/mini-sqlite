from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database
from mini_sqlite.errors import BusyError


def hold_reader(path: str, mode: str, conn) -> None:
    with Database(path, journal_mode=mode) as db:
        db.execute("BEGIN;")
        conn.send(db.execute("SELECT * FROM t ORDER BY id;").rows)
        command = conn.recv()
        if command == "read":
            conn.send(db.execute("SELECT * FROM t ORDER BY id;").rows)
            command = conn.recv()
        assert command == "commit"
        db.execute("COMMIT;")


def main() -> None:
    ctx = mp.get_context("spawn")

    rollback_path = "cross-process-rollback.db"
    with Database(rollback_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        db.execute("INSERT INTO t VALUES (1, 'one');")

    parent, child = ctx.Pipe()
    reader = ctx.Process(target=hold_reader, args=(rollback_path, "rollback", child))
    reader.start()
    print("rollback child snapshot:", parent.recv())
    with Database(rollback_path) as writer:
        try:
            writer.execute("INSERT INTO t VALUES (2, 'blocked');")
        except BusyError as exc:
            print("rollback writer blocked across processes:", exc)
    parent.send("commit")
    reader.join()

    wal_path = "cross-process-wal.db"
    with Database(wal_path, journal_mode="wal") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        db.execute("INSERT INTO t VALUES (1, 'one');")

    parent, child = ctx.Pipe()
    reader = ctx.Process(target=hold_reader, args=(wal_path, "wal", child))
    reader.start()
    print("WAL child snapshot:", parent.recv())
    with Database(wal_path, journal_mode="wal") as writer:
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        print("WAL writer sees:", writer.execute("SELECT * FROM t ORDER BY id;").rows)
    parent.send("read")
    print("WAL child still sees old snapshot:", parent.recv())
    parent.send("commit")
    reader.join()


if __name__ == "__main__":
    main()
