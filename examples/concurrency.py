from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import BusyError, Database


def cleanup(path: Path) -> None:
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal")):
        candidate.unlink(missing_ok=True)


def rollback_demo(path: Path) -> None:
    print("rollback mode")
    with Database(path) as setup:
        setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        setup.execute("INSERT INTO t VALUES (1, 'one');")

    with Database(path) as reader, Database(path) as writer:
        reader.execute("BEGIN;")
        print("reader:", reader.lock_status())
        try:
            writer.execute("INSERT INTO t VALUES (2, 'two');")
        except BusyError as exc:
            print("writer blocked:", exc)
        reader.execute("COMMIT;")
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        print("rows after reader releases:", writer.execute("SELECT * FROM t ORDER BY id;").rows)


def wal_demo(path: Path) -> None:
    print("\nwal mode")
    cleanup(path)
    with Database(path, journal_mode="wal") as setup:
        setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        setup.execute("INSERT INTO t VALUES (1, 'one');")

    with Database(path, journal_mode="wal") as reader, Database(path, journal_mode="wal") as writer:
        reader.execute("BEGIN;")
        print("reader snapshot:", reader.execute("SELECT * FROM t ORDER BY id;").rows)
        writer.execute("INSERT INTO t VALUES (2, 'two');")
        print("same reader snapshot:", reader.execute("SELECT * FROM t ORDER BY id;").rows)
        print("writer sees newest:", writer.execute("SELECT * FROM t ORDER BY id;").rows)
        reader.execute("COMMIT;")
        print("reader after COMMIT:", reader.execute("SELECT * FROM t ORDER BY id;").rows)


def main() -> None:
    path = Path("concurrency-demo.db")
    cleanup(path)
    rollback_demo(path)
    wal_demo(path)
    cleanup(path)


if __name__ == "__main__":
    main()
