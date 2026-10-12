from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import StorageError, TransactionError
from mini_sqlite.storage.journal import RollbackJournal


@dataclass
class CachedPage:
    data: bytearray
    dirty: bool = False


class Pager:
    """Own fixed-size page I/O, caching, and rollback-journal durability.

    The B+Tree only sees logical page operations. v0.2 adds transactions here so
    tree code remains unaware of fsync ordering, before-images, and crash recovery.
    """

    def __init__(self, path: str | Path, page_size: int = PAGE_SIZE):
        self.path = Path(path)
        self.page_size = page_size
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO = self._open_file()
        self._cache: dict[int, CachedPage] = {}
        self._journal: RollbackJournal | None = None
        self._journaled_pages: set[int] = set()
        self._transaction_original_page_count: int | None = None
        self._journal_needs_sync = False

        self.recovery_performed = RollbackJournal.recover_if_hot(
            self.path, self._file, expected_page_size=self.page_size
        )

        self._file.seek(0, os.SEEK_END)
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

    @property
    def in_transaction(self) -> bool:
        return self._journal is not None

    @property
    def journal_path(self) -> Path:
        return RollbackJournal.path_for(self.path)

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
        self._capture_before_image(page_id)
        self._cache[page_id] = CachedPage(bytearray(data), dirty=True)

    def mark_dirty(self, page_id: int) -> None:
        # Call mark_dirty *before* mutating a buffer returned by get_page().
        # Internal storage code uses write_page(), which cannot violate this rule.
        self._capture_before_image(page_id)
        if page_id not in self._cache:
            self.get_page(page_id)
        self._cache[page_id].dirty = True

    def _capture_before_image(self, page_id: int) -> None:
        if not self.in_transaction:
            return
        assert self._transaction_original_page_count is not None
        if page_id >= self._transaction_original_page_count:
            return  # new pages disappear via truncate on rollback
        if page_id in self._journaled_pages:
            return
        assert self._journal is not None
        before = bytes(self.get_page(page_id))
        self._journal.append_before_image(page_id, before)
        self._journaled_pages.add(page_id)
        self._journal_needs_sync = True

    def begin_transaction(self) -> None:
        if self.in_transaction:
            raise TransactionError("pager transaction already active")
        self._transaction_original_page_count = self._page_count
        self._journal = RollbackJournal.create(
            self.path,
            page_size=self.page_size,
            original_page_count=self._page_count,
        )
        self._journaled_pages.clear()
        self._journal_needs_sync = False

    def _sync_journal_if_needed(self) -> None:
        if self._journal is not None and self._journal_needs_sync:
            self._journal.sync()
            self._journal_needs_sync = False

    def commit_transaction(self) -> None:
        if not self.in_transaction:
            raise TransactionError("cannot commit without an active pager transaction")
        assert self._journal is not None
        # WAL is not used in v0.2. The rollback journal must reach stable storage
        # before any dirty database page can reach stable storage.
        self._sync_journal_if_needed()
        self.flush_all(sync=True)
        # Journal deletion is the commit point.
        self._journal.delete()
        self._clear_transaction_state()

    def rollback_transaction(self) -> None:
        if not self.in_transaction:
            raise TransactionError("cannot rollback without an active pager transaction")
        assert self._journal is not None
        original_count = self._journal.original_page_count
        self._journal.restore_into(self._file)
        self._cache.clear()
        self._page_count = original_count
        self._journal.delete()
        self._clear_transaction_state()

    def _clear_transaction_state(self) -> None:
        self._journal = None
        self._journaled_pages.clear()
        self._transaction_original_page_count = None
        self._journal_needs_sync = False

    def flush_page(self, page_id: int) -> None:
        cached = self._cache.get(page_id)
        if cached is None or not cached.dirty:
            return
        self._sync_journal_if_needed()
        self._file.seek(page_id * self.page_size)
        self._file.write(cached.data)
        cached.dirty = False

    def flush_all(self, sync: bool = True) -> None:
        self._sync_journal_if_needed()
        for page_id in sorted(self._cache):
            self.flush_page(page_id)
        self._file.flush()
        if sync:
            os.fsync(self._file.fileno())

    def stats(self) -> dict[str, int | bool]:
        return {
            "page_count": self._page_count,
            "cached_pages": len(self._cache),
            "dirty_pages": sum(1 for p in self._cache.values() if p.dirty),
            "transaction_active": self.in_transaction,
            "journaled_pages": len(self._journaled_pages),
            "recovery_performed": self.recovery_performed,
        }

    def close(self) -> None:
        if self._file.closed:
            return
        # Closing a connection never commits an explicit unfinished transaction.
        if self.in_transaction:
            self.rollback_transaction()
        else:
            self.flush_all()
        self._file.close()

    def __enter__(self) -> "Pager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
