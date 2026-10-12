from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Iterator

from mini_sqlite.btree.node import BTreeNode, InternalCell, LeafCell, NodeType
from mini_sqlite.errors import DuplicateKeyError, NotFoundError, StorageError
from mini_sqlite.storage.pager import Pager

RootChangeCallback = Callable[[int], None]


class BTree:
    """Persistent integer-key B+Tree backed by Pager pages.

    v0.1 supports search, insert, scan, and delete. Deletes compact a leaf but do
    not merge under-full pages; merge/rebalance is intentionally reserved for a
    later version so the split/search invariants stay easy to study.
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
    ) -> "BTree":
        page_id = pager.allocate_page()
        root = BTreeNode(page_id=page_id, node_type=NodeType.LEAF)
        pager.write_page(page_id, root.encode(pager.page_size))
        return cls(pager, page_id, on_root_change=on_root_change)

    def _load(self, page_id: int) -> BTreeNode:
        return BTreeNode.decode(page_id, self.pager.get_page(page_id))

    def _store(self, node: BTreeNode) -> None:
        self.pager.write_page(node.page_id, node.encode(self.pager.page_size))

    def _allocate_node(self, node_type: NodeType, parent: int = 0) -> BTreeNode:
        page_id = self.pager.allocate_page()
        return BTreeNode(page_id=page_id, node_type=node_type, parent=parent)

    def _set_root(self, page_id: int) -> None:
        self.root_page = page_id
        if self._on_root_change is not None:
            self._on_root_change(page_id)

    def search(self, key: int) -> bytes | None:
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos < len(keys) and keys[pos] == key:
            return leaf.leaf_cells[pos].value
        return None

    def insert(self, key: int, value: bytes) -> None:
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos < len(keys) and keys[pos] == key:
            raise DuplicateKeyError(f"duplicate primary key {key}")
        leaf.leaf_cells.insert(pos, LeafCell(key, value))
        if leaf.fits(self.pager.page_size):
            self._store(leaf)
            return
        self._split_leaf(leaf)

    def delete(self, key: int) -> bool:
        leaf = self._find_leaf(key)
        keys = [c.key for c in leaf.leaf_cells]
        pos = bisect_left(keys, key)
        if pos >= len(keys) or keys[pos] != key:
            return False
        del leaf.leaf_cells[pos]
        self._store(leaf)
        return True

    def scan(self) -> Iterator[tuple[int, bytes]]:
        node = self._load(self.root_page)
        while not node.is_leaf:
            node = self._load(node.first_child)
        while True:
            for cell in node.leaf_cells:
                yield cell.key, cell.value
            if node.right_sibling == 0:
                break
            node = self._load(node.right_sibling)

    def _find_leaf(self, key: int) -> BTreeNode:
        node = self._load(self.root_page)
        while not node.is_leaf:
            node = self._load(node.child_for_key(key))
        return node

    def _split_leaf(self, leaf: BTreeNode) -> None:
        if len(leaf.leaf_cells) < 2:
            raise StorageError("single B+Tree cell is larger than a page")
        split = self._choose_leaf_split(leaf.leaf_cells)
        left_cells = leaf.leaf_cells[:split]
        right_cells = leaf.leaf_cells[split:]
        right = self._allocate_node(NodeType.LEAF, parent=leaf.parent)
        right.leaf_cells = right_cells
        right.right_sibling = leaf.right_sibling
        leaf.leaf_cells = left_cells
        leaf.right_sibling = right.page_id
        self._store(leaf)
        self._store(right)
        separator = right.leaf_cells[0].key
        self._insert_into_parent(leaf, separator, right)

    def _choose_leaf_split(self, cells: list[LeafCell]) -> int:
        # Choose a balanced split by byte footprint, not by row count.
        total = sum(12 + len(c.value) + 2 for c in cells)
        running = 0
        best = 1
        best_delta = total
        for i in range(1, len(cells)):
            running += 12 + len(cells[i - 1].value) + 2
            delta = abs(total - 2 * running)
            if delta < best_delta:
                best, best_delta = i, delta
        return best

    def _insert_into_parent(self, left: BTreeNode, key: int, right: BTreeNode) -> None:
        if left.parent == 0:
            root = self._allocate_node(NodeType.INTERNAL)
            root.first_child = left.page_id
            root.internal_cells = [InternalCell(key, right.page_id)]
            left.parent = root.page_id
            right.parent = root.page_id
            self._store(left)
            self._store(right)
            self._store(root)
            self._set_root(root.page_id)
            return

        parent = self._load(left.parent)
        child_ids = parent.children()
        try:
            left_index = child_ids.index(left.page_id)
        except ValueError as exc:
            raise StorageError("parent does not reference child during split") from exc

        # Separator cells correspond to the right child after each child slot.
        parent.internal_cells.insert(left_index, InternalCell(key, right.page_id))
        right.parent = parent.page_id
        self._store(right)
        if parent.fits(self.pager.page_size):
            self._store(parent)
            return
        self._split_internal(parent)

    def _split_internal(self, node: BTreeNode) -> None:
        cells = node.internal_cells
        if len(cells) < 3:
            raise StorageError("internal node cannot be split safely")
        mid = len(cells) // 2
        promote = cells[mid]

        right = self._allocate_node(NodeType.INTERNAL, parent=node.parent)
        right.first_child = promote.right_child
        right.internal_cells = cells[mid + 1 :]
        node.internal_cells = cells[:mid]

        # Update child parent pointers on the new right subtree.
        for child_id in right.children():
            child = self._load(child_id)
            child.parent = right.page_id
            self._store(child)

        self._store(node)
        self._store(right)
        self._insert_into_parent(node, promote.key, right)

    def dump(self) -> str:
        """Return a compact human-readable tree for teaching/debugging."""
        lines: list[str] = []

        def visit(page_id: int, prefix: str) -> None:
            node = self._load(page_id)
            if node.is_leaf:
                keys = ", ".join(str(c.key) for c in node.leaf_cells)
                lines.append(
                    f"{prefix}page {page_id} LEAF parent={node.parent} "
                    f"right={node.right_sibling} keys=[{keys}]"
                )
                return
            seps = ", ".join(str(c.key) for c in node.internal_cells)
            lines.append(
                f"{prefix}page {page_id} INTERNAL parent={node.parent} separators=[{seps}]"
            )
            for child in node.children():
                visit(child, prefix + "  ")

        visit(self.root_page, "")
        return "\n".join(lines)

    def get_required(self, key: int) -> bytes:
        value = self.search(key)
        if value is None:
            raise NotFoundError(f"key {key} not found")
        return value
