from __future__ import annotations

import struct
from dataclasses import dataclass

from mini_sqlite.constants import DB_MAGIC, FORMAT_VERSION, PAGE_SIZE
from mini_sqlite.errors import CorruptionError

_META = struct.Struct("<8sHHIII")


@dataclass
class DatabaseMeta:
    page_size: int = PAGE_SIZE
    catalog_root_page: int = 1
    next_table_id: int = 1
    version: int = FORMAT_VERSION

    def encode(self) -> bytes:
        page = bytearray(self.page_size)
        _META.pack_into(
            page,
            0,
            DB_MAGIC,
            self.version,
            self.page_size,
            self.catalog_root_page,
            self.next_table_id,
            0,
        )
        return bytes(page)

    @classmethod
    def decode(cls, page: bytes | bytearray) -> "DatabaseMeta":
        if len(page) < _META.size:
            raise CorruptionError("meta page too small")
        magic, version, page_size, catalog_root, next_table_id, _ = _META.unpack_from(page, 0)
        if magic != DB_MAGIC:
            raise CorruptionError(f"bad database magic: {magic!r}")
        if version != FORMAT_VERSION:
            raise CorruptionError(f"unsupported format version {version}")
        if page_size != len(page):
            raise CorruptionError(
                f"meta page declares page_size={page_size}, actual={len(page)}"
            )
        return cls(
            page_size=page_size,
            catalog_root_page=catalog_root,
            next_table_id=next_table_id,
            version=version,
        )
