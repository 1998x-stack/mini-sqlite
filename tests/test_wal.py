from __future__ import annotations

import os
import zlib

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import TransactionError
from mini_sqlite.storage import wal as wal_module
from mini_sqlite.storage.wal import HEADER_SIZE


def create_items(db: Database) -> None:
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")


def test_wal_commit_survives_reopen_without_checkpoint(tmp_path):
    path = tmp_path / "wal.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        db.execute("INSERT INTO items VALUES (1, 'one');")
        assert db.pager.wal_path.stat().st_size > HEADER_SIZE
        assert db.execute("SELECT * FROM items;").rows == [(1, "one")]

    with Database(path, journal_mode="wal") as reopened:
        assert reopened.execute("SELECT * FROM items;").rows == [(1, "one")]
        assert "overlay_pages=" in reopened.wal_status()


def test_wal_rollback_and_crash_before_commit_do_not_publish(tmp_path):
    path = tmp_path / "private.db"
    db = Database(path, journal_mode="wal")
    create_items(db)
    db.execute("INSERT INTO items VALUES (1, 'stable');")
    wal_size = db.pager.wal_path.stat().st_size

    db.execute("BEGIN;")
    db.execute("INSERT INTO items VALUES (2, 'temporary');")
    db.execute("ROLLBACK;")
    assert db.execute("SELECT * FROM items;").rows == [(1, "stable")]
    assert db.pager.wal_path.stat().st_size == wal_size

    db.execute("BEGIN;")
    db.execute("INSERT INTO items VALUES (3, 'uncommitted');")
    db.flush()
    assert db.pager.wal_path.stat().st_size == wal_size
    db.pager._file.close()

    with Database(path, journal_mode="wal") as recovered:
        assert recovered.execute("SELECT * FROM items;").rows == [(1, "stable")]


def test_wal_ignores_torn_and_complete_uncommitted_tail(tmp_path):
    path = tmp_path / "tail.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        db.execute("INSERT INTO items VALUES (1, 'stable');")
        committed_size = db.pager.wal_path.stat().st_size
        page_zero = bytes(db.pager.get_page(0))

    wal_path = path.parent / (path.name + "-wal")
    with wal_path.open("ab") as wal:
        wal.write(
            wal_module._RECORD.pack(
                wal_module.FRAME_RECORD,
                999,
                0,
                len(page_zero),
                zlib.crc32(page_zero) & 0xFFFFFFFF,
            )
        )
        wal.write(page_zero)
        wal.flush()
        os.fsync(wal.fileno())

    with Database(path, journal_mode="wal") as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.execute("SELECT * FROM items;").rows == [(1, "stable")]
        assert recovered.pager.wal_path.stat().st_size == committed_size

    with wal_path.open("ab") as wal:
        wal.write(b"\x01\x02\x03")
        wal.flush()
        os.fsync(wal.fileno())
    with Database(path, journal_mode="wal") as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.pager.wal_path.stat().st_size == committed_size


def test_multiple_commits_overlay_newest_page_version(tmp_path):
    path = tmp_path / "multi.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        for i in range(1, 6):
            db.execute(f"INSERT INTO items VALUES ({i}, 'v{i}');")
        db.execute("UPDATE items SET body = 'latest' WHERE id = 3;")
        stats = db.pager.wal_stats()
        assert stats["committed_transactions"] >= 7
        assert db.execute("SELECT body FROM items WHERE id = 3;").rows == [("latest",)]

    with Database(path, journal_mode="wal") as reopened:
        assert reopened.execute("SELECT body FROM items WHERE id = 3;").rows == [("latest",)]


def test_checkpoint_moves_overlay_into_database_and_mode_switches(tmp_path):
    path = tmp_path / "checkpoint.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        for i in range(8):
            db.execute(f"INSERT INTO items VALUES ({i}, 'body-{i}');")
        copied = db.checkpoint()
        assert copied > 0
        assert db.pager.wal_path.stat().st_size == HEADER_SIZE
        assert db.pager.wal_stats()["overlay_pages"] == 0

    with Database(path, journal_mode="rollback") as reopened:
        assert reopened.execute("SELECT * FROM items WHERE id = 7;").rows == [(7, "body-7")]


