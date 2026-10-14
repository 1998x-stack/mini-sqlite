from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from mini_sqlite.catalog.schema import Column, IndexSchema, TableSchema
from mini_sqlite.sql.ast import AggregateFunction, CompareOp, Predicate


class AccessPath(str, Enum):
    PRIMARY_KEY = "primary-key lookup"
    SECONDARY_INDEX = "secondary-index lookup"
    SECONDARY_INDEX_RANGE = "secondary-index range scan"
    TABLE_SCAN = "table scan"


@dataclass(frozen=True)
class PlanAlternative:
    name: str
    estimated_cost: float
    estimated_rows: float


@dataclass(frozen=True)
class IndexProbeSpec:
    equality_values: tuple[Any, ...] = ()
    range_column: str | None = None
    lower: Any = None
    lower_inclusive: bool = True
    upper: Any = None
    upper_inclusive: bool = True
    has_lower: bool = False
    has_upper: bool = False
    matched_terms: int = 0

    @property
    def is_range(self) -> bool:
        return self.has_lower or self.has_upper


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
    columns: tuple[str, ...]

    @property
    def column(self) -> str:
        return self.columns[0]


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
    where: Predicate | None
    access_path: AccessPath
    index: IndexSchema | None = None
    index_probe: IndexProbeSpec | None = None
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
    outer_side: int = 0
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
    where: Predicate | None
    access_path: AccessPath
    index: IndexSchema | None = None
    index_probe: IndexProbeSpec | None = None


@dataclass(frozen=True)
class UpdatePlan:
    schema: TableSchema
    assignments: tuple[AssignmentSpec, ...]
    where: Predicate | None
    access_path: AccessPath
    index: IndexSchema | None = None
    index_probe: IndexProbeSpec | None = None


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
