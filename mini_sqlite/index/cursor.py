from __future__ import annotations

from mini_sqlite.index.secondary import SecondaryIndex


class SecondaryIndexCursor:
    """Equality-lookup cursor over a snapshot of matching rowids.

    The index tree performs logarithmic navigation to the first matching key;
    materializing only the duplicate rowid run keeps v0.3 execution simple while
    making later page-pin cursors a clean replacement in v0.7.
    """

    def __init__(self, index: SecondaryIndex):
        self.index = index
        self._rowids: list[int] = []
        self._position = -1

    def seek_equal(self, value: object) -> bool:
        self._rowids = self.index.lookup(value)
        self._position = 0
        return bool(self._rowids)

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
