from __future__ import annotations

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import SchemaError
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import SelectStmt


def seed_shop(db: Database) -> None:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
    db.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT, amount INTEGER);"
    )
    for sql in [
        "INSERT INTO users VALUES (1, 'Alice', 20);",
        "INSERT INTO users VALUES (2, 'Bob', 30);",
        "INSERT INTO users VALUES (3, 'Carol', 40);",
        "INSERT INTO orders VALUES (10, 1, 'Book', 50);",
        "INSERT INTO orders VALUES (11, 1, 'Pen', 5);",
        "INSERT INTO orders VALUES (12, 2, 'Bag', 80);",
        "INSERT INTO orders VALUES (13, 99, 'Orphan', 1);",
    ]:
        db.execute(sql)


def test_parser_join_aliases_and_qualified_columns():
    stmt = Parser(
        "SELECT u.name, o.item FROM users AS u INNER JOIN orders o "
        "ON u.id = o.user_id WHERE o.amount >= 10 ORDER BY o.id DESC LIMIT 2;"
    ).parse()
    assert isinstance(stmt, SelectStmt)
    assert stmt.table == "users"
    assert stmt.table_alias == "u"
    assert stmt.join is not None
    assert stmt.join.right.name == "orders"
    assert stmt.join.right.alias == "o"
    assert stmt.join.left_column == "u.id"
    assert stmt.join.right_column == "o.user_id"
    assert stmt.columns == ["u.name", "o.item"]
    assert stmt.where.column == "o.amount"
    assert stmt.order_by.column == "o.id"
    assert stmt.limit == 2


def test_plain_nested_loop_join_and_duplicate_matches(tmp_path):
    with Database(tmp_path / "nested.db") as db:
        seed_shop(db)
        sql = "SELECT u.name, o.item FROM users u JOIN orders o ON u.id = o.user_id ORDER BY o.id;"
        explain = db.explain(sql)
        assert "NESTED LOOP" in explain
        assert "INNER TABLE SCAN" in explain
        assert "INDEXED NESTED LOOP" not in explain
        assert db.execute(sql).rows == [
            ("Alice", "Book"),
            ("Alice", "Pen"),
            ("Bob", "Bag"),
        ]
        bytecode = db.bytecode(sql)
        assert "FILTER_JOIN_EQ" in bytecode
        assert "COLLECT_JOIN_ROW" in bytecode


def test_secondary_index_switches_join_algorithm(tmp_path):
    path = tmp_path / "index-join.db"
    sql = "SELECT u.name, o.item FROM users u JOIN orders o ON u.id=o.user_id ORDER BY o.id;"
    with Database(path) as db:
        seed_shop(db)
        assert "INNER TABLE SCAN" in db.explain(sql)
        db.execute("CREATE INDEX idx_orders_user ON orders(user_id);")
        explain = db.explain(sql)
        assert "INDEXED NESTED LOOP" in explain
        assert "SECONDARY INDEX idx_orders_user" in explain
        assert db.execute(sql).rows == [
            ("Alice", "Book"),
            ("Alice", "Pen"),
            ("Bob", "Bag"),
        ]
        code = db.bytecode(sql)
        assert "SEEK_INDEX_FROM_COLUMN" in code
        assert "INDEX_TO_TABLE" in code
        assert "FILTER_JOIN_EQ" not in code

    with Database(path) as reopened:
        assert "SECONDARY INDEX idx_orders_user" in reopened.explain(sql)
        assert reopened.execute(sql).rows[-1] == ("Bob", "Bag")


def test_primary_key_indexed_nested_loop(tmp_path):
    with Database(tmp_path / "pk-join.db") as db:
        seed_shop(db)
        sql = (
            "SELECT o.id, u.name FROM orders o JOIN users u ON o.user_id = u.id "
            "ORDER BY o.id;"
        )
        explain = db.explain(sql)
        assert "INDEXED NESTED LOOP" in explain
        assert "INNER PRIMARY KEY u.id" in explain
        assert db.execute(sql).rows == [(10, "Alice"), (11, "Alice"), (12, "Bob")]
        code = db.bytecode(sql)
        assert "SEEK_PK_FROM_COLUMN" in code
        assert "OPEN_INDEX" not in code


