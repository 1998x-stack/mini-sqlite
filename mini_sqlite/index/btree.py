from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Iterator

from mini_sqlite.errors import DuplicateKeyError, StorageError
from mini_sqlite.index.node import (
    IndexInternalCell,
    IndexLeafCell,
    IndexNode,
    IndexNodeType,
)
from mini_sqlite.storage.pager import Pager

RootChangeCallback = Callable[[int], None]


class ByteKeyBTree:
    """Persistent B+Tree whose keys are arbitrary byte strings.

    v0.3 uses this tree only for secondary indexes. The original integer-key
    table B+Tree stays untouched, making the new access path visible instead of
    hiding it behind a large storage refactor.
    """

    def __init__(
        self,
        pager: Pager,
        root_page: int,
        *,
        on_root_change: RootChangeCallback | None = None,
    ):
        self.pager = pager
        self.root_page = root_page
        self._on_root_change = on_root_change

    @classmethod
    def create(
        cls, pager: Pager, *, on_root_change: RootChangeCallback | None = None
    ) -> "ByteKeyBTree":
        page_id = pager.allocate_page()
        root = IndexNode(page_id=page_id, node_type=IndexNodeType.LEAF)
        pager.write_page(page_id, root.encode(pager.page_size))
        return cls(pager, page_id, on_root_change=on_root_change)

    def _load(self, page_id: int) -> IndexNode:
        return IndexNode.decode(page_id, self.pager.get_page(page_id))

    def _store(self, node: IndexNode) -> None:
        self.pager.write_page(node.page_id, node.encode(self.pager.page_size))

    def _allocate_node(self, node_type: IndexNodeType, parent: int = 0) -> IndexNode:
        page_id = self.pager.allocate_page()
        return IndexNode(page_id=page_id, node_type=node_type, parent=parent)

    def _set_root(self, page_id: int) -> None:
        self.root_page = page_id
        if self._on_root_change is not None:
            self._on_root_change(page_id)

    def search(self, key: bytes) -> bytes | None:
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos < len(keys) and keys[pos] == key:
            return leaf.leaf_cells[pos].value
        return None

    def insert(self, key: bytes, value: bytes) -> None:
        if not isinstance(key, bytes):
            raise TypeError("ByteKeyBTree keys must be bytes")
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos < len(keys) and keys[pos] == key:
            raise DuplicateKeyError(f"duplicate secondary-index physical key {key.hex()}")
        leaf.leaf_cells.insert(pos, IndexLeafCell(key, value))
        if leaf.fits(self.pager.page_size):
            self._store(leaf)
            return
        self._split_leaf(leaf)

    def delete(self, key: bytes) -> bool:
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos >= len(keys) or keys[pos] != key:
            return False
        del leaf.leaf_cells[pos]
        self._store(leaf)
        return True

    def scan(self) -> Iterator[tuple[bytes, bytes]]:
        node = self._load(self.root_page)
        while not node.is_leaf:
            node = self._load(node.first_child)
        while True:
            for cell in node.leaf_cells:
                yield cell.key, cell.value
            if node.right_sibling == 0:
                break
            node = self._load(node.right_sibling)

    def scan_prefix(self, prefix: bytes) -> Iterator[tuple[bytes, bytes]]:
        """Yield only entries whose ordered key begins with *prefix*.

        The search descends directly to the first leaf that could contain the
        prefix, then walks right siblings only while matching keys remain.
        """
        node = self._find_leaf(prefix)
        first = True
        while True:
            keys = [c.key for c in node.leaf_cells]
            start = bisect_left(keys, prefix) if first else 0
            first = False
            for cell in node.leaf_cells[start:]:
                if cell.key.startswith(prefix):
                    yield cell.key, cell.value
                    continue
                if cell.key > prefix:
                    return
            if node.right_sibling == 0:
                return
            node = self._load(node.right_sibling)

    def _find_leaf(self, key: bytes) -> IndexNode:
        node = self._load(self.root_page)
        while not node.is_leaf:
            node = self._load(node.child_for_key(key))
        return node

    def _split_leaf(self, leaf: IndexNode) -> None:
        if len(leaf.leaf_cells) < 2:
            raise StorageError("single secondary-index cell is larger than a page")
        split = self._choose_leaf_split(leaf.leaf_cells)
        right = self._allocate_node(IndexNodeType.LEAF, parent=leaf.parent)
        right.leaf_cells = leaf.leaf_cells[split:]
        right.right_sibling = leaf.right_sibling
        leaf.leaf_cells = leaf.leaf_cells[:split]
        leaf.right_sibling = right.page_id
        self._store(leaf)
        self._store(right)
        self._insert_into_parent(leaf, right.leaf_cells[0].key, right)

    @staticmethod
    def _choose_leaf_split(cells: list[IndexLeafCell]) -> int:
        weights = [2 + 2 + 4 + len(c.key) + len(c.value) for c in cells]
        total = sum(weights)
        running = 0
        best = 1
        best_delta = total
        for i in range(1, len(cells)):
            running += weights[i - 1]
            delta = abs(total - 2 * running)
            if delta < best_delta:
                best, best_delta = i, delta
        return best

    def _insert_into_parent(self, left: IndexNode, key: bytes, right: IndexNode) -> None:
        if left.parent == 0:
            root = self._allocate_node(IndexNodeType.INTERNAL)
            root.first_child = left.page_id
            root.internal_cells = [IndexInternalCell(key, right.page_id)]
            left.parent = root.page_id
            right.parent = root.page_id
            self._store(left)
            self._store(right)
            self._store(root)
            self._set_root(root.page_id)
            return

        parent = self._load(left.parent)
        children = parent.children()
        try:
            left_index = children.index(left.page_id)
        except ValueError as exc:
            raise StorageError("index parent does not reference child during split") from exc
        parent.internal_cells.insert(left_index, IndexInternalCell(key, right.page_id))
        right.parent = parent.page_id
        self._store(right)
        if parent.fits(self.pager.page_size):
            self._store(parent)
            return
        self._split_internal(parent)

    def _split_internal(self, node: IndexNode) -> None:
        cells = node.internal_cells
        if len(cells) < 3:
            raise StorageError("secondary-index internal node cannot be split safely")
        mid = len(cells) // 2
        promote = cells[mid]

        right = self._allocate_node(IndexNodeType.INTERNAL, parent=node.parent)
        right.first_child = promote.right_child
        right.internal_cells = cells[mid + 1 :]
        node.internal_cells = cells[:mid]

        for child_id in right.children():
            child = self._load(child_id)
            child.parent = right.page_id
            self._store(child)

        self._store(node)
        self._store(right)
        self._insert_into_parent(node, promote.key, right)

    def dump(self) -> str:
        lines: list[str] = []

        def brief(key: bytes) -> str:
            text = key.hex()
            return text if len(text) <= 36 else text[:36] + "…"

        def visit(page_id: int, prefix: str) -> None:
            node = self._load(page_id)
            if node.is_leaf:
                keys = ", ".join(brief(c.key) for c in node.leaf_cells)
                lines.append(
                    f"{prefix}page {page_id} INDEX_LEAF parent={node.parent} "
                    f"right={node.right_sibling} keys=[{keys}]"
                )
                return
            seps = ", ".join(brief(c.key) for c in node.internal_cells)
            lines.append(
                f"{prefix}page {page_id} INDEX_INTERNAL parent={node.parent} "
                f"separators=[{seps}]"
            )
            for child in node.children():
                visit(child, prefix + "  ")

        visit(self.root_page, "")
        return "\n".join(lines)
