from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


def main() -> None:
    path = Path("lifecycle.db")
    for candidate in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal")):
        if candidate.exists():
            candidate.unlink()

    with Database(path, buffer_pages=4) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER, name TEXT);")
        for i in range(1, 121):
            db.execute(f"INSERT INTO users VALUES ({i}, {i % 5}, 'user-{i:03d}');")
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        db.execute("ANALYZE users;")

        print("explain analyze:")
        print(
            db.explain_analyze(
                "SELECT id, name FROM users WHERE age = 3 ORDER BY id LIMIT 4;"
            ).render()
        )

        for i in range(41, 121):
            db.execute(f"DELETE FROM users WHERE id = {i};")
        db.reindex("idx_users_age")

        print("\nintegrity before vacuum:")
        print(db.integrity_check().render())

        print("\nvacuum:")
        print(db.vacuum().render())

        print("\nintegrity after vacuum:")
        print(db.integrity_check().render())

    for candidate in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal")):
        if candidate.exists():
            candidate.unlink()


if __name__ == "__main__":
    main()
