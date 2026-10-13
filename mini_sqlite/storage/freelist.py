from __future__ import annotations

import struct
from dataclasses import dataclass

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import CorruptionError, StorageError

FREE_PAGE_MAGIC = b"MSQLFREE"
_FREE_HEADER = struct.Struct("<8sI20s")
FREE_PAGE_HEADER_SIZE = _FREE_HEADER.size


@dataclass(frozen=True)
class FreePage:
    """Persisted singly-linked free-list node stored inside an unused page."""

    next_page: int = 0

    def encode(self, page_size: int = PAGE_SIZE) -> bytes:
        if page_size < FREE_PAGE_HEADER_SIZE:
            raise StorageError("page size too small for free-page header")
        if self.next_page < 0:
            raise StorageError("free-list next page cannot be negative")
        page = bytearray(page_size)
        _FREE_HEADER.pack_into(page, 0, FREE_PAGE_MAGIC, self.next_page, b"\x00" * 20)
        return bytes(page)

    @classmethod
    def decode(cls, page: bytes | bytearray) -> "FreePage":
        if len(page) < FREE_PAGE_HEADER_SIZE:
            raise CorruptionError("free page is too small")
        magic, next_page, reserved = _FREE_HEADER.unpack_from(page, 0)
        if magic != FREE_PAGE_MAGIC:
            raise CorruptionError("page is not a valid free-list page")
        if reserved != b"\x00" * 20:
            raise CorruptionError("free-page reserved bytes are non-zero")
        return cls(next_page=next_page)

    @classmethod
    def looks_free(cls, page: bytes | bytearray) -> bool:
        return len(page) >= 8 and bytes(page[:8]) == FREE_PAGE_MAGIC
