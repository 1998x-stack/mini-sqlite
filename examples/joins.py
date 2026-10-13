from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_sqlite import Database  # noqa: E402


def main() -> None:
    path = ROOT / "join-demo.db"
    path.unlink(missing_ok=True)

    with Database(path) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        db.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT, amount INTEGER);"
        )
        for sql in (
            "INSERT INTO users VALUES (1, 'Alice');",
            "INSERT INTO users VALUES (2, 'Bob');",
            "INSERT INTO users VALUES (3, 'Carol');",
            "INSERT INTO orders VALUES (10, 1, 'Book', 50);",
            "INSERT INTO orders VALUES (11, 1, 'Pen', 5);",
            "INSERT INTO orders VALUES (12, 2, 'Bag', 80);",
        ):
            db.execute(sql)

        query = (
            "SELECT u.name, o.item, o.amount "
            "FROM users u JOIN orders o ON u.id=o.user_id "
            "ORDER BY o.id;"
        )

        print("== before secondary index ==")
        print(db.explain(query))
        print(db.bytecode(query))
        print(db.execute(query).rows)

        db.execute("CREATE INDEX idx_orders_user ON orders(user_id);")
        print("\n== after secondary index ==")
        print(db.explain(query))
        print(db.bytecode(query))
        print(db.execute(query).rows)

        reverse = (
            "SELECT o.id, u.name FROM orders o JOIN users u ON o.user_id=u.id ORDER BY o.id;"
        )
        print("\n== primary-key inner lookup ==")
        print(db.explain(reverse))
        print(db.execute(reverse).rows)

        aggregate = (
            "SELECT COUNT(*), SUM(o.amount) "
            "FROM users u JOIN orders o ON u.id=o.user_id;"
        )
        print("\n== aggregate after join ==")
        print(db.execute(aggregate).rows)

    path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
