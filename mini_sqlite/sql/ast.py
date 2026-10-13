from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from mini_sqlite.catalog.schema import Column


class CompareOp(str, Enum):
    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


class AggregateFunction(str, Enum):
    COUNT = "COUNT"
    SUM = "SUM"
    MIN = "MIN"
    MAX = "MAX"


@dataclass(frozen=True)
class ComparisonPredicate:
    column: str
    op: CompareOp
    value: Any


# Historical name kept as an import-compatible alias for v0.1-v0.3 readers.
EqualityPredicate = ComparisonPredicate


@dataclass(frozen=True)
class AggregateExpr:
    function: AggregateFunction
    column: str | None = None  # None means COUNT(*)

    @property
    def display_name(self) -> str:
        arg = "*" if self.column is None else self.column
        return f"{self.function.value}({arg})"


@dataclass(frozen=True)
class OrderBy:
    column: str
    descending: bool = False


@dataclass(frozen=True)
class Assignment:
    column: str
    value: Any


@dataclass(frozen=True)
class CreateTableStmt:
    name: str
    columns: list[Column]


@dataclass(frozen=True)
class CreateIndexStmt:
    name: str
    table: str
    column: str


@dataclass(frozen=True)
class InsertStmt:
    table: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SelectStmt:
    table: str
    items: list[str | AggregateExpr]
    where: ComparisonPredicate | None = None
    order_by: OrderBy | None = None
    limit: int | None = None

    @property
    def columns(self) -> list[str]:
        """Compatibility view used by older teaching/tests for column-only SELECTs."""
        return [item for item in self.items if isinstance(item, str)]


@dataclass(frozen=True)
class DeleteStmt:
    table: str
    where: ComparisonPredicate | None = None


@dataclass(frozen=True)
class UpdateStmt:
    table: str
    assignments: tuple[Assignment, ...]
    where: ComparisonPredicate | None = None


@dataclass(frozen=True)
class BeginStmt:
    pass


@dataclass(frozen=True)
class CommitStmt:
    pass


@dataclass(frozen=True)
class RollbackStmt:
    pass


Statement = (
    CreateTableStmt
    | CreateIndexStmt
    | InsertStmt
    | SelectStmt
    | DeleteStmt
    | UpdateStmt
    | BeginStmt
    | CommitStmt
    | RollbackStmt
)