def test_join_post_pipeline_filter_sort_limit_and_aggregate(tmp_path):
    with Database(tmp_path / "pipeline.db") as db:
        seed_shop(db)
        sql = (
            "SELECT o.id, u.name, o.amount FROM orders o JOIN users u ON o.user_id=u.id "
            "WHERE o.amount >= 10 ORDER BY o.amount DESC LIMIT 2;"
        )
        result = db.execute(sql)
        assert result.columns == ["o.id", "u.name", "o.amount"]
        assert result.rows == [(12, "Bob", 80), (10, "Alice", 50)]
        code = db.bytecode(sql)
        for opcode in (
            "COLLECT_JOIN_ROW",
            "FILTER_ROWS",
            "SORT_ROWS",
            "PROJECT_ROWS",
            "LIMIT_ROWS",
            "EMIT_ROWS",
        ):
            assert opcode in code

        agg = db.execute(
            "SELECT COUNT(*), SUM(o.amount), MIN(o.amount), MAX(o.amount) "
            "FROM users u JOIN orders o ON u.id=o.user_id;"
        )
        assert agg.rows == [(3, 135, 5, 80)]


def test_ambiguous_columns_require_qualification(tmp_path):
    with Database(tmp_path / "ambiguous.db") as db:
        seed_shop(db)
        with pytest.raises(SchemaError, match="ambiguous column"):
            db.execute("SELECT id FROM users u JOIN orders o ON u.id=o.user_id;")
        with pytest.raises(SchemaError, match="ambiguous column"):
            db.execute(
                "SELECT u.name FROM users u JOIN orders o ON u.id=o.user_id ORDER BY id;"
            )
        assert db.execute(
            "SELECT u.id, o.id FROM users u JOIN orders o ON u.id=o.user_id ORDER BY o.id;"
        ).rows == [(1, 10), (1, 11), (2, 12)]


def test_unqualified_unique_columns_and_select_star(tmp_path):
    with Database(tmp_path / "names.db") as db:
        seed_shop(db)
        assert db.execute(
            "SELECT name, item FROM users u JOIN orders o ON u.id=o.user_id ORDER BY o.id;"
        ).rows == [("Alice", "Book"), ("Alice", "Pen"), ("Bob", "Bag")]
        result = db.execute(
            "SELECT * FROM users u JOIN orders o ON u.id=o.user_id ORDER BY o.id LIMIT 1;"
        )
        assert result.columns == [
            "u.id",
            "u.name",
            "u.age",
            "o.id",
            "o.user_id",
            "o.item",
            "o.amount",
        ]
        assert result.rows == [(1, "Alice", 20, 10, 1, "Book", 50)]


def test_self_join_works_with_aliases(tmp_path):
    with Database(tmp_path / "self.db") as db:
        db.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, manager_id INTEGER, name TEXT);")
        db.execute("INSERT INTO people VALUES (1, NULL, 'CEO');")
        db.execute("INSERT INTO people VALUES (2, 1, 'Alice');")
        db.execute("INSERT INTO people VALUES (3, 1, 'Bob');")
        sql = (
            "SELECT e.name, m.name FROM people e JOIN people m ON e.manager_id=m.id "
            "ORDER BY e.id;"
        )
        assert "INNER PRIMARY KEY m.id" in db.explain(sql)
        assert db.execute(sql).rows == [("Alice", "CEO"), ("Bob", "CEO")]


def test_join_column_type_mismatch_is_rejected(tmp_path):
    with Database(tmp_path / "types.db") as db:
        db.execute("CREATE TABLE ints (id INTEGER PRIMARY KEY, key1 INTEGER);")
        db.execute("CREATE TABLE texts (id INTEGER PRIMARY KEY, key2 TEXT);")
        with pytest.raises(SchemaError, match="compatible types"):
            db.execute("SELECT * FROM ints i JOIN texts t ON i.key1=t.key2;")


def test_join_is_read_only_inside_explicit_transaction(tmp_path):
    with Database(tmp_path / "tx.db") as db:
        seed_shop(db)
        db.execute("BEGIN;")
        result = db.execute(
            "SELECT u.name, o.item FROM users u JOIN orders o ON u.id=o.user_id ORDER BY o.id;"
        )
        assert result.rows[0] == ("Alice", "Book")
        assert db.in_transaction is True
        db.execute("ROLLBACK;")
