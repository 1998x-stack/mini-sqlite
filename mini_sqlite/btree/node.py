from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import CorruptionError, StorageError


class NodeType(IntEnum):
    LEAF = 1
    INTERNAL = 2


# type:u8 flags:u8 count:u16 parent:u32 right:u32 first_child:u32 free_start:u16 content_start:u16 reserved:12
_HEADER = struct.Struct("<BBHIIIHH12s")
HEADER_SIZE = _HEADER.size  # 32
_POINTER = struct.Struct("<H")
_LEAF_PREFIX = struct.Struct("<qI")       # key, value_len
_INTERNAL_CELL = struct.Struct("<qI")     # separator key, right child


@dataclass
class LeafCell:
    key: int
    value: bytes


@dataclass
class InternalCell:
    key: int
    right_child: int


@dataclass
class BTreeNode:
    page_id: int
    node_type: NodeType
    parent: int = 0
    right_sibling: int = 0
    first_child: int = 0
    leaf_cells: list[LeafCell] = field(default_factory=list)
    internal_cells: list[InternalCell] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return self.node_type == NodeType.LEAF

    @property
    def cell_count(self) -> int:
        return len(self.leaf_cells if self.is_leaf else self.internal_cells)

    def required_bytes(self) -> int:
        if self.is_leaf:
            cells = sum(_LEAF_PREFIX.size + len(c.value) for c in self.leaf_cells)
        else:
            cells = len(self.internal_cells) * _INTERNAL_CELL.size
        return HEADER_SIZE + self.cell_count * _POINTER.size + cells

    def fits(self, page_size: int = PAGE_SIZE) -> bool:
        return self.required_bytes() <= page_size

    def encode(self, page_size: int = PAGE_SIZE) -> bytes:
        if not self.fits(page_size):
            raise StorageError(
                f"node {self.page_id} requires {self.required_bytes()} bytes; page={page_size}"
            )
        page = bytearray(page_size)
        pointers: list[int] = []
        content_start = page_size

        if self.is_leaf:
            encoded_cells = [
                _LEAF_PREFIX.pack(c.key, len(c.value)) + c.value for c in self.leaf_cells
            ]
        else:
            encoded_cells = [
                _INTERNAL_CELL.pack(c.key, c.right_child) for c in self.internal_cells
            ]

        # Store payload from end of page backwards, while preserving logical order
        # through the pointer array.
        for raw in encoded_cells:
            content_start -= len(raw)
            page[content_start : content_start + len(raw)] = raw
            pointers.append(content_start)

        free_start = HEADER_SIZE + len(pointers) * _POINTER.size
        _HEADER.pack_into(
            page,
            0,
            int(self.node_type),
            0,
            self.cell_count,
            self.parent,
            self.right_sibling,
            self.first_child,
            free_start,
            content_start,
            b"\x00" * 12,
        )
        off = HEADER_SIZE
        for ptr in pointers:
            _POINTER.pack_into(page, off, ptr)
            off += _POINTER.size
        return bytes(page)

    @classmethod
    def decode(cls, page_id: int, page: bytes | bytearray) -> "BTreeNode":
        if len(page) < HEADER_SIZE:
            raise CorruptionError("B+Tree page too small")
        (
            raw_type,
            _flags,
            count,
            parent,
            right_sibling,
            first_child,
            free_start,
            content_start,
            _reserved,
        ) = _HEADER.unpack_from(page, 0)
        try:
            node_type = NodeType(raw_type)
        except ValueError as exc:
            raise CorruptionError(f"unknown node type {raw_type} on page {page_id}") from exc

        expected_free = HEADER_SIZE + count * _POINTER.size
        if free_start != expected_free or content_start < free_start or content_start > len(page):
            raise CorruptionError(f"invalid slotted-page bounds on page {page_id}")

        pointers = [
            _POINTER.unpack_from(page, HEADER_SIZE + i * _POINTER.size)[0]
            for i in range(count)
        ]
        node = cls(
            page_id=page_id,
            node_type=node_type,
            parent=parent,
            right_sibling=right_sibling,
            first_child=first_child,
        )

        for ptr in pointers:
            if ptr < content_start or ptr >= len(page):
                raise CorruptionError(f"bad cell pointer {ptr} on page {page_id}")
            if node_type == NodeType.LEAF:
                if ptr + _LEAF_PREFIX.size > len(page):
                    raise CorruptionError("truncated leaf cell")
                key, length = _LEAF_PREFIX.unpack_from(page, ptr)
                start = ptr + _LEAF_PREFIX.size
                end = start + length
                if end > len(page):
                    raise CorruptionError("truncated leaf value")
                node.leaf_cells.append(LeafCell(key, bytes(page[start:end])))
            else:
                if ptr + _INTERNAL_CELL.size > len(page):
                    raise CorruptionError("truncated internal cell")
                key, child = _INTERNAL_CELL.unpack_from(page, ptr)
                node.internal_cells.append(InternalCell(key, child))
        return node

    def child_for_key(self, key: int) -> int:
        if self.is_leaf:
            raise StorageError("leaf nodes do not have children")
        child = self.first_child
        for cell in self.internal_cells:
            if key < cell.key:
                return child
            child = cell.right_child
        return child

    def children(self) -> list[int]:
        if self.is_leaf:
            return []
        return [self.first_child] + [c.right_child for c in self.internal_cells]
