from __future__ import annotations

import os

import pytest

from mini_sqlite import Database
from mini_sqlite.errors import SchemaError
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import AggregateExpr, CompareOp, SelectStmt, UpdateStmt


def seed_users(db: Database) -> None:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);")
    db.execute("INSERT INTO users VALUES (1, 'Alice', 20);")
    db.execute("INSERT INTO users VALUES (2, 'Bob', 35);")
    db.execute("INSERT INTO users VALUES (3, 'Carol', 25);")
    db.execute("INSERT INTO users VALUES (4, 'Dave', 35);")
    db.execute("INSERT INTO users VALUES (5, 'Eve', NULL);")


def simulate_process_death(db: Database) -> None:
    db.flush()
    db.pager._file.flush()
    os.fsync(db.pager._file.fileno())
    db.pager._file.close()


def test_parser_v04_select_pipeline_and_update():
    stmt = Parser(
        "SELECT id, name FROM users WHERE age >= 21 ORDER BY age DESC LIMIT 3;"
    ).parse()
    assert isinstance(stmt, SelectStmt)
    assert stmt.columns == ["id", "name"]
    assert stmt.where.op == CompareOp.GE
    assert stmt.order_by.column == "age"
    assert stmt.order_by.descending is True
    assert stmt.limit == 3

    agg = Parser("SELECT COUNT(*), SUM(age), MIN(age), MAX(age) FROM users;").parse()
    assert isinstance(agg, SelectStmt)
    assert all(isinstance(item, AggregateExpr) for item in agg.items)

    update = Parser("UPDATE users SET name = 'A', age = 21 WHERE id != 9;").parse()
    assert isinstance(update, UpdateStmt)
    assert len(update.assignments) == 2
    assert update.where.op == CompareOp.NE


def test_comparison_predicates_and_range_scan(tmp_path):
    with Database(tmp_path / "compare.db") as db:
        seed_users(db)
        db.execute("CREATE INDEX idx_age ON users(age);")

        # Equality still uses the v0.3 secondary index.
        assert "SECONDARY INDEX idx_age" in db.explain(
            "SELECT id FROM users WHERE age = 35;"
        )
        # Range access is intentionally a scan until range index cursors exist.
        assert "TABLE SCAN" in db.explain("SELECT id FROM users WHERE age >= 25;")

        assert db.execute("SELECT id FROM users WHERE age != 35 ORDER BY id;").rows == [
            (1,),
            (3,),
            (5,),
        ]
        assert db.execute("SELECT id FROM users WHERE age < 30 ORDER BY id;").rows == [
            (1,),
            (3,),
        ]
        assert db.execute("SELECT id FROM users WHERE age <= 25 ORDER BY id;").rows == [
            (1,),
            (3,),
        ]
        assert db.execute("SELECT id FROM users WHERE age > 25 ORDER BY id;").rows == [
            (2,),
            (4,),
        ]
        assert db.execute("SELECT id FROM users WHERE age >= 35 ORDER BY id;").rows == [
            (2,),
            (4,),
        ]


def test_order_by_limit_and_hidden_sort_column(tmp_path):
    with Database(tmp_path / "sort.db") as db:
        seed_users(db)
        # ORDER BY operates on full source rows before projection, so the sort
        # column need not appear in the SELECT list.
        result = db.execute("SELECT name FROM users ORDER BY age DESC LIMIT 3;")
        assert result.columns == ["name"]
        assert result.rows == [("Bob",), ("Dave",), ("Carol",)]

        asc = db.execute("SELECT id, age FROM users ORDER BY age ASC LIMIT 2;")
        assert asc.rows == [(5, None), (1, 20)]
        explain = db.explain("SELECT name FROM users ORDER BY age DESC LIMIT 3;")
        assert "SORT age DESC" in explain
        assert "PROJECT name" in explain
        assert "LIMIT 3" in explain


def test_aggregates_and_empty_input(tmp_path):
    with Database(tmp_path / "aggregate.db") as db:
        seed_users(db)
        result = db.execute(
            "SELECT COUNT(*), COUNT(age), SUM(age), MIN(age), MAX(age) FROM users;"
        )
        assert result.columns == ["COUNT(*)", "COUNT(age)", "SUM(age)", "MIN(age)", "MAX(age)"]
        assert result.rows == [(5, 4, 115, 20, 35)]

        filtered = db.execute(
            "SELECT COUNT(*), SUM(age), MIN(age), MAX(age) FROM users WHERE age > 100;"
        )
        assert filtered.rows == [(0, None, None, None)]

        limited = db.execute("SELECT COUNT(*) FROM users LIMIT 0;")
        assert limited.rows == []


