from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import StorageError, TransactionError
from mini_sqlite.storage.buffer import BufferFrame, BufferManager
from mini_sqlite.storage.freelist import FreePage
from mini_sqlite.storage.journal import RollbackJournal
from mini_sqlite.storage.wal import WriteAheadLog


class Pager:
    """Own page I/O, a bounded buffer pool, and durability-mode behavior."""

    def __init__(self, path: str | Path, page_size: int = PAGE_SIZE, *, journal_mode: str = "rollback", buffer_pages: int = 64, replacement_policy: str = "clock", recover: bool = True):
        self.path = Path(path)
        self.page_size = page_size
        normalized_mode = journal_mode.lower().strip()
        if normalized_mode not in {"rollback", "wal"}:
            raise StorageError(f"unsupported journal mode {journal_mode!r}")
        self.journal_mode = normalized_mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO = self._open_file()
        self.buffer = BufferManager(buffer_pages, replacement_policy)
        self._journal: RollbackJournal | None = None
        self._journaled_pages: set[int] = set()
        self._transaction_original_page_count: int | None = None
        self._journal_needs_sync = False
        self._transaction_dirty_pages: set[int] = set()
        self._wal_before_images: dict[int, bytes] = {}
        self._free_list_head = 0
        self._persist_free_list_head: Callable[[int], None] | None = None
        self._transaction_original_free_list_head: int | None = None
        self._pending_truncate_page_count: int | None = None

        rollback_recovery = False
        if recover:
            rollback_recovery = RollbackJournal.recover_if_hot(self.path, self._file, expected_page_size=self.page_size)
        self._file.seek(0, os.SEEK_END)
        size = self._file.tell()
        if size % page_size != 0:
            raise StorageError(f"database file size {size} is not page aligned")
        self._database_page_count = size // page_size
        self._wal: WriteAheadLog | None = None
        wal_recovery = False
        if self.journal_mode == "wal":
            self._wal = WriteAheadLog(self.path, page_size=self.page_size, recover_tail=recover)
            wal_recovery = self._wal.recovery_performed
            wal_count = self._wal.page_count or 0
            self._page_count = max(self._database_page_count, wal_count)
        else:
            if recover:
                wal_recovery = WriteAheadLog.checkpoint_existing_into_database(self.path, self._file, expected_page_size=self.page_size, database_page_count=self._database_page_count)
            if wal_recovery:
                self._file.seek(0, os.SEEK_END)
                self._database_page_count = self._file.tell() // self.page_size
            self._page_count = self._database_page_count
        self.recovery_performed = rollback_recovery or wal_recovery

    def _open_file(self) -> BinaryIO:
        return self.path.open("r+b") if self.path.exists() else self.path.open("w+b")

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

    def wal_signature(self) -> tuple[int, int]:
        return (0, 0) if self._wal is None else self._wal.disk_signature()

    @property
    def free_list_head(self) -> int:
        return self._free_list_head

    def configure_free_list(self, head_page: int, persist_head: Callable[[int], None]) -> None:
        if head_page < 0 or head_page >= max(1, self._page_count):
            if head_page != 0:
                raise StorageError(f"free-list head {head_page} is out of range")
        self._free_list_head = head_page
        self._persist_free_list_head = persist_head

    def _set_free_list_head(self, page_id: int) -> None:
        if page_id < 0 or page_id >= max(1, self._page_count):
            if page_id != 0:
                raise StorageError(f"free-list head {page_id} is out of range")
        self._free_list_head = page_id
        if self._persist_free_list_head is not None:
            self._persist_free_list_head(page_id)

    def free_list_pages(self) -> list[int]:
        pages: list[int] = []
        seen: set[int] = set()
        current = self._free_list_head
        while current:
            if current <= 0 or current >= self._page_count:
                raise StorageError(f"free-list points outside database: page {current}")
            if current in seen:
                raise StorageError(f"free-list cycle detected at page {current}")
            seen.add(current)
            pages.append(current)
            with self.pin_page(current) as raw:
                node = FreePage.decode(raw)
            current = node.next_page
        return pages

    def free_page(self, page_id: int) -> None:
        if not self.in_transaction:
            raise TransactionError("free_page requires an active transaction")
        if self._pending_truncate_page_count is not None:
            raise TransactionError("cannot free pages after incremental truncation is scheduled")
        if page_id <= 0 or page_id >= self._page_count:
            raise StorageError(f"cannot free page {page_id}; count={self._page_count}")
        if page_id in set(self.free_list_pages()):
            raise StorageError(f"page {page_id} is already free")
        self.write_page(page_id, FreePage(self._free_list_head).encode(self.page_size))
        self._set_free_list_head(page_id)

    def trim_free_tail(self, max_pages: int | None = None) -> int:
        if not self.in_transaction:
            raise TransactionError("incremental vacuum requires an active transaction")
        if self._pending_truncate_page_count is not None:
            raise TransactionError("incremental truncation already scheduled")
        if max_pages is not None and max_pages < 0:
            raise ValueError("max_pages must be >= 0 or None")
        if max_pages == 0:
            return 0
        chain = self.free_list_pages()
        free_set = set(chain)
        new_count = self._page_count
        reclaimed: list[int] = []
        while new_count > 1 and (new_count - 1) in free_set:
            if max_pages is not None and len(reclaimed) >= max_pages:
                break
            reclaimed.append(new_count - 1)
            new_count -= 1
        if not reclaimed:
            return 0
        reclaimed_set = set(reclaimed)
        kept = [page_id for page_id in chain if page_id not in reclaimed_set]
        for i, page_id in enumerate(kept):
            expected_next = kept[i + 1] if i + 1 < len(kept) else 0
            with self.pin_page(page_id) as raw:
                current_next = FreePage.decode(raw).next_page
            if current_next != expected_next:
                self.write_page(page_id, FreePage(expected_next).encode(self.page_size))
        if self.journal_mode == "rollback":
            for page_id in reclaimed:
                self._capture_before_image(page_id)
        self._set_free_list_head(kept[0] if kept else 0)
        self._pending_truncate_page_count = new_count
        return len(reclaimed)

    def refresh_from_disk(self) -> None:
        if self.in_transaction:
            raise TransactionError("cannot refresh Pager during an active transaction")
        stats = self.buffer.stats()
        if stats["dirty"]:
            raise StorageError("cannot refresh Pager with dirty idle buffer frames")
        self.buffer.clear()
        self._file.seek(0, os.SEEK_END)
        size = self._file.tell()
        if size % self.page_size != 0:
            raise StorageError(f"database file size {size} is not page aligned")
        self._database_page_count = size // self.page_size
        if self._wal is not None:
            self._wal.refresh()
            wal_count = self._wal.page_count or 0
            self._page_count = max(self._database_page_count, wal_count)
        else:
            self._page_count = self._database_page_count

    def _load_page_bytes(self, page_id: int) -> bytes:
        raw: bytes | None = None
        if self._wal is not None:
            raw = self._wal.read_page(page_id)
        if raw is not None:
            return raw
        if page_id >= self._database_page_count:
            raise StorageError(f"page {page_id} is not present in database file or committed WAL")
        self._file.seek(page_id * self.page_size)
        raw = self._file.read(self.page_size)
        if len(raw) != self.page_size:
            raise StorageError(f"short read for page {page_id}")
        return raw

    def _can_evict_frame(self, frame: BufferFrame) -> bool:
        if not frame.dirty:
            return True
        if self.journal_mode == "wal" and self.in_transaction and frame.page_id in self._transaction_dirty_pages:
            return False
        return True

    def _evict_frame(self, frame: BufferFrame) -> None:
        if frame.dirty:
            self.flush_page(frame.page_id)

    def get_page(self, page_id: int) -> bytearray:
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range; count={self._page_count}")
        return self.buffer.fetch(page_id, self._load_page_bytes, can_evict=self._can_evict_frame, on_evict=self._evict_frame).data

    @contextmanager
    def pin_page(self, page_id: int) -> Iterator[bytearray]:
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range; count={self._page_count}")
        frame = self.buffer.fetch(page_id, self._load_page_bytes, pin=True, can_evict=self._can_evict_frame, on_evict=self._evict_frame)
        try:
            yield frame.data
        finally:
            self.buffer.unpin(page_id)

    def allocate_page(self) -> int:
        if self._pending_truncate_page_count is not None:
            raise TransactionError("cannot allocate pages after incremental truncation is scheduled")
        if self._free_list_head:
            if not self.in_transaction:
                raise TransactionError("reusing a free page requires an active transaction")
            page_id = self._free_list_head
            with self.pin_page(page_id) as raw:
                free = FreePage.decode(raw)
            if free.next_page == page_id or free.next_page < 0 or free.next_page >= self._page_count:
                if free.next_page != 0:
                    raise StorageError(f"free page {page_id} has invalid next pointer {free.next_page}")
            self.write_page(page_id, bytes(self.page_size))
            self._set_free_list_head(free.next_page)
            return page_id
        if self.in_transaction and self.journal_mode == "rollback":
            self._ensure_rollback_journal()
        page_id = self._page_count
        self._page_count += 1
        try:
            self.buffer.install(page_id, bytearray(self.page_size), dirty=True, can_evict=self._can_evict_frame, on_evict=self._evict_frame)
        except BaseException:
            self._page_count -= 1
            raise
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)
        return page_id

    def write_page(self, page_id: int, data: bytes | bytearray) -> None:
        if len(data) != self.page_size:
            raise StorageError(f"page writes must be exactly {self.page_size} bytes, got {len(data)}")
        if page_id < 0 or page_id >= self._page_count:
            raise StorageError(f"page {page_id} out of range")
        self._capture_before_image(page_id)
        self.buffer.install(page_id, data, dirty=True, can_evict=self._can_evict_frame, on_evict=self._evict_frame)
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)

    def mark_dirty(self, page_id: int) -> None:
        self._capture_before_image(page_id)
        if page_id not in self.buffer:
            self.get_page(page_id)
        self.buffer.mark_dirty(page_id)
        if self.in_transaction:
            self._transaction_dirty_pages.add(page_id)

    def _ensure_rollback_journal(self) -> RollbackJournal:
        if self.journal_mode != "rollback":
            raise TransactionError("rollback journal requested in WAL mode")
        if not self.in_transaction:
            raise TransactionError("rollback journal requires an active transaction")
        if self._journal is None:
            assert self._transaction_original_page_count is not None
            self._journal = RollbackJournal.create(self.path, page_size=self.page_size, original_page_count=self._transaction_original_page_count)
        return self._journal

    def _capture_before_image(self, page_id: int) -> None:
        if not self.in_transaction:
            return
        assert self._transaction_original_page_count is not None
        if page_id >= self._transaction_original_page_count:
            return
        if self.journal_mode == "wal":
            if page_id not in self._wal_before_images:
                with self.pin_page(page_id) as page:
                    self._wal_before_images[page_id] = bytes(page)
            return
        if page_id in self._journaled_pages:
            return
        journal = self._ensure_rollback_journal()
        with self.pin_page(page_id) as page:
            before = bytes(page)
        journal.append_before_image(page_id, before)
        self._journaled_pages.add(page_id)
        self._journal_needs_sync = True

    def begin_transaction(self) -> None:
        if self.in_transaction:
            raise TransactionError("pager transaction already active")
        self._transaction_original_page_count = self._page_count
        self._transaction_original_free_list_head = self._free_list_head
        self._pending_truncate_page_count = None
        self._transaction_dirty_pages.clear()
        self._wal_before_images.clear()
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
        target_count = self._pending_truncate_page_count or self._page_count
        if self.journal_mode == "wal":
            assert self._wal is not None
            frames: list[tuple[int, bytes]] = []
            for page_id in sorted(self._transaction_dirty_pages):
                if page_id >= target_count:
                    raise StorageError(f"dirty page {page_id} lies beyond scheduled page_count {target_count}")
                frame = self.buffer.frame(page_id)
                if frame is None:
                    raise StorageError(f"uncommitted WAL page {page_id} left the buffer before commit")
                frames.append((page_id, bytes(frame.data)))
            if frames or target_count != self._page_count:
                self._wal.append_transaction(frames, page_count=target_count)
                for page_id in self._transaction_dirty_pages:
                    self.buffer.mark_clean(page_id)
            if target_count != self._page_count:
                for page_id in list(self.buffer.page_ids()):
                    if page_id >= target_count:
                        self.buffer.remove(page_id)
                self._page_count = target_count
            self._clear_transaction_state()
            return
        if self._journal is None:
            self._clear_transaction_state()
            return
        self._sync_journal_if_needed()
        self.flush_all(sync=True)
        if target_count != self._page_count:
            self._file.truncate(target_count * self.page_size)
            self._file.flush()
            os.fsync(self._file.fileno())
            for page_id in list(self.buffer.page_ids()):
                if page_id >= target_count:
                    self.buffer.remove(page_id)
            self._page_count = target_count
            self._database_page_count = target_count
        self._journal.delete()
        self._database_page_count = self._page_count
        self._clear_transaction_state()

    def rollback_transaction(self) -> None:
        if not self.in_transaction:
            raise TransactionError("cannot rollback without an active pager transaction")
        assert self._transaction_original_page_count is not None
        original_free_head = self._transaction_original_free_list_head
        if self.journal_mode == "wal":
            original_count = self._transaction_original_page_count
            for page_id, before in self._wal_before_images.items():
                frame = self.buffer.frame(page_id)
                if frame is None:
                    raise StorageError(f"cannot rollback WAL page {page_id}: frame is not resident")
                frame.data[:] = before
                frame.dirty = False
            for page_id in list(self.buffer.page_ids()):
                if page_id >= original_count:
                    self.buffer.remove(page_id)
            self._page_count = original_count
            if original_free_head is not None:
                self._free_list_head = original_free_head
            self._clear_transaction_state()
            return
        if self._journal is None:
            if original_free_head is not None:
                self._free_list_head = original_free_head
            self._clear_transaction_state()
            return
        original_count = self._journal.original_page_count
        self._journal.restore_into(self._file)
        self.buffer.clear()
        self._page_count = original_count
        self._database_page_count = original_count
        if original_free_head is not None:
            self._free_list_head = original_free_head
        self._journal.delete()
        self._clear_transaction_state()

    def _clear_transaction_state(self) -> None:
        self._journal = None
        self._journaled_pages.clear()
        self._transaction_dirty_pages.clear()
        self._wal_before_images.clear()
        self._transaction_original_page_count = None
        self._transaction_original_free_list_head = None
        self._pending_truncate_page_count = None
        self._journal_needs_sync = False

    def flush_page(self, page_id: int) -> None:
        frame = self.buffer.frame(page_id)
        if frame is None or not frame.dirty:
            return
        if self.journal_mode == "wal" and self.in_transaction and page_id in self._transaction_dirty_pages:
            return
        self._sync_journal_if_needed()
        self._file.seek(page_id * self.page_size)
        self._file.write(frame.data)
        frame.dirty = False
        self._database_page_count = max(self._database_page_count, page_id + 1)

    def flush_all(self, sync: bool = True) -> None:
        self._sync_journal_if_needed()
        for page_id in sorted(self.buffer.page_ids()):
            self.flush_page(page_id)
        self._file.flush()
        if sync:
            os.fsync(self._file.fileno())

    def clear_cache(self) -> None:
        self.flush_all()
        self.buffer.clear()

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
            return {"mode": self.journal_mode, "wal_exists": self.wal_path.exists(), "committed_transactions": 0, "committed_frames": 0, "overlay_pages": 0, "wal_bytes": self.wal_path.stat().st_size if self.wal_path.exists() else 0}
        return {"mode": self.journal_mode, "wal_exists": self._wal.exists, "committed_transactions": self._wal.committed_transactions, "committed_frames": self._wal.committed_frames, "overlay_pages": len(self._wal.overlay), "wal_bytes": self._wal.file_size}

    def buffer_stats(self) -> dict[str, int | str]:
        return self.buffer.stats()

    def buffer_snapshot(self) -> list[dict[str, int | bool]]:
        return self.buffer.snapshot()

    def stats(self) -> dict[str, int | bool | str]:
        buffer_stats = self.buffer.stats()
        return {"page_count": self._page_count, "cached_pages": len(self.buffer), "dirty_pages": buffer_stats["dirty"], "buffer_capacity": buffer_stats["capacity"], "buffer_policy": buffer_stats["policy"], "buffer_hits": buffer_stats["hits"], "buffer_misses": buffer_stats["misses"], "buffer_evictions": buffer_stats["evictions"], "buffer_dirty_evictions": buffer_stats["dirty_evictions"], "buffer_pinned": buffer_stats["pinned"], "transaction_active": self.in_transaction, "journal_mode": self.journal_mode, "journaled_pages": len(self._journaled_pages), "transaction_dirty_pages": len(self._transaction_dirty_pages), "wal_overlay_pages": len(self._wal.overlay) if self._wal is not None else 0, "free_list_head": self._free_list_head, "pending_truncate_page_count": self._pending_truncate_page_count or 0, "recovery_performed": self.recovery_performed}

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
