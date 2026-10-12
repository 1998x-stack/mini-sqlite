from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.catalog.schema import Column


@dataclass(frozen=True)
class EqualityPredicate:
    column: str
    value: Any


@dataclass(frozen=True)
class CreateTableStmt:
    name: str
    columns: list[Column]


@dataclass(frozen=True)
class InsertStmt:
    table: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SelectStmt:
    table: str
    columns: list[str]
    where: EqualityPredicate | None = None


@dataclass(frozen=True)
class DeleteStmt:
    table: str
    where: EqualityPredicate | None = None


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
    | InsertStmt
    | SelectStmt
    | DeleteStmt
    | BeginStmt
    | CommitStmt
    | RollbackStmt
)
