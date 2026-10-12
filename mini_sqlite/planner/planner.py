from __future__ import annotations

from mini_sqlite.catalog import Catalog
from mini_sqlite.errors import SchemaError
from mini_sqlite.planner.plan import (
    AccessPath,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Plan,
    SelectPlan,
)
from mini_sqlite.sql.ast import CreateTableStmt, DeleteStmt, InsertStmt, SelectStmt, Statement


class Planner:
    """Tiny rule-based planner.

    v0.1 has only two access paths: primary-key seek or full table scan. The
    interface intentionally returns an explicit Plan object so v0.3 can attach
    secondary indexes and v0.8 can replace the rules with a cost model.
    """

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def plan(self, stmt: Statement) -> Plan:
        if isinstance(stmt, CreateTableStmt):
            return CreateTablePlan(stmt.name, stmt.columns)
        if isinstance(stmt, InsertStmt):
            schema = self.catalog.get_table(stmt.table)
            schema.validate_row(stmt.values)
            return InsertPlan(schema, stmt.values)
        if isinstance(stmt, SelectStmt):
            schema = self.catalog.get_table(stmt.table)
            projection, names = self._projection(schema, stmt.columns)
            path = self._choose_access_path(schema, stmt.where)
            return SelectPlan(schema, projection, names, stmt.where, path)
        if isinstance(stmt, DeleteStmt):
            schema = self.catalog.get_table(stmt.table)
            path = self._choose_access_path(schema, stmt.where)
            return DeletePlan(schema, stmt.where, path)
        raise SchemaError(f"unsupported statement type: {type(stmt).__name__}")

    def _projection(self, schema, columns: list[str]) -> tuple[list[int], list[str]]:
        if columns == ["*"]:
            return list(range(len(schema.columns))), [c.name for c in schema.columns]
        indexes = [schema.column_index(name) for name in columns]
        names = [schema.columns[i].name for i in indexes]
        return indexes, names

    @staticmethod
    def _choose_access_path(schema, where) -> AccessPath:
        if where is not None and where.column.lower() == schema.primary_key.name.lower():
            if not isinstance(where.value, int):
                raise SchemaError("INTEGER PRIMARY KEY comparison requires an integer literal")
            return AccessPath.PRIMARY_KEY
        if where is not None:
            schema.column_index(where.column)  # validate now rather than during execution
        return AccessPath.TABLE_SCAN

    @staticmethod
    def explain(plan: Plan) -> str:
        if isinstance(plan, CreateTablePlan):
            return f"CREATE TABLE {plan.name}"
        if isinstance(plan, InsertPlan):
            return f"INSERT INTO {plan.schema.name} USING B+TREE PRIMARY KEY"
        if isinstance(plan, SelectPlan):
            return f"SELECT FROM {plan.schema.name} USING {plan.access_path.value.upper()}"
        if isinstance(plan, DeletePlan):
            return f"DELETE FROM {plan.schema.name} USING {plan.access_path.value.upper()}"
        return repr(plan)
