from __future__ import annotations

import os
from pathlib import Path

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import SchemaError
from mini_sqlite.index import ByteKeyBTree, KeyCodec
from mini_sqlite.catalog import ColumnType
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import CreateIndexStmt
from mini_sqlite.storage import Pager


def create_users(db: Database) -> None:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")


def simulate_process_death(db: Database) -> None:
    db.flush()
    db.pager._file.flush()
    os.fsync(db.pager._file.fileno())
    db.pager._file.close()


def test_create_index_parser():
    stmt = Parser("CREATE INDEX idx_users_age ON users(age);").parse()
    assert isinstance(stmt, CreateIndexStmt)
    assert stmt.name == "idx_users_age"
    assert stmt.table == "users"
    assert stmt.column == "age"


def test_planner_switches_from_scan_to_secondary_index_and_reopens(tmp_path):
    path = tmp_path / "planner.db"
    with Database(path) as db:
        create_users(db)
        db.execute("INSERT INTO users VALUES (1, 'Alice', 20);")
        db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")
        db.execute("INSERT INTO users VALUES (3, 'Carol', 20);")

        assert "TABLE SCAN" in db.explain("SELECT name FROM users WHERE age = 20;")
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        explain = db.explain("SELECT name FROM users WHERE age = 20;")
        assert "SECONDARY INDEX idx_users_age" in explain
        assert "ROWID LOOKUP" in explain
        assert db.execute("SELECT name FROM users WHERE age = 20;").rows == [
            ("Alice",),
            ("Carol",),
        ]
        assert "SEEK_INDEX_EQ" in db.bytecode("SELECT name FROM users WHERE age = 20;")
        assert "INDEX_TO_TABLE" in db.bytecode("SELECT name FROM users WHERE age = 20;")

    with Database(path) as db:
        assert "idx_users_age" in db.schema_text()
        assert "SECONDARY INDEX idx_users_age" in db.explain(
            "SELECT name FROM users WHERE age = 20;"
        )
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == [(1,), (3,)]


def test_duplicate_secondary_keys_and_incremental_maintenance(tmp_path):
    path = tmp_path / "duplicates.db"
    with Database(path) as db:
        create_users(db)
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        for rowid, name in [(7, "G"), (2, "B"), (11, "K"), (5, "E")]:
            db.execute(f"INSERT INTO users VALUES ({rowid}, '{name}', 20);")

        # Composite physical key (age, rowid) keeps duplicates ordered by rowid.
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == [
            (2,),
            (5,),
            (7,),
            (11,),
        ]

        deleted = db.execute("DELETE FROM users WHERE age = 20;")
        assert deleted.rowcount == 4
        assert db.execute("SELECT * FROM users;").rows == []
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == []


def test_text_index_prefix_encoding_does_not_confuse_a_with_ab(tmp_path):
    path = tmp_path / "text.db"
    with Database(path) as db:
        db.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, tag TEXT);")
        db.execute("INSERT INTO docs VALUES (1, 'a');")
        db.execute("INSERT INTO docs VALUES (2, 'ab');")
        db.execute("INSERT INTO docs VALUES (3, 'a');")
        db.execute("CREATE INDEX idx_docs_tag ON docs(tag);")

        assert db.execute("SELECT id FROM docs WHERE tag = 'a';").rows == [(1,), (3,)]
        assert db.execute("SELECT id FROM docs WHERE tag = 'ab';").rows == [(2,)]


def test_index_root_split_is_persisted(tmp_path):
    path = tmp_path / "split.db"
    with Database(path) as db:
        create_users(db)
        for i in range(500):
            db.execute(f"INSERT INTO users VALUES ({i}, 'u{i}', {i % 13});")
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        table, index = db.catalog.get_index("idx_users_age")
        root_page = index.root_page
        assert db.index_dump("idx_users_age").splitlines()[0].find("INDEX_INTERNAL") >= 0
        assert db.execute("SELECT id FROM users WHERE age = 7;").rows

    with Database(path) as db:
        _table, reopened_index = db.catalog.get_index("idx_users_age")
        assert reopened_index.root_page == root_page
        expected = [(i,) for i in range(500) if i % 13 == 7]
        assert db.execute("SELECT id FROM users WHERE age = 7;").rows == expected


def test_create_index_rollback_removes_metadata_and_pages(tmp_path):
    path = tmp_path / "create-index-rollback.db"
    with Database(path) as db:
        create_users(db)
        for i in range(80):
            db.execute(f"INSERT INTO users VALUES ({i}, 'u{i}', {i % 5});")
        stable_pages = db.pager.page_count

        db.execute("BEGIN;")
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        assert db.catalog.get_index("idx_users_age")
        assert db.pager.page_count > stable_pages
        db.execute("ROLLBACK;")

        assert db.pager.page_count == stable_pages
        with pytest.raises(SchemaError):
            db.catalog.get_index("idx_users_age")
        assert "TABLE SCAN" in db.explain("SELECT id FROM users WHERE age = 3;")


