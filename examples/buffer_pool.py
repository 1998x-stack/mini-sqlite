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
        path = Path(tmp) / "buffer.db"
        with Database(
            path,
            buffer_pages=3,
            replacement_policy="clock",
        ) as db:
            db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
            for i in range(80):
                db.execute(f"INSERT INTO items VALUES ({i}, '{'x' * 160}{i}');")

            db.pager.clear_cache()
            before = db.pager.buffer_stats()
            db.execute("SELECT * FROM items ORDER BY id;")
            after_scan = db.pager.buffer_stats()

            for _ in range(8):
                db.execute("SELECT body FROM items WHERE id = 79;")
            after_hot_lookup = db.pager.buffer_stats()

            print("before scan:", before)
            print("after bounded scan:", after_scan)
            print("after hot PK lookups:", after_hot_lookup)
            print("resident frames:")
            print(db.buffer_frames_text())


if __name__ == "__main__":
    main()