def test_invalid_aggregate_shapes_are_rejected(tmp_path):
    with Database(tmp_path / "aggregate-errors.db") as db:
        seed_users(db)
        with pytest.raises(SchemaError):
            db.execute("SELECT name, COUNT(*) FROM users;")
        with pytest.raises(SchemaError):
            db.execute("SELECT SUM(name) FROM users;")
        with pytest.raises(SchemaError):
            db.execute("SELECT COUNT(*) FROM users ORDER BY age;")


def test_update_primary_key_and_range_paths(tmp_path):
    path = tmp_path / "update.db"
    with Database(path) as db:
        seed_users(db)
        db.execute("CREATE INDEX idx_age ON users(age);")
        db.execute("CREATE INDEX idx_name ON users(name);")

        updated = db.execute("UPDATE users SET name = 'Bobby', age = 40 WHERE id = 2;")
        assert updated.rowcount == 1
        assert db.execute("SELECT id FROM users WHERE name = 'Bob';").rows == []
        assert db.execute("SELECT id FROM users WHERE name = 'Bobby';").rows == [(2,)]
        assert db.execute("SELECT id FROM users WHERE age = 35;").rows == [(4,)]
        assert db.execute("SELECT id FROM users WHERE age = 40;").rows == [(2,)]

        # Range predicate uses a scan, but all secondary indexes must still stay valid.
        updated = db.execute("UPDATE users SET age = 30 WHERE age < 30;")
        assert updated.rowcount == 2
        assert db.execute("SELECT id FROM users WHERE age = 30 ORDER BY id;").rows == [(1,), (3,)]
        assert db.execute("SELECT id FROM users WHERE age = 20;").rows == []
        assert db.execute("SELECT id FROM users WHERE age = 25;").rows == []

    with Database(path) as reopened:
        assert reopened.execute("SELECT name, age FROM users WHERE id = 2;").rows == [("Bobby", 40)]
        assert reopened.execute("SELECT id FROM users WHERE age = 30 ORDER BY id;").rows == [(1,), (3,)]


def test_update_via_secondary_index_can_change_indexed_value(tmp_path):
    with Database(tmp_path / "update-index.db") as db:
        seed_users(db)
        db.execute("CREATE INDEX idx_age ON users(age);")
        assert "SECONDARY INDEX idx_age" in db.explain(
            "UPDATE users SET age = 36 WHERE age = 35;"
        )
        result = db.execute("UPDATE users SET age = 36 WHERE age = 35;")
        assert result.rowcount == 2
        assert db.execute("SELECT id FROM users WHERE age = 35;").rows == []
        assert db.execute("SELECT id FROM users WHERE age = 36;").rows == [(2,), (4,)]


def test_update_rollback_and_hot_journal_restore_table_and_indexes(tmp_path):
    path = tmp_path / "update-crash.db"
    db = Database(path)
    seed_users(db)
    db.execute("CREATE INDEX idx_age ON users(age);")
    db.execute("CREATE INDEX idx_name ON users(name);")

    db.execute("BEGIN;")
    db.execute("UPDATE users SET name = 'TEMP', age = 99 WHERE age >= 25;")
    assert db.execute("SELECT id FROM users WHERE age = 99 ORDER BY id;").rows == [(2,), (3,), (4,)]
    simulate_process_death(db)

    with Database(path) as recovered:
        assert recovered.pager.recovery_performed is True
        assert recovered.execute("SELECT id FROM users WHERE age = 99;").rows == []
        assert recovered.execute("SELECT id FROM users WHERE name = 'TEMP';").rows == []
        assert recovered.execute("SELECT name, age FROM users ORDER BY id;").rows == [
            ("Alice", 20),
            ("Bob", 35),
            ("Carol", 25),
            ("Dave", 35),
            ("Eve", None),
        ]


def test_updating_primary_key_is_explicit_non_goal(tmp_path):
    with Database(tmp_path / "pk-update.db") as db:
        seed_users(db)
        with pytest.raises(SchemaError):
            db.execute("UPDATE users SET id = 10 WHERE id = 1;")


def test_v04_bytecode_exposes_pipeline_stages(tmp_path):
    with Database(tmp_path / "pipeline.db") as db:
        seed_users(db)
        text = db.bytecode(
            "SELECT name FROM users WHERE age >= 20 ORDER BY age DESC LIMIT 2;"
        )
        for opcode in (
            "FILTER_COMPARE",
            "COLLECT_ROW",
            "SORT_ROWS",
            "PROJECT_ROWS",
            "LIMIT_ROWS",
            "EMIT_ROWS",
        ):
            assert opcode in text

        agg = db.bytecode("SELECT COUNT(*), SUM(age) FROM users WHERE age >= 20;")
        assert "AGGREGATE_ROWS" in agg
