from __future__ import annotations

import os
from pathlib import Path

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import DuplicateKeyError, TransactionError
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import BeginStmt, CommitStmt, RollbackStmt


def create_items(db: Database) -> None:
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")


def test_transaction_control_parser():
    assert isinstance(Parser("BEGIN;").parse(), BeginStmt)
    assert isinstance(Parser("BEGIN TRANSACTION;").parse(), BeginStmt)
    assert isinstance(Parser("COMMIT;").parse(), CommitStmt)
    assert isinstance(Parser("END TRANSACTION;").parse(), CommitStmt)
    assert isinstance(Parser("ROLLBACK;").parse(), RollbackStmt)


def test_explicit_commit_and_rollback(tmp_path):
    path = tmp_path / "tx.db"
    with Database(path) as db:
        create_items(db)

        db.execute("BEGIN;")
        db.execute("INSERT INTO items VALUES (1, 'one');")
        db.execute("INSERT INTO items VALUES (2, 'two');")
        assert db.execute("SELECT * FROM items;").rows == [(1, "one"), (2, "two")]
        assert db.pager.journal_path.exists()
        db.execute("COMMIT;")
        assert not db.pager.journal_path.exists()

        db.execute("BEGIN;")
        db.execute("INSERT INTO items VALUES (3, 'three');")
        assert db.execute("SELECT body FROM items WHERE id = 3;").rows == [("three",)]
        db.execute("ROLLBACK;")
        assert db.execute("SELECT * FROM items;").rows == [(1, "one"), (2, "two")]
        assert not db.pager.journal_path.exists()

    with Database(path) as db:
        assert db.execute("SELECT * FROM items;").rows == [(1, "one"), (2, "two")]


def test_python_transaction_context_manager(tmp_path):
    path = tmp_path / "context.db"
    with Database(path) as db:
        create_items(db)
        with db.transaction():
            db.execute("INSERT INTO items VALUES (1, 'committed');")
        assert db.execute("SELECT * FROM items;").rows == [(1, "committed")]

        with pytest.raises(RuntimeError):
            with db.transaction():
                db.execute("INSERT INTO items VALUES (2, 'rolled back');")
                raise RuntimeError("application failure")
        assert db.execute("SELECT * FROM items;").rows == [(1, "committed")]


def test_execution_error_aborts_explicit_transaction(tmp_path):
    path = tmp_path / "error.db"
    with Database(path) as db:
        create_items(db)
        db.execute("INSERT INTO items VALUES (1, 'base');")
        db.execute("BEGIN;")
        db.execute("INSERT INTO items VALUES (2, 'temporary');")
        with pytest.raises(DuplicateKeyError):
            db.execute("INSERT INTO items VALUES (1, 'duplicate');")
        assert not db.in_transaction
        assert db.execute("SELECT * FROM items;").rows == [(1, "base")]


def test_close_rolls_back_uncommitted_transaction(tmp_path):
    path = tmp_path / "close.db"
    db = Database(path)
    create_items(db)
    db.execute("BEGIN;")
    db.execute("INSERT INTO items VALUES (1, 'never committed');")
    db.close()

    with Database(path) as reopened:
        assert reopened.execute("SELECT * FROM items;").rows == []


def _simulate_process_death(db: Database) -> None:
    """Leave a hot journal behind without running close()/rollback()."""
    db.flush()  # force uncommitted pages into the main DB, journal stays hot
    db.pager._file.flush()
    os.fsync(db.pager._file.fileno())
    db.pager._file.close()


def test_hot_journal_recovery_after_uncommitted_pages_reach_main_file(tmp_path):
    path = tmp_path / "crash.db"
    db = Database(path)
    create_items(db)
    db.execute("INSERT INTO items VALUES (1, 'stable');")

    db.execute("BEGIN;")
    db.execute("INSERT INTO items VALUES (2, 'uncommitted');")
    assert db.pager.journal_path.exists()
    _simulate_process_death(db)

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.execute("SELECT * FROM items;").rows == [(1, "stable")]
        assert not recovered.pager.journal_path.exists()


def test_crash_recovery_truncates_pages_allocated_by_btree_splits(tmp_path):
    path = tmp_path / "split-crash.db"
    db = Database(path)
    create_items(db)
    for i in range(40):
        db.execute(f"INSERT INTO items VALUES ({i}, '{'a' * 80}{i}');")
    stable_page_count = db.pager.page_count

    db.execute("BEGIN;")
    for i in range(40, 180):
        db.execute(f"INSERT INTO items VALUES ({i}, '{'z' * 120}{i}');")
    assert db.pager.page_count > stable_page_count
    _simulate_process_death(db)

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.pager.page_count == stable_page_count
        rows = recovered.execute("SELECT * FROM items;").rows
        assert len(rows) == 40
        assert rows[-1][0] == 39


def test_create_table_is_rolled_back_with_catalog_and_meta(tmp_path):
    path = tmp_path / "schema-rollback.db"
    with Database(path) as db:
        db.execute("BEGIN;")
        db.execute("CREATE TABLE temporary (id INTEGER PRIMARY KEY, value TEXT);")
        assert "temporary" in db.schema_text()
        db.execute("ROLLBACK;")
        assert db.schema_text() == ""

        # next_table_id must also have returned to its previous value.
        db.execute("CREATE TABLE persistent (id INTEGER PRIMARY KEY, value TEXT);")
        assert db.catalog.get_table("persistent").table_id == 1


def test_nested_transaction_and_commit_without_begin_are_rejected(tmp_path):
    path = tmp_path / "state.db"
    with Database(path) as db:
        db.execute("BEGIN;")
        with pytest.raises(TransactionError):
            db.execute("BEGIN;")
        db.execute("ROLLBACK;")
        with pytest.raises(TransactionError):
            db.execute("COMMIT;")


def test_autocommit_write_commits_and_removes_journal(tmp_path):
    path = tmp_path / "autocommit.db"
    with Database(path) as db:
        create_items(db)
        db.execute("INSERT INTO items VALUES (1, 'durable');")
        assert not db.in_transaction
        assert not db.pager.journal_path.exists()

    with Database(path) as reopened:
        assert reopened.execute("SELECT * FROM items;").rows == [(1, "durable")]


def test_read_only_statement_does_not_create_journal(tmp_path):
    path = tmp_path / "read-only.db"
    with Database(path) as db:
        create_items(db)
        db.execute("SELECT * FROM items;")
        assert not db.pager.journal_path.exists()


def test_torn_trailing_journal_entry_is_ignored_during_recovery(tmp_path):
    path = tmp_path / "torn-tail.db"
    db = Database(path)
    create_items(db)
    db.execute("INSERT INTO items VALUES (1, 'stable');")

    db.execute("BEGIN;")
    db.execute("INSERT INTO items VALUES (2, 'uncommitted');")
    db.flush()
    with db.pager.journal_path.open("ab") as journal:
        journal.write(b"\x00\x01")  # incomplete next entry header
        journal.flush()
        os.fsync(journal.fileno())
    db.pager._file.close()

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.execute("SELECT * FROM items;").rows == [(1, "stable")]
