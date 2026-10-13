from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


def main() -> None:
    path = Path("optimizer-demo.db")
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal")):
        candidate.unlink(missing_ok=True)

    with Database(path, buffer_pages=8) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, grp INTEGER, name TEXT);")
        for i in range(1, 101):
            grp = 1 if i <= 90 else i
            db.execute(f"INSERT INTO users VALUES ({i}, {grp}, 'u{i}');")
        db.execute("CREATE INDEX idx_users_grp ON users(grp);")
        print("before ANALYZE:")
        print(db.explain("SELECT * FROM users WHERE grp = 1;"))

        db.execute("ANALYZE users;")
        print("\nstatistics:")
        stats = db.catalog.get_table("users").stats
        assert stats is not None
        print(f"users: rows={stats.row_count}")
        for name, col in stats.columns.items():
            print(
                f"  {name}: nulls={col.null_count} distinct={col.distinct_count} "
                f"min={col.min_value!r} max={col.max_value!r} mcv={col.most_common[:5]}"
            )

        print("\nhot value (90 rows):")
        print(db.explain("SELECT * FROM users WHERE grp = 1;"))
        print("\nrare value (1 row):")
        print(db.explain("SELECT * FROM users WHERE grp = 95;"))

        db.execute("CREATE TABLE small (id INTEGER PRIMARY KEY, grp INTEGER);")
        for i in range(1, 6):
            db.execute(f"INSERT INTO small VALUES ({i}, {i});")
        db.execute("ANALYZE;")
        join_sql = (
            "SELECT users.id, small.id FROM users "
            "JOIN small ON users.grp = small.grp;"
        )
        print("\njoin plan:")
        print(db.explain(join_sql))
        print("join rows:", len(db.execute(join_sql).rows))

    path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
