"""Observe v0.3 table-scan -> secondary-index planner transition."""

from pathlib import Path
from tempfile import TemporaryDirectory
import sys

# Allow `python examples/indexes.py` directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


def main() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "indexes.db"
        with Database(path) as db:
            db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
            for row in [
                (1, "Alice", 20),
                (2, "Bob", 25),
                (3, "Carol", 20),
                (4, "Dave", 30),
            ]:
                db.execute(
                    f"INSERT INTO users VALUES ({row[0]}, '{row[1]}', {row[2]});"
                )

            query = "SELECT name FROM users WHERE age = 20;"
            print("before:", db.explain(query))
            print("rows:  ", db.execute(query).rows)

            db.execute("CREATE INDEX idx_users_age ON users(age);")

            print("after: ", db.explain(query))
            print("rows:  ", db.execute(query).rows)
            print("\nbytecode:\n" + db.bytecode(query))
            print("\nindex metadata:\n" + db.indexes_text())
            print("\nindex tree:\n" + db.index_dump("idx_users_age"))


if __name__ == "__main__":
    main()
