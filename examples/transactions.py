"""Observe v0.2 commit and rollback semantics."""

from pathlib import Path
from tempfile import TemporaryDirectory
import sys

# Allow `python examples/transactions.py` directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


def main() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "transactions.db"
        with Database(path) as db:
            db.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);")

            with db.transaction():
                db.execute("INSERT INTO accounts VALUES (1, 'committed');")

            db.execute("BEGIN;")
            db.execute("INSERT INTO accounts VALUES (2, 'rolled-back');")
            print("inside transaction:", db.execute("SELECT * FROM accounts;").rows)
            print("transaction state:", db.transaction_status())
            db.execute("ROLLBACK;")

            print("after rollback:", db.execute("SELECT * FROM accounts;").rows)

        with Database(path) as reopened:
            print("after reopen:", reopened.execute("SELECT * FROM accounts;").rows)


if __name__ == "__main__":
    main()
