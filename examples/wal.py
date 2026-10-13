from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_sqlite import Database


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wal-demo.db"

        with Database(path, journal_mode="wal") as db:
            db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
            db.execute("INSERT INTO items VALUES (1, 'from WAL');")
            db.execute("INSERT INTO items VALUES (2, 'still not checkpointed');")
            print("rows:", db.execute("SELECT * FROM items ORDER BY id;").rows)
            print("wal before checkpoint:", db.wal_status())
            print("checkpointed pages:", db.checkpoint())
            print("wal after checkpoint:", db.wal_status())

        with Database(path, journal_mode="rollback") as db:
            print("rollback-mode reopen:", db.execute("SELECT * FROM items ORDER BY id;").rows)


if __name__ == "__main__":
    main()
