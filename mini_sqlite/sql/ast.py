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


@dataclass(frozen=True)
class BetweenPredicate:
    column: str
    lower: Any
    upper: Any


PredicateAtom = ComparisonPredicate | BetweenPredicate


@dataclass(frozen=True)
class AndPredicate:
    terms: tuple[PredicateAtom, ...]


Predicate = PredicateAtom | AndPredicate


def predicate_terms(predicate: Predicate | None) -> tuple[PredicateAtom, ...]:
    if predicate is None:
        return ()
    if isinstance(predicate, AndPredicate):
        return predicate.terms
    return (predicate,)


# Historical name kept as an import-compatible alias for v0.1-v0.3 readers.
EqualityPredicate = ComparisonPredicate


@dataclass(frozen=True)
class AggregateExpr:
    function: AggregateFunction
    column: str | None = None

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
class TableRef:
    name: str
    alias: str | None = None

    @property
    def visible_name(self) -> str:
        return self.alias or self.name


@dataclass(frozen=True)
class JoinClause:
    right: TableRef
    left_column: str
    right_column: str


@dataclass(frozen=True)
class CreateTableStmt:
    name: str
    columns: list[Column]


@dataclass(frozen=True)
class CreateIndexStmt:
    name: str
    table: str
    columns: tuple[str, ...]

    @property
    def column(self) -> str:
        """Compatibility view for historical single-column callers."""
        return self.columns[0]


@dataclass(frozen=True)
class InsertStmt:
    table: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SelectStmt:
    table: str
    items: list[str | AggregateExpr]
    where: Predicate | None = None
    order_by: OrderBy | None = None
    limit: int | None = None
    table_alias: str | None = None
    join: JoinClause | None = None

    @property
    def columns(self) -> list[str]:
        return [item for item in self.items if isinstance(item, str)]

    @property
    def left(self) -> TableRef:
        return TableRef(self.table, self.table_alias)


@dataclass(frozen=True)
class DeleteStmt:
    table: str
    where: Predicate | None = None


@dataclass(frozen=True)
class UpdateStmt:
    table: str
    assignments: tuple[Assignment, ...]
    where: Predicate | None = None


@dataclass(frozen=True)
class AnalyzeStmt:
    table: str | None = None


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
    | AnalyzeStmt
    | BeginStmt
    | CommitStmt
    | RollbackStmt
)
