from __future__ import annotations

from dataclasses import dataclass

from mini_sqlite.catalog import Catalog, ColumnType, IndexSchema, TableSchema
from mini_sqlite.errors import SchemaError
from mini_sqlite.planner.indexing import choose_rule_access, render_predicate
from mini_sqlite.planner.plan import (
    AccessPath,
    AggregateSpec,
    AssignmentSpec,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    JoinedPredicateSpec,
    JoinSelectPlan,
    JoinSpec,
    OrderSpec,
    Plan,
    SelectPlan,
    UpdatePlan,
)
from mini_sqlite.sql.ast import (
    AggregateExpr,
    AggregateFunction,
    AndPredicate,
    BetweenPredicate,
    CompareOp,
    ComparisonPredicate,
    predicate_terms,
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    SelectStmt,
    Statement,
    UpdateStmt,
)


@dataclass(frozen=True)
class _ResolvedColumn:
    side: int  # 0 = left, 1 = right
    local_index: int
    flat_index: int
    schema: TableSchema
    visible_table: str
    column_name: str

    @property
    def display_name(self) -> str:
        return f"{self.visible_table}.{self.column_name}"


class Planner:
    """Rule-based planner with explicit access paths and relational stages.

    v0.5 adds a second row source and an explicit join algorithm decision while
    preserving v0.4's post-source relational pipeline:

        outer source -> inner access -> JOIN -> filter -> sort -> project/agg -> limit

    The written left table remains the outer source. The ON column on the right
    chooses PRIMARY KEY seek, SECONDARY INDEX seek, or a full inner scan.
    """

    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    def plan(self, stmt: Statement) -> Plan:
        if isinstance(stmt, CreateTableStmt):
            return CreateTablePlan(stmt.name, stmt.columns)
        if isinstance(stmt, CreateIndexStmt):
            table = self.catalog.get_table(stmt.table)
            canonical = tuple(table.column(name).name for name in stmt.columns)
            if len({name.lower() for name in canonical}) != len(canonical):
                raise SchemaError("index column list contains duplicates")
            return CreateIndexPlan(stmt.name, table.name, canonical)
        if isinstance(stmt, InsertStmt):
            schema = self.catalog.get_table(stmt.table)
            schema.validate_row(stmt.values)
            return InsertPlan(schema, stmt.values)
        if isinstance(stmt, SelectStmt):
            return self._select(stmt)
        if isinstance(stmt, DeleteStmt):
            schema = self.catalog.get_table(stmt.table)
            where = self._normalize_single_predicate(schema, schema.name, stmt.where)
            path, index, probe = self._choose_access_path(schema, where)
            return DeletePlan(schema, where, path, index, probe)
        if isinstance(stmt, UpdateStmt):
            return self._update(stmt)
        raise SchemaError(f"unsupported statement type: {type(stmt).__name__}")

    def _select(self, stmt: SelectStmt) -> SelectPlan | JoinSelectPlan:
        if stmt.join is not None:
            return self._join_select(stmt)
        return self._single_select(stmt)

    def _single_select(self, stmt: SelectStmt) -> SelectPlan:
        schema = self.catalog.get_table(stmt.table)
        visible_name = stmt.table_alias or schema.name

        where = self._normalize_single_predicate(schema, visible_name, stmt.where)
        path, index, probe = self._choose_access_path(schema, where)

        aggregate_items = [item for item in stmt.items if isinstance(item, AggregateExpr)]
        column_items = [item for item in stmt.items if isinstance(item, str)]
        if aggregate_items and column_items:
            raise SchemaError("v0.5 does not mix aggregate and non-aggregate SELECT items")

        aggregates: tuple[AggregateSpec, ...] = ()
        if aggregate_items:
            specs: list[AggregateSpec] = []
            for expr in aggregate_items:
                if expr.column is None:
                    if expr.function != AggregateFunction.COUNT:
                        raise SchemaError(f"{expr.function.value}(*) is not supported")
                    column_index = None
                else:
                    bare = self._resolve_single_name(schema, visible_name, expr.column)
                    column_index = schema.column_index(bare)
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
            if column_items == ["*"]:
                projection = list(range(len(schema.columns)))
                names = [c.name for c in schema.columns]
            else:
                bare_columns = [
                    self._resolve_single_name(schema, visible_name, name) for name in column_items
                ]
                projection, names = self._projection(schema, bare_columns)

        order_by = None
        if stmt.order_by is not None:
            bare = self._resolve_single_name(schema, visible_name, stmt.order_by.column)
            order_by = OrderSpec(schema.column_index(bare), bare, stmt.order_by.descending)

        return SelectPlan(
            schema=schema,
            projection=projection,
            projection_names=names,
            where=where,
            access_path=path,
            index=index,
            index_probe=probe,
            order_by=order_by,
            limit=stmt.limit,
            aggregates=aggregates,
        )

    def _join_select(self, stmt: SelectStmt) -> JoinSelectPlan:
        assert stmt.join is not None
        left_schema = self.catalog.get_table(stmt.table)
        right_schema = self.catalog.get_table(stmt.join.right.name)
        left_name = stmt.table_alias or left_schema.name
        right_name = stmt.join.right.alias or right_schema.name
        if left_name.lower() == right_name.lower():
            raise SchemaError("JOIN sources need distinct visible names; use aliases")

        on_a = self._resolve_join_column(
            stmt.join.left_column, left_schema, right_schema, left_name, right_name
        )
        on_b = self._resolve_join_column(
            stmt.join.right_column, left_schema, right_schema, left_name, right_name
        )
        if on_a.side == on_b.side:
            raise SchemaError("JOIN ON must compare a column from each source")
        left_col, right_col = (on_a, on_b) if on_a.side == 0 else (on_b, on_a)
        if left_schema.columns[left_col.local_index].type != right_schema.columns[right_col.local_index].type:
            raise SchemaError("JOIN columns must have compatible types")

        join = JoinSpec(
            left_column_index=left_col.local_index,
            right_column_index=right_col.local_index,
            left_column_name=left_col.display_name,
            right_column_name=right_col.display_name,
        )
        inner_path, inner_index = self._choose_join_inner_path(right_schema, right_col.local_index)

        where = None
        if stmt.where is not None:
            if not isinstance(stmt.where, ComparisonPredicate):
                raise SchemaError(
                    "v1.3 composite/range WHERE is currently supported for single-table queries"
                )
            resolved = self._resolve_join_column(
                stmt.where.column, left_schema, right_schema, left_name, right_name
            )
            resolved.schema.validate_literal(resolved.column_name, stmt.where.value)
            where = JoinedPredicateSpec(
                resolved.flat_index,
                resolved.display_name,
                stmt.where.op,
                stmt.where.value,
            )

        aggregate_items = [item for item in stmt.items if isinstance(item, AggregateExpr)]
        column_items = [item for item in stmt.items if isinstance(item, str)]
        if aggregate_items and column_items:
            raise SchemaError("v0.5 does not mix aggregate and non-aggregate SELECT items")

        aggregates: tuple[AggregateSpec, ...] = ()
        if aggregate_items:
            specs: list[AggregateSpec] = []
            for expr in aggregate_items:
                if expr.column is None:
                    if expr.function != AggregateFunction.COUNT:
                        raise SchemaError(f"{expr.function.value}(*) is not supported")
                    flat_index = None
                else:
                    resolved = self._resolve_join_column(
                        expr.column, left_schema, right_schema, left_name, right_name
                    )
                    if (
                        expr.function == AggregateFunction.SUM
                        and resolved.schema.columns[resolved.local_index].type != ColumnType.INTEGER
                    ):
                        raise SchemaError("SUM requires an INTEGER column")
                    flat_index = resolved.flat_index
                specs.append(AggregateSpec(expr.function, flat_index, expr.display_name))
            aggregates = tuple(specs)
            projection: list[int] = []
            names = [spec.output_name for spec in specs]
            if stmt.order_by is not None:
                raise SchemaError("ORDER BY with aggregate queries is deferred until GROUP BY support")
        elif column_items == ["*"]:
            projection = list(range(len(left_schema.columns) + len(right_schema.columns)))
            names = [f"{left_name}.{c.name}" for c in left_schema.columns] + [
                f"{right_name}.{c.name}" for c in right_schema.columns
            ]
        else:
            resolved_items = [
                self._resolve_join_column(item, left_schema, right_schema, left_name, right_name)
                for item in column_items
            ]
            projection = [col.flat_index for col in resolved_items]
            names = [col.display_name for col in resolved_items]

        order_by = None
        if stmt.order_by is not None:
            resolved = self._resolve_join_column(
                stmt.order_by.column, left_schema, right_schema, left_name, right_name
            )
            order_by = OrderSpec(
                resolved.flat_index, resolved.display_name, stmt.order_by.descending
            )

        return JoinSelectPlan(
            left_schema=left_schema,
            right_schema=right_schema,
            left_name=left_name,
            right_name=right_name,
            join=join,
            inner_access_path=inner_path,
            inner_index=inner_index,
            projection=projection,
            projection_names=names,
            where=where,
            order_by=order_by,
            limit=stmt.limit,
            aggregates=aggregates,
        )

    def _update(self, stmt: UpdateStmt) -> UpdatePlan:
        schema = self.catalog.get_table(stmt.table)
        where = self._normalize_single_predicate(schema, schema.name, stmt.where)
        seen: set[int] = set()
        assignments: list[AssignmentSpec] = []
        for assignment in stmt.assignments:
            column_index = schema.column_index(assignment.column)
            if column_index in seen:
                raise SchemaError(f"column {assignment.column!r} assigned more than once")
            seen.add(column_index)
            if column_index == schema.primary_key_index:
                raise SchemaError("v0.5 UPDATE cannot change the INTEGER PRIMARY KEY")
            schema.validate_literal(assignment.column, assignment.value)
            assignments.append(
                AssignmentSpec(column_index, schema.columns[column_index].name, assignment.value)
            )
        path, index, probe = self._choose_access_path(schema, where)
        return UpdatePlan(schema, tuple(assignments), where, path, index, probe)

    @staticmethod
    def _projection(schema: TableSchema, columns: list[str]) -> tuple[list[int], list[str]]:
        indexes = [schema.column_index(name) for name in columns]
        names = [schema.columns[i].name for i in indexes]
        return indexes, names

    def _normalize_single_predicate(self, schema: TableSchema, visible_name: str, where):
        if where is None:
            return None
        normalized = []
        for term in predicate_terms(where):
            bare = self._resolve_single_name(schema, visible_name, term.column)
            if isinstance(term, BetweenPredicate):
                schema.validate_literal(bare, term.lower)
                schema.validate_literal(bare, term.upper)
                if term.lower is not None and term.upper is not None and term.lower > term.upper:
                    raise SchemaError("BETWEEN lower bound must not exceed upper bound")
                normalized.append(BetweenPredicate(bare, term.lower, term.upper))
            else:
                schema.validate_literal(bare, term.value)
                normalized.append(ComparisonPredicate(bare, term.op, term.value))
        if len(normalized) == 1:
            return normalized[0]
        return AndPredicate(tuple(normalized))

    @staticmethod
    def _resolve_single_name(schema: TableSchema, visible_name: str, ref: str) -> str:
        if "." not in ref:
            schema.column(ref)
            return ref
        qualifier, column = ref.split(".", 1)
        if qualifier.lower() not in {visible_name.lower(), schema.name.lower()}:
            raise SchemaError(f"unknown table or alias {qualifier!r}")
        schema.column(column)
        return column

    @staticmethod
    def _resolve_join_column(
        ref: str,
        left: TableSchema,
        right: TableSchema,
        left_name: str,
        right_name: str,
    ) -> _ResolvedColumn:
        if "." in ref:
            qualifier, name = ref.split(".", 1)
            q = qualifier.lower()
            if q == left_name.lower():
                local = left.column_index(name)
                return _ResolvedColumn(0, local, local, left, left_name, left.columns[local].name)
            if q == right_name.lower():
                local = right.column_index(name)
                return _ResolvedColumn(
                    1,
                    local,
                    len(left.columns) + local,
                    right,
                    right_name,
                    right.columns[local].name,
                )
            raise SchemaError(f"unknown table or alias {qualifier!r}")

        matches: list[_ResolvedColumn] = []
        for side, schema, visible, offset in (
            (0, left, left_name, 0),
            (1, right, right_name, len(left.columns)),
        ):
            try:
                local = schema.column_index(ref)
            except SchemaError:
                continue
            matches.append(
                _ResolvedColumn(
                    side,
                    local,
                    offset + local,
                    schema,
                    visible,
                    schema.columns[local].name,
                )
            )
        if not matches:
            raise SchemaError(f"unknown column {ref!r} in JOIN")
        if len(matches) > 1:
            raise SchemaError(f"ambiguous column {ref!r}; qualify it with a table alias")
        return matches[0]

    @staticmethod
    def _choose_access_path(schema: TableSchema, where):
        return choose_rule_access(schema, where)

    @staticmethod
    def _choose_join_inner_path(
        schema: TableSchema, column_index: int
    ) -> tuple[AccessPath, IndexSchema | None]:
        if column_index == schema.primary_key_index:
            return AccessPath.PRIMARY_KEY, None
        column_name = schema.columns[column_index].name
        index = schema.index_on_column(column_name)
        if index is not None:
            return AccessPath.SECONDARY_INDEX, index
        return AccessPath.TABLE_SCAN, None

    @staticmethod
    def explain(plan: Plan) -> str:
        if isinstance(plan, CreateTablePlan):
            return f"CREATE TABLE {plan.name}"
        if isinstance(plan, CreateIndexPlan):
            return f"CREATE INDEX {plan.name} ON {plan.table}({', '.join(plan.columns)}) USING B+TREE"
        if isinstance(plan, InsertPlan):
            suffix = f" + {len(plan.schema.indexes)} SECONDARY INDEX(ES)" if plan.schema.indexes else ""
            return f"INSERT INTO {plan.schema.name} USING B+TREE PRIMARY KEY{suffix}"
        if isinstance(plan, JoinSelectPlan):
            if plan.inner_access_path == AccessPath.PRIMARY_KEY:
                join_text = f"INDEXED NESTED LOOP | INNER PRIMARY KEY {plan.join.right_column_name}"
            elif plan.inner_access_path == AccessPath.SECONDARY_INDEX:
                assert plan.inner_index is not None
                join_text = (
                    "INDEXED NESTED LOOP | INNER SECONDARY INDEX "
                    f"{plan.inner_index.name} ON {plan.join.right_column_name}"
                )
            else:
                join_text = "NESTED LOOP | INNER TABLE SCAN"
            parts = [
                f"SELECT FROM {plan.left_schema.name} AS {plan.left_name}",
                f"INNER JOIN {plan.right_schema.name} AS {plan.right_name}",
                f"ON {plan.join.left_column_name} = {plan.join.right_column_name}",
                join_text,
            ]
            if plan.where is not None:
                parts.append(
                    f"FILTER {plan.where.column_name} {plan.where.op.value} {plan.where.value!r}"
                )
            if plan.order_by is not None:
                parts.append(
                    f"SORT {plan.order_by.column_name} "
                    f"{'DESC' if plan.order_by.descending else 'ASC'}"
                )
            if plan.aggregates:
                parts.append("AGGREGATE " + ", ".join(a.output_name for a in plan.aggregates))
            else:
                parts.append("PROJECT " + ", ".join(plan.projection_names))
            if plan.limit is not None:
                parts.append(f"LIMIT {plan.limit}")
            return " | ".join(parts)
        if isinstance(plan, SelectPlan):
            parts = [f"SELECT FROM {plan.schema.name} USING {Planner._path_text(plan)}"]
            if plan.where is not None:
                parts.append(f"FILTER {render_predicate(plan.where)}")
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
        if plan.access_path in (AccessPath.SECONDARY_INDEX, AccessPath.SECONDARY_INDEX_RANGE):
            assert plan.index is not None
            columns = ",".join(plan.index.columns)
            if plan.access_path == AccessPath.SECONDARY_INDEX_RANGE:
                return f"SECONDARY INDEX RANGE {plan.index.name} ON ({columns}) -> ROWID LOOKUP"
            return f"SECONDARY INDEX {plan.index.name} ON ({columns}) -> ROWID LOOKUP"
        return plan.access_path.value.upper()
