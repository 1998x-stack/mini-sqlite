from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from mini_sqlite.catalog.schema import Column, IndexSchema, TableSchema
from mini_sqlite.sql.ast import AggregateFunction, CompareOp, ComparisonPredicate


class AccessPath(str, Enum):
    PRIMARY_KEY = "primary-key lookup"
    SECONDARY_INDEX = "secondary-index lookup"
    TABLE_SCAN = "table scan"


@dataclass(frozen=True)
class PlanAlternative:
    name: str
    estimated_cost: float
    estimated_rows: float



@dataclass(frozen=True)
class AggregateSpec:
    function: AggregateFunction
    column_index: int | None
    output_name: str


@dataclass(frozen=True)
class OrderSpec:
    column_index: int
    column_name: str
    descending: bool = False


@dataclass(frozen=True)
class AssignmentSpec:
    column_index: int
    column_name: str
    value: Any


@dataclass(frozen=True)
class JoinedPredicateSpec:
    column_index: int
    column_name: str
    op: CompareOp
    value: Any


@dataclass(frozen=True)
class JoinSpec:
    left_column_index: int
    right_column_index: int
    left_column_name: str
    right_column_name: str


@dataclass(frozen=True)
class CreateTablePlan:
    name: str
    columns: list[Column]


@dataclass(frozen=True)
class CreateIndexPlan:
    name: str
    table: str
    column: str


@dataclass(frozen=True)
class AnalyzePlan:
    table: str | None = None


@dataclass(frozen=True)
class InsertPlan:
    schema: TableSchema
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SelectPlan:
    schema: TableSchema
    projection: list[int]
    projection_names: list[str]
    where: ComparisonPredicate | None
    access_path: AccessPath
    index: IndexSchema | None = None
    order_by: OrderSpec | None = None
    limit: int | None = None
    aggregates: tuple[AggregateSpec, ...] = ()
    estimated_rows: float | None = None
    estimated_cost: float | None = None
    alternatives: tuple[PlanAlternative, ...] = ()

    @property
    def is_aggregate(self) -> bool:
        return bool(self.aggregates)


@dataclass(frozen=True)
class JoinSelectPlan:
    left_schema: TableSchema
    right_schema: TableSchema
    left_name: str
    right_name: str
    join: JoinSpec
    inner_access_path: AccessPath
    projection: list[int]
    projection_names: list[str]
    where: JoinedPredicateSpec | None = None
    inner_index: IndexSchema | None = None
    order_by: OrderSpec | None = None
    limit: int | None = None
    aggregates: tuple[AggregateSpec, ...] = ()
    outer_side: int = 0  # 0 = SQL-left outer, 1 = SQL-right outer
    estimated_rows: float | None = None
    estimated_cost: float | None = None
    alternatives: tuple[PlanAlternative, ...] = ()

    @property
    def is_aggregate(self) -> bool:
        return bool(self.aggregates)

    @property
    def combined_width(self) -> int:
        return len(self.left_schema.columns) + len(self.right_schema.columns)


@dataclass(frozen=True)
class DeletePlan:
    schema: TableSchema
    where: ComparisonPredicate | None
    access_path: AccessPath
    index: IndexSchema | None = None


@dataclass(frozen=True)
class UpdatePlan:
    schema: TableSchema
    assignments: tuple[AssignmentSpec, ...]
    where: ComparisonPredicate | None
    access_path: AccessPath
    index: IndexSchema | None = None


Plan = (
    CreateTablePlan
    | CreateIndexPlan
    | AnalyzePlan
    | InsertPlan
    | SelectPlan
    | JoinSelectPlan
    | DeletePlan
    | UpdatePlan
)
