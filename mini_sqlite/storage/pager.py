from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import StorageError, TransactionError
from mini_sqlite.storage.journal import RollbackJournal
from mini_sqlite.storage.wal import WriteAheadLog


@dataclass
class CachedPage:
    data: bytearray
    dirty: bool = False


class Pager:
    """Own fixed-size page I/O, caching, and durability-mode behavior.

    B+Trees only see logical page operations. Rollback-journal mode uses physical
    before-images; WAL mode appends committed after-images and overlays them on
    reads until checkpoint. Query/storage layers stay unaware of that distinction.
    """

    def __init__(
        self,
        path: str | Path,
        page_size: int = PAGE_SIZE,
        *,
        journal_mode: str = "rollback",
    ):
        self.path = Path(path)
        self.page_size = page_size
        normalized_mode = journal_mode.lower().strip()
        if normalized_mode not in {"rollback", "wal"}:
            raise StorageError(f"unsupported journal mode {journal_mode!r}")
        self.journal_mode = normalized_mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO = self._open_file()
        self._cache: dict[int, CachedPage] = {}
        self._journal: RollbackJournal | None = None
        self._journaled_pages: set[int] = set()
        self._transaction_original_page_count: int | None = None
        self._journal_needs_sync = False
        self._transaction_dirty_pages: set[int] = set()
        self._wal_before_images: dict[int, bytes] = {}

        rollback_recovery = RollbackJournal.recover_if_hot(
            self.path, self._file, expected_page_size=self.page_size
        )

        self._file.seek(0, os.SEEK_END)
        size = self._file.tell()
        if size % page_size != 0:
            raise StorageError(f"database file size {size} is not page aligned")
        self._database_page_count = size // page_size

        self._wal: WriteAheadLog | None = None
        wal_recovery = False
        if self.journal_mode == "wal":
            self._wal = WriteAheadLog(self.path, page_size=self.page_size)
            wal_recovery = self._wal.recovery_performed
            wal_count = self._wal.page_count or 0
            self._page_count = max(self._database_page_count, wal_count)
        else:
            wal_recovery = WriteAheadLog.checkpoint_existing_into_database(
                self.path,
                self._file,
                expected_page_size=self.page_size,
                database_page_count=self._database_page_count,
            )
            if wal_recovery:
                self._file.seek(0, os.SEEK_END)
                self._database_page_count = self._file.tell() // self.page_size
            self._page_count = self._database_page_count

        self.recovery_performed = rollback_recovery or wal_recovery

    def _open_file(self) -> BinaryIO:
        if self.path.exists():
            return self.path.open("r+b")
        return self.path.open("w+b")

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def in_transaction(self) -> bool:
        return self._transaction_original_page_count is not None

    @property
    def journal_path(self) -> Path:
        return RollbackJournal.path_for(self.path)

    @property
    def wal_path(self) -> Path:
        return WriteAheadLog.path_for(self.path)

    def get_page(self, page_id: int) -> bytearray:
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range; count={self._page_count}")
        cached = self._cache.get(page_id)
        if cached is not None:
            return cached.data

        raw: bytes | None = None
        if self._wal is not None:
            raw = self._wal.read_page(page_id)
        if raw is None:
            if page_id >= self._database_page_count:
                raise StorageError(
                    f"page {page_id} is not present in database file or committed WAL"
                )
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
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)
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
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)

    def mark_dirty(self, page_id: int) -> None:
        self._capture_before_image(page_id)
        if page_id not in self._cache:
            self.get_page(page_id)
        self._cache[page_id].dirty = True
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)

    def _capture_before_image(self, page_id: int) -> None:
        if not self.in_transaction:
            return
        assert self._transaction_original_page_count is not None
        if page_id >= self._transaction_original_page_count:
            return

        if self.journal_mode == "wal":
            if page_id not in self._wal_before_images:
                self._wal_before_images[page_id] = bytes(self.get_page(page_id))
            return

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
        self._transaction_dirty_pages.clear()
        self._wal_before_images.clear()
        if self.journal_mode == "rollback":
            self._journal = RollbackJournal.create(
                self.path,
                page_size=self.page_size,
                original_page_count=self._page_count,
            )
        else:
            self._journal = None
        self._journaled_pages.clear()
        self._journal_needs_sync = False

    def _sync_journal_if_needed(self) -> None:
        if self._journal is not None and self._journal_needs_sync:
            self._journal.sync()
            self._journal_needs_sync = False

    def commit_transaction(self) -> None:
        if not self.in_transaction:
            raise TransactionError("cannot commit without an active pager transaction")

        if self.journal_mode == "wal":
            assert self._wal is not None
            frames = [
                (page_id, bytes(self._cache[page_id].data))
                for page_id in sorted(self._transaction_dirty_pages)
            ]
            if frames:
                self._wal.append_transaction(frames, page_count=self._page_count)
                for page_id in self._transaction_dirty_pages:
                    cached = self._cache.get(page_id)
                    if cached is not None:
                        cached.dirty = False
            self._clear_transaction_state()
            return

        assert self._journal is not None
        self._sync_journal_if_needed()
        self.flush_all(sync=True)
        self._journal.delete()
        self._database_page_count = self._page_count
        self._clear_transaction_state()

    def rollback_transaction(self) -> None:
        if not self.in_transaction:
            raise TransactionError("cannot rollback without an active pager transaction")
        assert self._transaction_original_page_count is not None

        if self.journal_mode == "wal":
            original_count = self._transaction_original_page_count
            for page_id, before in self._wal_before_images.items():
                self._cache[page_id] = CachedPage(bytearray(before), dirty=False)
            for page_id in list(self._cache):
                if page_id >= original_count:
                    del self._cache[page_id]
            self._page_count = original_count
            self._clear_transaction_state()
            return

        assert self._journal is not None
        original_count = self._journal.original_page_count
        self._journal.restore_into(self._file)
        self._cache.clear()
        self._page_count = original_count
        self._database_page_count = original_count
        self._journal.delete()
        self._clear_transaction_state()

    def _clear_transaction_state(self) -> None:
        self._journal = None
        self._journaled_pages.clear()
        self._transaction_dirty_pages.clear()
        self._wal_before_images.clear()
        self._transaction_original_page_count = None
        self._journal_needs_sync = False

    def flush_page(self, page_id: int) -> None:
        cached = self._cache.get(page_id)
        if cached is None or not cached.dirty:
            return
        if self.journal_mode == "wal" and self.in_transaction:
            return
        self._sync_journal_if_needed()
        self._file.seek(page_id * self.page_size)
        self._file.write(cached.data)
        cached.dirty = False
        self._database_page_count = max(self._database_page_count, page_id + 1)

    def flush_all(self, sync: bool = True) -> None:
        self._sync_journal_if_needed()
        for page_id in sorted(self._cache):
            self.flush_page(page_id)
        self._file.flush()
        if sync:
            os.fsync(self._file.fileno())

    def checkpoint(self) -> int:
        if self.journal_mode != "wal":
            raise TransactionError("checkpoint is only available in WAL mode")
        if self.in_transaction:
            raise TransactionError("cannot checkpoint during an active transaction")
        assert self._wal is not None
        copied = self._wal.checkpoint_into(self._file, page_count=self._page_count)
        if copied:
            self._database_page_count = self._page_count
        return copied

    def wal_stats(self) -> dict[str, int | bool | str]:
        if self._wal is None:
            return {
                "mode": self.journal_mode,
                "wal_exists": self.wal_path.exists(),
                "committed_transactions": 0,
                "committed_frames": 0,
                "overlay_pages": 0,
                "wal_bytes": self.wal_path.stat().st_size if self.wal_path.exists() else 0,
            }
        return {
            "mode": self.journal_mode,
            "wal_exists": self._wal.exists,
            "committed_transactions": self._wal.committed_transactions,
            "committed_frames": self._wal.committed_frames,
            "overlay_pages": len(self._wal.overlay),
            "wal_bytes": self._wal.file_size,
        }

    def stats(self) -> dict[str, int | bool | str]:
        return {
            "page_count": self._page_count,
            "cached_pages": len(self._cache),
            "dirty_pages": sum(1 for p in self._cache.values() if p.dirty),
            "transaction_active": self.in_transaction,
            "journal_mode": self.journal_mode,
            "journaled_pages": len(self._journaled_pages),
            "transaction_dirty_pages": len(self._transaction_dirty_pages),
            "wal_overlay_pages": len(self._wal.overlay) if self._wal is not None else 0,
            "recovery_performed": self.recovery_performed,
        }

    def close(self) -> None:
        if self._file.closed:
            return
        if self.in_transaction:
            self.rollback_transaction()
        else:
            self.flush_all()
        self._file.close()

    def __enter__(self) -> "Pager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
