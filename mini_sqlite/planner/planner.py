from __future__ import annotations

from mini_sqlite.catalog import Catalog, ColumnType, IndexSchema, TableSchema
from mini_sqlite.errors import SchemaError
from mini_sqlite.planner.plan import (
    AccessPath,
    AggregateSpec,
    AssignmentSpec,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    OrderSpec,
    Plan,
    SelectPlan,
    UpdatePlan,
)
from mini_sqlite.sql.ast import (
    AggregateExpr,
    AggregateFunction,
    CompareOp,
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    SelectStmt,
    Statement,
    UpdateStmt,
)


class Planner:
    """Rule-based planner with explicit access paths and relational stages.

    v0.4 keeps v0.3's access-path rule and adds logical processing stages:

        source -> filter -> sort -> aggregate/project -> limit -> result

    The rule-based access-path choice remains intentionally simple so v0.8 can
    replace it with cost-based selection without changing the SQL frontend.
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
            return self._select(stmt)
        if isinstance(stmt, DeleteStmt):
            schema = self.catalog.get_table(stmt.table)
            self._validate_predicate(schema, stmt.where)
            path, index = self._choose_access_path(schema, stmt.where)
            return DeletePlan(schema, stmt.where, path, index)
        if isinstance(stmt, UpdateStmt):
            return self._update(stmt)
        raise SchemaError(f"unsupported statement type: {type(stmt).__name__}")

    def _select(self, stmt: SelectStmt) -> SelectPlan:
        schema = self.catalog.get_table(stmt.table)
        self._validate_predicate(schema, stmt.where)
        path, index = self._choose_access_path(schema, stmt.where)

        aggregate_items = [item for item in stmt.items if isinstance(item, AggregateExpr)]
        column_items = [item for item in stmt.items if isinstance(item, str)]
        if aggregate_items and column_items:
            raise SchemaError("v0.4 does not mix aggregate and non-aggregate SELECT items")

        aggregates: tuple[AggregateSpec, ...] = ()
        if aggregate_items:
            specs: list[AggregateSpec] = []
            for expr in aggregate_items:
                if expr.column is None:
                    if expr.function != AggregateFunction.COUNT:
                        raise SchemaError(f"{expr.function.value}(*) is not supported")
                    column_index = None
                else:
                    column_index = schema.column_index(expr.column)
                    column = schema.columns[column_index]
                    if expr.function == AggregateFunction.SUM and column.type != ColumnType.INTEGER:
                        raise SchemaError("SUM requires an INTEGER column")
                specs.append(AggregateSpec(expr.function, column_index, expr.display_name))
            aggregates = tuple(specs)
            projection: list[int] = []
            names = [spec.output_name for spec in specs]
            if stmt.order_by is not None:
                raise SchemaError("ORDER BY with aggregate queries is deferred until GROUP BY support")
        else:
            projection, names = self._projection(schema, column_items)

        order_by = None
        if stmt.order_by is not None:
            order_by = OrderSpec(
                schema.column_index(stmt.order_by.column),
                stmt.order_by.column,
                stmt.order_by.descending,
            )

        return SelectPlan(
            schema=schema,
            projection=projection,
            projection_names=names,
            where=stmt.where,
            access_path=path,
            index=index,
            order_by=order_by,
            limit=stmt.limit,
            aggregates=aggregates,
        )

    def _update(self, stmt: UpdateStmt) -> UpdatePlan:
        schema = self.catalog.get_table(stmt.table)
        self._validate_predicate(schema, stmt.where)
        seen: set[int] = set()
        assignments: list[AssignmentSpec] = []
        for assignment in stmt.assignments:
            column_index = schema.column_index(assignment.column)
            if column_index in seen:
                raise SchemaError(f"column {assignment.column!r} assigned more than once")
            seen.add(column_index)
            if column_index == schema.primary_key_index:
                raise SchemaError("v0.4 UPDATE cannot change the INTEGER PRIMARY KEY")
            schema.validate_literal(assignment.column, assignment.value)
            assignments.append(
                AssignmentSpec(column_index, schema.columns[column_index].name, assignment.value)
            )
        path, index = self._choose_access_path(schema, stmt.where)
        return UpdatePlan(schema, tuple(assignments), stmt.where, path, index)

    def _projection(self, schema: TableSchema, columns: list[str]) -> tuple[list[int], list[str]]:
        if columns == ["*"]:
            return list(range(len(schema.columns))), [c.name for c in schema.columns]
        indexes = [schema.column_index(name) for name in columns]
        names = [schema.columns[i].name for i in indexes]
        return indexes, names

    @staticmethod
    def _validate_predicate(schema: TableSchema, where) -> None:
        if where is None:
            return
        schema.validate_literal(where.column, where.value)

    @staticmethod
    def _choose_access_path(schema: TableSchema, where) -> tuple[AccessPath, IndexSchema | None]:
        # v0.3 indexes support equality lookup only. Range predicates deliberately
        # fall back to a table scan until range-capable index cursors are added.
        if where is None or where.op != CompareOp.EQ:
            return AccessPath.TABLE_SCAN, None

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
            parts = [f"SELECT FROM {plan.schema.name} USING {Planner._path_text(plan)}"]
            if plan.where is not None and plan.access_path == AccessPath.TABLE_SCAN:
                parts.append(f"FILTER {plan.where.column} {plan.where.op.value} {plan.where.value!r}")
            if plan.order_by is not None:
                parts.append(
                    f"SORT {plan.order_by.column_name} {'DESC' if plan.order_by.descending else 'ASC'}"
                )
            if plan.aggregates:
                parts.append("AGGREGATE " + ", ".join(a.output_name for a in plan.aggregates))
            else:
                parts.append("PROJECT " + ", ".join(plan.projection_names))
            if plan.limit is not None:
                parts.append(f"LIMIT {plan.limit}")
            return " | ".join(parts)
        if isinstance(plan, DeletePlan):
            return f"DELETE FROM {plan.schema.name} USING {Planner._path_text(plan)}"
        if isinstance(plan, UpdatePlan):
            assigns = ", ".join(f"{a.column_name}={a.value!r}" for a in plan.assignments)
            return f"UPDATE {plan.schema.name} USING {Planner._path_text(plan)} | SET {assigns}"
        return repr(plan)

    @staticmethod
    def _path_text(plan: SelectPlan | DeletePlan | UpdatePlan) -> str:
        if plan.access_path == AccessPath.SECONDARY_INDEX:
            assert plan.index is not None
            return f"SECONDARY INDEX {plan.index.name} ON {plan.index.column} -> ROWID LOOKUP"
        return plan.access_path.value.upper()
