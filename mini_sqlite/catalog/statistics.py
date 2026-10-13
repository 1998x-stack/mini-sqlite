from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnStats:
    """Exact educational column statistics collected by ANALYZE.

    Production systems usually sample and store richer histograms. v0.8 keeps
    the model intentionally small: NULL count, number of distinct non-NULL
    values, and min/max for values that are orderable inside the column type.
    """

    null_count: int = 0
    distinct_count: int = 0
    min_value: Any = None
    max_value: Any = None
    most_common: list[tuple[Any, int]] = field(default_factory=list)

    def encode(self) -> dict[str, Any]:
        return {
            "null_count": self.null_count,
            "distinct_count": self.distinct_count,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "most_common": [[value, count] for value, count in self.most_common],
        }

    @classmethod
    def decode(cls, obj: dict[str, Any]) -> "ColumnStats":
        return cls(
            null_count=int(obj.get("null_count", 0)),
            distinct_count=int(obj.get("distinct_count", 0)),
            min_value=obj.get("min_value"),
            max_value=obj.get("max_value"),
            most_common=[(pair[0], int(pair[1])) for pair in obj.get("most_common", [])],
        )


@dataclass
class TableStats:
    row_count: int = 0
    columns: dict[str, ColumnStats] = field(default_factory=dict)

    def column(self, name: str) -> ColumnStats | None:
        lowered = name.lower()
        for key, value in self.columns.items():
            if key.lower() == lowered:
                return value
        return None

    def encode(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "columns": {name: stats.encode() for name, stats in self.columns.items()},
        }

    @classmethod
    def decode(cls, obj: dict[str, Any] | None) -> "TableStats | None":
        if not obj:
            return None
        return cls(
            row_count=int(obj.get("row_count", 0)),
            columns={
                str(name): ColumnStats.decode(value)
                for name, value in obj.get("columns", {}).items()
            },
        )
