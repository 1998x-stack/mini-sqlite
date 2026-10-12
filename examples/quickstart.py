from pathlib import Path
import sys

# Allow `python examples/quickstart.py` directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


with Database("example.db") as db:
    if not db.schema_text():
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
        db.execute("INSERT INTO users VALUES (1, 'Alice', 20);")
        db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")

    print(db.execute("SELECT * FROM users;").rows)
    print(db.explain("SELECT * FROM users WHERE id = 2;"))
    print(db.bytecode("SELECT * FROM users WHERE id = 2;"))
    print(db.btree_dump("users"))
