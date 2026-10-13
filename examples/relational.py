"""v0.4 relational execution walkthrough."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys

# Allow `python examples/relational.py` directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


with TemporaryDirectory() as tmp:
    path = Path(tmp) / "relational.db"
    with Database(path) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
        for sql in (
            "INSERT INTO users VALUES (1, 'Alice', 20);",
            "INSERT INTO users VALUES (2, 'Bob', 35);",
            "INSERT INTO users VALUES (3, 'Carol', 25);",
            "INSERT INTO users VALUES (4, 'Dave', 35);",
        ):
            db.execute(sql)

        db.execute("CREATE INDEX idx_users_age ON users(age);")

        query = "SELECT name FROM users WHERE age >= 20 ORDER BY age DESC LIMIT 3;"
        print("EXPLAIN")
        print(db.explain(query))
        print("\nBYTECODE")
        print(db.bytecode(query))
        print("\nRESULT")
        print(db.execute(query).rows)

        print("\nAGGREGATE")
        print(db.execute("SELECT COUNT(*), SUM(age), MIN(age), MAX(age) FROM users;").rows)

        print("\nUPDATE THROUGH SECONDARY INDEX")
        print(db.explain("UPDATE users SET age = 36 WHERE age = 35;"))
        changed = db.execute("UPDATE users SET age = 36 WHERE age = 35;")
        print("changed:", changed.rowcount)
        print(db.execute("SELECT id, age FROM users ORDER BY id;").rows)
