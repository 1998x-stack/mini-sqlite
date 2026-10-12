from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from mini_sqlite.catalog.schema import Column, IndexSchema, TableSchema
from mini_sqlite.sql.ast import EqualityPredicate


class AccessPath(str, Enum):
    PRIMARY_KEY = "primary-key lookup"
    SECONDARY_INDEX = "secondary-index lookup"
    TABLE_SCAN = "table scan"


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
class InsertPlan:
    schema: TableSchema
    values: tuple[Any, ...]


@dataclass(frozen=True)
class SelectPlan:
    schema: TableSchema
    projection: list[int]
    projection_names: list[str]
    where: EqualityPredicate | None
    access_path: AccessPath
    index: IndexSchema | None = None


@dataclass(frozen=True)
class DeletePlan:
    schema: TableSchema
    where: EqualityPredicate | None
    access_path: AccessPath
    index: IndexSchema | None = None


Plan = CreateTablePlan | CreateIndexPlan | InsertPlan | SelectPlan | DeletePlan
