from __future__ import annotations

from dataclasses import dataclass

from mini_sqlite.btree.btree import BTree


@dataclass
class CursorRow:
    key: int
    value: bytes


class BTreeCursor:
    """Simple logical cursor used by the VM.

    v0.1 materializes only the key list for scans. The public cursor contract is
    intentionally small so v0.7 can replace this with true page-pin iteration.
    """

    def __init__(self, tree: BTree):
        self.tree = tree
        self._rows: list[CursorRow] = []
        self._index = -1

    def rewind(self) -> bool:
        self._rows = [CursorRow(k, v) for k, v in self.tree.scan()]
        self._index = 0
        return bool(self._rows)

    def seek(self, key: int) -> bool:
        value = self.tree.search(key)
        if value is None:
            self._rows = []
            self._index = -1
            return False
        self._rows = [CursorRow(key, value)]
        self._index = 0
        return True

    @property
    def current(self) -> CursorRow | None:
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]
        return None

    def next(self) -> bool:
        if self._index < 0:
            return False
        self._index += 1
        return self._index < len(self._rows)
