from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import StorageError


@dataclass
class CachedPage:
    data: bytearray
    dirty: bool = False


class Pager:
    """Owns fixed-size page I/O and a tiny in-process page cache.

    v0.1 keeps cache policy deliberately simple: pages remain cached for the
    lifetime of the Database. v0.7 can replace this with LRU/Clock eviction
    without changing the B+Tree API.
    """

    def __init__(self, path: str | Path, page_size: int = PAGE_SIZE):
        self.path = Path(path)
        self.page_size = page_size
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO = self._open_file()
        self._cache: dict[int, CachedPage] = {}

        self._file.seek(0, 2)
        size = self._file.tell()
        if size % page_size != 0:
            raise StorageError(f"database file size {size} is not page aligned")
        self._page_count = size // page_size

    def _open_file(self) -> BinaryIO:
        if self.path.exists():
            return self.path.open("r+b")
        return self.path.open("w+b")

    @property
    def page_count(self) -> int:
        return self._page_count

    def get_page(self, page_id: int) -> bytearray:
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range; count={self._page_count}")
        cached = self._cache.get(page_id)
        if cached is not None:
            return cached.data

        self._file.seek(page_id * self.page_size)
        raw = self._file.read(self.page_size)
        if len(raw) != self.page_size:
            raise StorageError(f"short read for page {page_id}")
        page = CachedPage(bytearray(raw))
        self._cache[page_id] = page
        return page.data

    def allocate_page(self) -> int:
        page_id = self._page_count
        self._page_count += 1
        self._cache[page_id] = CachedPage(bytearray(self.page_size), dirty=True)
        return page_id

    def write_page(self, page_id: int, data: bytes | bytearray) -> None:
        if len(data) != self.page_size:
            raise StorageError(
                f"page writes must be exactly {self.page_size} bytes, got {len(data)}"
            )
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range")
        self._cache[page_id] = CachedPage(bytearray(data), dirty=True)

    def mark_dirty(self, page_id: int) -> None:
        if page_id not in self._cache:
            self.get_page(page_id)
        self._cache[page_id].dirty = True

    def flush_page(self, page_id: int) -> None:
        cached = self._cache.get(page_id)
        if cached is None or not cached.dirty:
            return
        self._file.seek(page_id * self.page_size)
        self._file.write(cached.data)
        cached.dirty = False

    def flush_all(self, sync: bool = True) -> None:
        for page_id in sorted(self._cache):
            self.flush_page(page_id)
        self._file.flush()
        if sync:
            import os

            os.fsync(self._file.fileno())

    def stats(self) -> dict[str, int]:
        return {
            "page_count": self._page_count,
            "cached_pages": len(self._cache),
            "dirty_pages": sum(1 for p in self._cache.values() if p.dirty),
        }

    def close(self) -> None:
        if self._file.closed:
            return
        self.flush_all()
        self._file.close()

    def __enter__(self) -> "Pager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
