from mini_sqlite.catalog.schema import ColumnType
from mini_sqlite.sql.ast import CreateTableStmt, SelectStmt
from mini_sqlite.sql.parser import Parser


def test_create_table_parser():
    stmt = Parser(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);"
    ).parse()
    assert isinstance(stmt, CreateTableStmt)
    assert stmt.name == "users"
    assert stmt.columns[0].primary_key is True
    assert stmt.columns[1].type == ColumnType.TEXT


def test_select_parser_with_where():
    stmt = Parser("SELECT id, name FROM users WHERE id = 7;").parse()
    assert isinstance(stmt, SelectStmt)
    assert stmt.columns == ["id", "name"]
    assert stmt.where.column == "id"
    assert stmt.where.value == 7
