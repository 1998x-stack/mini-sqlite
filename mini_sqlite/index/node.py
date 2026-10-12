from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import CorruptionError, StorageError


class IndexNodeType(IntEnum):
    LEAF = 3
    INTERNAL = 4


# Keep the same 32-byte slotted-page header shape as the table B+Tree. Distinct
# node-type tags let page inspection distinguish table pages from index pages.
_HEADER = struct.Struct("<BBHIIIHH12s")
HEADER_SIZE = _HEADER.size
_POINTER = struct.Struct("<H")
_LEAF_PREFIX = struct.Struct("<HI")       # key_len:u16, value_len:u32
_INTERNAL_PREFIX = struct.Struct("<HI")   # key_len:u16, right_child:u32


@dataclass
class IndexLeafCell:
    key: bytes
    value: bytes


@dataclass
class IndexInternalCell:
    key: bytes
    right_child: int


@dataclass
class IndexNode:
    page_id: int
    node_type: IndexNodeType
    parent: int = 0
    right_sibling: int = 0
    first_child: int = 0
    leaf_cells: list[IndexLeafCell] = field(default_factory=list)
    internal_cells: list[IndexInternalCell] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return self.node_type == IndexNodeType.LEAF

    @property
    def cell_count(self) -> int:
        return len(self.leaf_cells if self.is_leaf else self.internal_cells)

    def required_bytes(self) -> int:
        if self.is_leaf:
            cells = sum(
                _LEAF_PREFIX.size + len(c.key) + len(c.value) for c in self.leaf_cells
            )
        else:
            cells = sum(_INTERNAL_PREFIX.size + len(c.key) for c in self.internal_cells)
        return HEADER_SIZE + self.cell_count * _POINTER.size + cells

    def fits(self, page_size: int = PAGE_SIZE) -> bool:
        return self.required_bytes() <= page_size

    def encode(self, page_size: int = PAGE_SIZE) -> bytes:
        if not self.fits(page_size):
            raise StorageError(
                f"index node {self.page_id} requires {self.required_bytes()} bytes; "
                f"page={page_size}"
            )
        page = bytearray(page_size)
        pointers: list[int] = []
        content_start = page_size

        if self.is_leaf:
            encoded_cells = [
                _LEAF_PREFIX.pack(len(c.key), len(c.value)) + c.key + c.value
                for c in self.leaf_cells
            ]
        else:
            encoded_cells = [
                _INTERNAL_PREFIX.pack(len(c.key), c.right_child) + c.key
                for c in self.internal_cells
            ]

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
    def decode(cls, page_id: int, page: bytes | bytearray) -> "IndexNode":
        if len(page) < HEADER_SIZE:
            raise CorruptionError("index B+Tree page too small")
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
            node_type = IndexNodeType(raw_type)
        except ValueError as exc:
            raise CorruptionError(
                f"unknown index node type {raw_type} on page {page_id}"
            ) from exc

        expected_free = HEADER_SIZE + count * _POINTER.size
        if free_start != expected_free or content_start < free_start or content_start > len(page):
            raise CorruptionError(f"invalid index slotted-page bounds on page {page_id}")

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
                raise CorruptionError(f"bad index cell pointer {ptr} on page {page_id}")
            if node_type == IndexNodeType.LEAF:
                if ptr + _LEAF_PREFIX.size > len(page):
                    raise CorruptionError("truncated index leaf cell")
                key_len, value_len = _LEAF_PREFIX.unpack_from(page, ptr)
                key_start = ptr + _LEAF_PREFIX.size
                key_end = key_start + key_len
                value_end = key_end + value_len
                if value_end > len(page):
                    raise CorruptionError("truncated index leaf payload")
                node.leaf_cells.append(
                    IndexLeafCell(bytes(page[key_start:key_end]), bytes(page[key_end:value_end]))
                )
            else:
                if ptr + _INTERNAL_PREFIX.size > len(page):
                    raise CorruptionError("truncated index internal cell")
                key_len, child = _INTERNAL_PREFIX.unpack_from(page, ptr)
                key_start = ptr + _INTERNAL_PREFIX.size
                key_end = key_start + key_len
                if key_end > len(page):
                    raise CorruptionError("truncated index separator key")
                node.internal_cells.append(IndexInternalCell(bytes(page[key_start:key_end]), child))
        return node

    def child_for_key(self, key: bytes) -> int:
        if self.is_leaf:
            raise StorageError("index leaf nodes do not have children")
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
