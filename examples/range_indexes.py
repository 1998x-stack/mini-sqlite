from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


path = Path("range-index-demo.db")
for suffix in ("", "-journal", "-wal", "-lock-mode", "-lock-pending", "-lock-readers", "-lock-writer"):
    candidate = Path(str(path) + suffix)
    if candidate.exists():
        candidate.unlink()

with Database(path) as db:
    db.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, region TEXT, ts INTEGER, note TEXT);"
    )
    rows = [
        (1, "us", 10, "a"),
        (2, "us", 20, "b"),
        (3, "us", 30, "c"),
        (4, "us", 40, "d"),
        (5, "eu", 20, "e"),
        (6, "eu", 30, "f"),
    ]
    for row in rows:
        db.execute(f"INSERT INTO events VALUES ({row[0]}, '{row[1]}', {row[2]}, '{row[3]}');")

    db.execute("CREATE INDEX idx_region_ts ON events(region, ts);")

    sql = (
        "SELECT id, ts FROM events "
        "WHERE region = 'us' AND ts BETWEEN 20 AND 40 ORDER BY id;"
    )
    print("query:")
    print(sql)
    print("rows:", db.execute(sql).rows)
    print("\nplan:")
    print(db.explain(sql))
    print("\nbytecode:")
    print(db.bytecode(sql))

    print("\nleft-prefix query:")
    prefix = "SELECT id FROM events WHERE region = 'eu' ORDER BY id;"
    print(db.explain(prefix))
    print(db.execute(prefix).rows)

    print("\nmissing-left-prefix query:")
    no_prefix = "SELECT id FROM events WHERE ts >= 20 ORDER BY id;"
    print(db.explain(no_prefix))
    print(db.execute(no_prefix).rows)

for suffix in ("", "-journal", "-wal", "-lock-mode", "-lock-pending", "-lock-readers", "-lock-writer"):
    candidate = Path(str(path) + suffix)
    if candidate.exists():
        candidate.unlink()
