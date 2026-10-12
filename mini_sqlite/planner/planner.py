from __future__ import annotations

from mini_sqlite.catalog import Catalog, IndexSchema, TableSchema
from mini_sqlite.errors import SchemaError
from mini_sqlite.planner.plan import (
    AccessPath,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Plan,
    SelectPlan,
)
from mini_sqlite.sql.ast import (
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    SelectStmt,
    Statement,
)


class Planner:
    """Rule-based access-path planner.

    v0.3 makes physical alternatives explicit:

        PRIMARY_KEY_SEEK > SECONDARY_INDEX_SEEK > TABLE_SCAN

    This is intentionally not cost based. v0.8 can replace the rule with a cost
    model without changing Parser, Plan, Compiler, or VM boundaries.
    """

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def plan(self, stmt: Statement) -> Plan:
        if isinstance(stmt, CreateTableStmt):
            return CreateTablePlan(stmt.name, stmt.columns)
        if isinstance(stmt, CreateIndexStmt):
            table = self.catalog.get_table(stmt.table)
            table.column(stmt.column)
            return CreateIndexPlan(stmt.name, table.name, stmt.column)
        if isinstance(stmt, InsertStmt):
            schema = self.catalog.get_table(stmt.table)
            schema.validate_row(stmt.values)
            return InsertPlan(schema, stmt.values)
        if isinstance(stmt, SelectStmt):
            schema = self.catalog.get_table(stmt.table)
            projection, names = self._projection(schema, stmt.columns)
            path, index = self._choose_access_path(schema, stmt.where)
            return SelectPlan(schema, projection, names, stmt.where, path, index)
        if isinstance(stmt, DeleteStmt):
            schema = self.catalog.get_table(stmt.table)
            path, index = self._choose_access_path(schema, stmt.where)
            return DeletePlan(schema, stmt.where, path, index)
        raise SchemaError(f"unsupported statement type: {type(stmt).__name__}")

    def _projection(self, schema: TableSchema, columns: list[str]) -> tuple[list[int], list[str]]:
        if columns == ["*"]:
            return list(range(len(schema.columns))), [c.name for c in schema.columns]
        indexes = [schema.column_index(name) for name in columns]
        names = [schema.columns[i].name for i in indexes]
        return indexes, names

    @staticmethod
    def _choose_access_path(schema: TableSchema, where) -> tuple[AccessPath, IndexSchema | None]:
        if where is None:
            return AccessPath.TABLE_SCAN, None

        schema.validate_literal(where.column, where.value)
        if where.column.lower() == schema.primary_key.name.lower():
            return AccessPath.PRIMARY_KEY, None

        index = schema.index_on_column(where.column)
        if index is not None:
            return AccessPath.SECONDARY_INDEX, index
        return AccessPath.TABLE_SCAN, None

    @staticmethod
    def explain(plan: Plan) -> str:
        if isinstance(plan, CreateTablePlan):
            return f"CREATE TABLE {plan.name}"
        if isinstance(plan, CreateIndexPlan):
            return f"CREATE INDEX {plan.name} ON {plan.table}({plan.column}) USING B+TREE"
        if isinstance(plan, InsertPlan):
            suffix = f" + {len(plan.schema.indexes)} SECONDARY INDEX(ES)" if plan.schema.indexes else ""
            return f"INSERT INTO {plan.schema.name} USING B+TREE PRIMARY KEY{suffix}"
        if isinstance(plan, SelectPlan):
            if plan.access_path == AccessPath.SECONDARY_INDEX:
                assert plan.index is not None
                return (
                    f"SELECT FROM {plan.schema.name} USING SECONDARY INDEX {plan.index.name} "
                    f"ON {plan.index.column} -> ROWID LOOKUP"
                )
            return f"SELECT FROM {plan.schema.name} USING {plan.access_path.value.upper()}"
        if isinstance(plan, DeletePlan):
            if plan.access_path == AccessPath.SECONDARY_INDEX:
                assert plan.index is not None
                return (
                    f"DELETE FROM {plan.schema.name} USING SECONDARY INDEX {plan.index.name} "
                    f"ON {plan.index.column} -> ROWID LOOKUP"
                )
            return f"DELETE FROM {plan.schema.name} USING {plan.access_path.value.upper()}"
        return repr(plan)
