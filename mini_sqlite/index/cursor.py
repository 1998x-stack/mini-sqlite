from __future__ import annotations

from mini_sqlite.index.secondary import SecondaryIndex


class SecondaryIndexCursor:
    """Materialized rowid cursor for equality/prefix/range index scans."""

    def __init__(self, index: SecondaryIndex):
        self.index = index
        self._rowids: list[int] = []
        self._position = -1

    def _reset(self, rowids: list[int]) -> bool:
        self._rowids = rowids
        self._position = 0
        return bool(self._rowids)

    def seek_equal(self, value: object) -> bool:
        return self._reset(self.index.lookup(value))

    def seek_prefix(self, values: tuple[object, ...]) -> bool:
        return self._reset(self.index.lookup_prefix(values))

    def seek_range(self, probe) -> bool:
        return self._reset(
            self.index.lookup_range(
                equality_values=probe.equality_values,
                lower=probe.lower,
                lower_inclusive=probe.lower_inclusive,
                upper=probe.upper,
                upper_inclusive=probe.upper_inclusive,
                has_lower=probe.has_lower,
                has_upper=probe.has_upper,
            )
        )

    @property
    def current_rowid(self) -> int | None:
        if 0 <= self._position < len(self._rowids):
            return self._rowids[self._position]
        return None

    def next(self) -> bool:
        if self._position < 0:
            return False
        self._position += 1
        return self._position < len(self._rowids)