def test_partial_checkpoint_is_safe_while_wal_remains(tmp_path):
    path = tmp_path / "partial.db"
    db = Database(path, journal_mode="wal")
    create_items(db)
    for i in range(12):
        db.execute(f"INSERT INTO items VALUES ({i}, 'value-{i}');")
    expected = db.execute("SELECT * FROM items ORDER BY id;").rows

    overlay = dict(db.pager._wal.overlay)  # type: ignore[union-attr]
    page_id = sorted(overlay)[0]
    db.pager._file.seek(page_id * db.pager.page_size)
    db.pager._file.write(overlay[page_id])
    db.pager._file.flush()
    os.fsync(db.pager._file.fileno())
    db.pager._file.close()

    with Database(path, journal_mode="wal") as recovered:
        assert recovered.execute("SELECT * FROM items ORDER BY id;").rows == expected


def test_wal_handles_btree_splits_new_pages_and_reopen(tmp_path):
    path = tmp_path / "splits.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        with db.transaction():
            for i in range(180):
                db.execute(f"INSERT INTO items VALUES ({i}, '{'x' * 120}{i}');")
        count = db.pager.page_count
        assert count > 3

    with Database(path, journal_mode="wal") as reopened:
        assert reopened.pager.page_count == count
        assert reopened.execute("SELECT body FROM items WHERE id = 179;").rows == [
            ("x" * 120 + "179",)
        ]
        assert reopened.checkpoint() > 0

    with Database(path, journal_mode="rollback") as final:
        assert final.pager.page_count == count
        assert len(final.execute("SELECT * FROM items;").rows) == 180


def test_indexes_and_join_are_unchanged_above_wal(tmp_path):
    path = tmp_path / "join.db"
    with Database(path, journal_mode="wal") as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT);")
        db.execute("CREATE INDEX idx_orders_user ON orders(user_id);")
        db.execute("INSERT INTO users VALUES (1, 'Alice');")
        db.execute("INSERT INTO users VALUES (2, 'Bob');")
        db.execute("INSERT INTO orders VALUES (10, 1, 'book');")
        db.execute("INSERT INTO orders VALUES (11, 1, 'pen');")
        db.execute("INSERT INTO orders VALUES (12, 2, 'bag');")
        sql = (
            "SELECT u.name, o.item FROM users u "
            "JOIN orders o ON u.id = o.user_id ORDER BY o.id;"
        )
        assert "SECONDARY INDEX idx_orders_user" in db.explain(sql)
        assert db.execute(sql).rows == [
            ("Alice", "book"),
            ("Alice", "pen"),
            ("Bob", "bag"),
        ]

    with Database(path, journal_mode="wal") as reopened:
        assert reopened.execute(sql).rows[-1] == ("Bob", "bag")


def test_opening_rollback_mode_checkpoints_existing_wal(tmp_path):
    path = tmp_path / "switch.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        db.execute("INSERT INTO items VALUES (1, 'from-wal');")
        assert db.pager.wal_path.stat().st_size > HEADER_SIZE

    with Database(path, journal_mode="rollback") as switched:
        assert switched.execute("SELECT * FROM items;").rows == [(1, "from-wal")]
        assert not switched.pager.wal_path.exists()


def test_checkpoint_rejected_inside_transaction_and_in_rollback_mode(tmp_path):
    path = tmp_path / "active.db"
    with Database(path, journal_mode="wal") as db:
        create_items(db)
        db.execute("BEGIN;")
        with pytest.raises(TransactionError):
            db.checkpoint()
        db.execute("ROLLBACK;")

    with Database(tmp_path / "rollback.db") as db:
        with pytest.raises(TransactionError):
            db.checkpoint()