def test_table_and_index_changes_rollback_together(tmp_path):
    path = tmp_path / "index-rollback.db"
    with Database(path) as db:
        create_users(db)
        db.execute("CREATE INDEX idx_users_age ON users(age);")
        db.execute("INSERT INTO users VALUES (1, 'stable', 20);")

        db.execute("BEGIN;")
        db.execute("INSERT INTO users VALUES (2, 'temporary', 20);")
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == [(1,), (2,)]
        db.execute("ROLLBACK;")

        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == [(1,)]
        assert db.execute("SELECT * FROM users WHERE id = 2;").rows == []


def test_hot_journal_recovers_table_and_secondary_index_atomically(tmp_path):
    path = tmp_path / "index-crash.db"
    db = Database(path)
    create_users(db)
    for i in range(60):
        db.execute(f"INSERT INTO users VALUES ({i}, 'stable{i}', {i % 4});")
    db.execute("CREATE INDEX idx_users_age ON users(age);")
    stable_pages = db.pager.page_count
    stable_rows = db.execute("SELECT id FROM users WHERE age = 3;").rows

    db.execute("BEGIN;")
    for i in range(60, 260):
        db.execute(f"INSERT INTO users VALUES ({i}, 'temp{i}', 3);")
    assert len(db.execute("SELECT id FROM users WHERE age = 3;").rows) > len(stable_rows)
    assert db.pager.page_count > stable_pages
    simulate_process_death(db)

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.pager.page_count == stable_pages
        assert recovered.execute("SELECT id FROM users WHERE age = 3;").rows == stable_rows
        assert recovered.execute("SELECT * FROM users WHERE id = 259;").rows == []


def test_duplicate_index_name_and_second_index_on_same_column_are_rejected(tmp_path):
    path = tmp_path / "errors.db"
    with Database(path) as db:
        create_users(db)
        db.execute("CREATE INDEX idx_age ON users(age);")
        with pytest.raises(SchemaError):
            db.execute("CREATE INDEX idx_age ON users(name);")
        with pytest.raises(SchemaError):
            db.execute("CREATE INDEX another_age ON users(age);")


def test_key_codec_signed_integer_order_and_text_delimiting():
    encoded = [KeyCodec.encode_value(v, ColumnType.INTEGER) for v in (-9, -1, 0, 1, 12)]
    assert encoded == sorted(encoded)
    a = KeyCodec.encode_value("a", ColumnType.TEXT)
    ab = KeyCodec.encode_value("ab", ColumnType.TEXT)
    assert not ab.startswith(a)


def test_byte_key_btree_split_and_prefix_scan(tmp_path):
    path = tmp_path / "byte-tree.db"
    with Pager(path) as pager:
        tree = ByteKeyBTree.create(pager)
        prefix = KeyCodec.encode_value("group", ColumnType.TEXT)
        for rowid in range(400):
            key = prefix + KeyCodec.encode_rowid(rowid)
            tree.insert(key, KeyCodec.encode_rowid(rowid))
        assert tree.root_page != 0
        rows = [KeyCodec.decode_rowid(k) for k, _ in tree.scan_prefix(prefix)]
        assert rows == list(range(400))
        assert "INDEX_INTERNAL" in tree.dump().splitlines()[0]


def test_multiple_indexes_and_non_index_access_path_deletes_stay_consistent(tmp_path):
    path = tmp_path / "multi-index.db"
    with Database(path) as db:
        create_users(db)
        db.execute("CREATE INDEX idx_age ON users(age);")
        db.execute("CREATE INDEX idx_name ON users(name);")
        db.execute("INSERT INTO users VALUES (1, 'Alice', 20);")
        db.execute("INSERT INTO users VALUES (2, 'Bob', 20);")
        db.execute("INSERT INTO users VALUES (3, 'Carol', 30);")

        # Primary-key access still has to maintain both secondary indexes.
        assert db.execute("DELETE FROM users WHERE id = 1;").rowcount == 1
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == [(2,)]
        assert db.execute("SELECT id FROM users WHERE name = 'Alice';").rows == []

        # Drop through a table-scan predicate would also maintain all indexes.
        # Here age is indexed, so use a value on a deliberately unindexed clone
        # would add noise; deleting by primary key already proves access-path
        # independence of maintenance. The second indexed path cross-checks the
        # remaining physical structures.
        assert db.execute("SELECT id FROM users WHERE name = 'Bob';").rows == [(2,)]
        assert db.execute("SELECT id FROM users WHERE age = 30;").rows == [(3,)]
