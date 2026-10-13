from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database
from mini_sqlite.concurrency import lock_paths


def cleanup(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-journal"),
        Path(str(path) + "-wal"),
        *lock_paths(path).all(),
    ):
        if candidate.exists():
            candidate.unlink()


def main() -> None:
    path = Path("freelist.db")
    cleanup(path)

    with Database(path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        db.execute("CREATE INDEX idx_v ON t(v);")
        for i in range(1, 400):
            db.execute(f"INSERT INTO t VALUES ({i}, 'v{i % 7}');")

        print("initial:", db.pager.page_count, db.freelist_text())

        # First rebuild appends a new index and frees the old lower page ids.
        db.reindex("idx_v")
        print("after reindex #1:", db.pager.page_count, db.freelist_text())

        # Second rebuild reuses those free pages, then frees the previously-new
        # high page ids, producing a reclaimable free suffix.
        db.reindex("idx_v")
        print("after reindex #2:", db.pager.page_count, db.freelist_text())

        print("incremental vacuum:", db.incremental_vacuum().render())
        print("after trim:", db.pager.page_count, db.freelist_text())
        print(db.integrity_check().render())

    cleanup(path)


if __name__ == "__main__":
    main()
