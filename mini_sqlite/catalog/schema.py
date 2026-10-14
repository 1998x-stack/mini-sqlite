from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from mini_sqlite.catalog.statistics import TableStats
from mini_sqlite.errors import SchemaError


class ColumnType(str, Enum):
    INTEGER = "INTEGER"
    TEXT = "TEXT"


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType
    primary_key: bool = False


@dataclass
class IndexSchema:
    name: str
    columns: tuple[str, ...]
    root_page: int
    unique: bool = False

    @property
    def column(self) -> str:
        """Historical single-column compatibility view (the leftmost key)."""
        return self.columns[0]


@dataclass
class TableSchema:
    table_id: int
    name: str
    root_page: int
    columns: list[Column] = field(default_factory=list)
    indexes: list[IndexSchema] = field(default_factory=list)
    stats: TableStats | None = None

    @property
    def primary_key_index(self) -> int:
        for i, column in enumerate(self.columns):
            if column.primary_key:
                return i
        raise SchemaError(f"table {self.name} has no primary key")

    @property
    def primary_key(self) -> Column:
        return self.columns[self.primary_key_index]

    def column_index(self, name: str) -> int:
        for i, column in enumerate(self.columns):
            if column.name.lower() == name.lower():
                return i
        raise SchemaError(f"unknown column {name!r} on table {self.name}")

    def column(self, name: str) -> Column:
        return self.columns[self.column_index(name)]

    def index_on_column(self, column: str) -> IndexSchema | None:
        """Return an index whose leftmost key is *column*.

        Existing JOIN code relies on this leftmost-prefix rule. v1.3 may keep
        multiple indexes with the same first column; the first catalog order is
        deterministic and the cost planner can inspect richer candidates later.
        """
        lowered = column.lower()
        for index in self.indexes:
            if index.columns and index.columns[0].lower() == lowered:
                return index
        return None

    def indexes_starting_with(self, column: str) -> list[IndexSchema]:
        lowered = column.lower()
        return [
            index
            for index in self.indexes
            if index.columns and index.columns[0].lower() == lowered
        ]

    def index_on_columns(self, columns: tuple[str, ...] | list[str]) -> IndexSchema | None:
        wanted = tuple(name.lower() for name in columns)
        for index in self.indexes:
            if tuple(name.lower() for name in index.columns) == wanted:
                return index
        return None

    def get_index(self, name: str) -> IndexSchema:
        lowered = name.lower()
        for index in self.indexes:
            if index.name.lower() == lowered:
                return index
        raise SchemaError(f"no such index {name!r} on table {self.name}")

    def validate_literal(self, column_name: str, value: object) -> None:
        column = self.column(column_name)
        if value is None:
            return
        if column.type == ColumnType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise SchemaError(f"column {column.name} expects INTEGER")
            return
        if column.type == ColumnType.TEXT:
            if not isinstance(value, str):
                raise SchemaError(f"column {column.name} expects TEXT")
            return
        raise SchemaError(f"unsupported column type: {column.type}")

    def validate_row(self, values: tuple[object, ...] | list[object]) -> None:
        if len(values) != len(self.columns):
            raise SchemaError(
                f"table {self.name} expects {len(self.columns)} values, got {len(values)}"
            )
        for column, value in zip(self.columns, values):
            if value is None:
                if column.primary_key:
                    raise SchemaError("primary key cannot be NULL")
                continue
            if column.type == ColumnType.INTEGER and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise SchemaError(f"column {column.name} expects INTEGER")
            if column.type == ColumnType.TEXT and not isinstance(value, str):
                raise SchemaError(f"column {column.name} expects TEXT")
        pk = values[self.primary_key_index]
        if not isinstance(pk, int) or isinstance(pk, bool):
            raise SchemaError("mini-sqlite requires an INTEGER PRIMARY KEY")

    def encode(self) -> bytes:
        obj = {
            "table_id": self.table_id,
            "name": self.name,
            "root_page": self.root_page,
            "columns": [
                {"name": c.name, "type": c.type.value, "primary_key": c.primary_key}
                for c in self.columns
            ],
            "indexes": [
                {
                    "name": index.name,
                    # `column` is retained as a readable historical hint; v1.3
                    # engines use `columns` and format-version 3 prevents old
                    # writers from silently treating a composite index as scalar.
                    "column": index.column,
                    "columns": list(index.columns),
                    "root_page": index.root_page,
                    "unique": index.unique,
                }
                for index in self.indexes
            ],
            "stats": self.stats.encode() if self.stats is not None else None,
        }
        return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def decode(cls, raw: bytes) -> "TableSchema":
        obj = json.loads(raw.decode("utf-8"))
        indexes: list[IndexSchema] = []
        for item in obj.get("indexes", []):
            raw_columns = item.get("columns")
            if raw_columns is None:
                raw_columns = [item["column"]]
            indexes.append(
                IndexSchema(
                    name=str(item["name"]),
                    columns=tuple(str(value) for value in raw_columns),
                    root_page=int(item["root_page"]),
                    unique=bool(item.get("unique", False)),
                )
            )
        return cls(
            table_id=int(obj["table_id"]),
            name=str(obj["name"]),
            root_page=int(obj["root_page"]),
            columns=[
                Column(
                    name=str(c["name"]),
                    type=ColumnType(c["type"]),
                    primary_key=bool(c["primary_key"]),
                )
                for c in obj["columns"]
            ],
            indexes=indexes,
            stats=TableStats.decode(obj.get("stats")),
        )
