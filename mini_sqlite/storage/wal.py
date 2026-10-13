from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

from mini_sqlite.errors import CorruptionError, StorageError

WAL_MAGIC = b"MSQLWAL1"
WAL_VERSION = 1
_HEADER = struct.Struct("<8sHHI8s")
_RECORD = struct.Struct("<B7xQQII")
HEADER_SIZE = _HEADER.size
RECORD_SIZE = _RECORD.size

FRAME_RECORD = 1
COMMIT_RECORD = 2


@dataclass(frozen=True)
class WALScan:
    overlay: dict[int, bytes]
    page_count: int | None
    committed_transactions: int
    committed_frames: int
    ignored_tail: bool
    last_committed_offset: int


class WriteAheadLog:
    """Tiny physical after-image WAL used by mini-sqlite v0.6."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        page_size: int,
        recover_tail: bool = True,
    ) -> None:
        self.database_path = Path(database_path)
        self.path = self.path_for(database_path)
        self.page_size = page_size
        self.overlay: dict[int, bytes] = {}
        self.page_count: int | None = None
        self.committed_transactions = 0
        self.committed_frames = 0
        self.recovery_performed = False
        self._next_txid = 1
        if self.path.exists():
            scan = self._scan(self.path, expected_page_size=page_size)
            self._install_scan(scan)
            if scan.ignored_tail and recover_tail:
                self._truncate_to(scan.last_committed_offset)
                self.recovery_performed = True

    @staticmethod
    def path_for(database_path: str | Path) -> Path:
        db = Path(database_path)
        return db.with_name(db.name + "-wal")

    def _install_scan(self, scan: WALScan) -> None:
        self.overlay = dict(scan.overlay)
        self.page_count = scan.page_count
        self.committed_transactions = scan.committed_transactions
        self.committed_frames = scan.committed_frames
        self._next_txid = scan.committed_transactions + 1

    def refresh(self) -> None:
        """Reload the newest committed WAL prefix without truncating a live tail."""
        if not self.path.exists():
            self.overlay.clear()
            self.page_count = None
            self.committed_transactions = 0
            self.committed_frames = 0
            self._next_txid = 1
            return
        scan = self._scan(self.path, expected_page_size=self.page_size)
        self._install_scan(scan)

    def disk_signature(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return (0, 0)
        return (stat.st_size, stat.st_mtime_ns)

    def read_page(self, page_id: int) -> bytes | None:
        return self.overlay.get(page_id)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    def append_transaction(self, frames: Iterable[tuple[int, bytes | bytearray]], *, page_count: int) -> int:
        materialized = [(page_id, bytes(data)) for page_id, data in frames]
        if not materialized:
            return 0
        for page_id, data in materialized:
            if page_id < 0:
                raise StorageError(f"negative WAL page id {page_id}")
            if len(data) != self.page_size:
                raise StorageError(f"WAL frame must contain exactly {self.page_size} bytes, got {len(data)}")
        self._ensure_header()
        txid = self._next_txid
        try:
            with self.path.open("r+b") as file:
                file.seek(0, os.SEEK_END)
                for page_id, data in materialized:
                    checksum = zlib.crc32(data) & 0xFFFFFFFF
                    file.write(_RECORD.pack(FRAME_RECORD, txid, page_id, len(data), checksum))
                    file.write(data)
                file.write(_RECORD.pack(COMMIT_RECORD, txid, page_count, 0, len(materialized)))
                file.flush()
                os.fsync(file.fileno())
        except BaseException:
            try:
                scan = self._scan(self.path, expected_page_size=self.page_size)
                if scan.ignored_tail:
                    self._truncate_to(scan.last_committed_offset)
                self._install_scan(scan)
            except Exception:
                pass
            raise
        for page_id, data in materialized:
            self.overlay[page_id] = data
        self.page_count = page_count
        self.committed_transactions += 1
        self.committed_frames += len(materialized)
        self._next_txid += 1
        return txid

    def checkpoint_into(self, database_file: BinaryIO, *, page_count: int) -> int:
        if not self.overlay:
            return 0
        for page_id in sorted(self.overlay):
            database_file.seek(page_id * self.page_size)
            database_file.write(self.overlay[page_id])
        database_file.truncate(page_count * self.page_size)
        database_file.flush()
        os.fsync(database_file.fileno())
        copied = len(self.overlay)
        self.reset()
        return copied

    def reset(self) -> None:
        if not self.path.exists():
            self.overlay.clear()
            self.page_count = None
            self.committed_transactions = 0
            self.committed_frames = 0
            self._next_txid = 1
            return
        with self.path.open("w+b") as file:
            file.write(self._header_bytes(self.page_size))
            file.flush()
            os.fsync(file.fileno())
        self._fsync_directory(self.path.parent)
        self.overlay.clear()
        self.page_count = None
        self.committed_transactions = 0
        self.committed_frames = 0
        self._next_txid = 1

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        else:
            self._fsync_directory(self.path.parent)
        self.overlay.clear()
        self.page_count = None
        self.committed_transactions = 0
        self.committed_frames = 0
        self._next_txid = 1

    def _ensure_header(self) -> None:
        if self.path.exists():
            if self.path.stat().st_size < HEADER_SIZE:
                raise CorruptionError("WAL header is truncated")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w+b") as file:
            file.write(self._header_bytes(self.page_size))
            file.flush()
            os.fsync(file.fileno())
        self._fsync_directory(self.path.parent)

    def _truncate_to(self, size: int) -> None:
        with self.path.open("r+b") as file:
            file.truncate(size)
            file.flush()
            os.fsync(file.fileno())

    @classmethod
    def checkpoint_existing_into_database(
        cls,
        database_path: str | Path,
        database_file: BinaryIO,
        *,
        expected_page_size: int,
        database_page_count: int,
    ) -> bool:
        path = cls.path_for(database_path)
        if not path.exists():
            return False
        scan = cls._scan(path, expected_page_size=expected_page_size)
        if not scan.overlay:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            else:
                cls._fsync_directory(path.parent)
            return scan.ignored_tail
        logical_count = scan.page_count or database_page_count
        for page_id in sorted(scan.overlay):
            database_file.seek(page_id * expected_page_size)
            database_file.write(scan.overlay[page_id])
        database_file.truncate(logical_count * expected_page_size)
        database_file.flush()
        os.fsync(database_file.fileno())
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        cls._fsync_directory(path.parent)
        return True

    @classmethod
    def _scan(cls, path: Path, *, expected_page_size: int) -> WALScan:
        with path.open("rb") as file:
            header = file.read(HEADER_SIZE)
            if len(header) != HEADER_SIZE:
                raise CorruptionError("WAL header is truncated")
            magic, version, header_size, page_size, reserved = _HEADER.unpack(header)
            if magic != WAL_MAGIC:
                raise CorruptionError("invalid WAL magic")
            if version != WAL_VERSION:
                raise CorruptionError(f"unsupported WAL version {version}")
            if header_size != HEADER_SIZE:
                raise CorruptionError(f"unexpected WAL header size {header_size}")
            if page_size != expected_page_size:
                raise CorruptionError(f"WAL page size {page_size} != database page size {expected_page_size}")
            if reserved != b"\x00" * 8:
                raise CorruptionError("WAL reserved header bytes are non-zero")
            overlay: dict[int, bytes] = {}
            page_count: int | None = None
            committed_transactions = 0
            committed_frames = 0
            pending_txid: int | None = None
            pending: list[tuple[int, bytes]] = []
            last_committed_offset = HEADER_SIZE
            ignored_tail = False
            while True:
                raw = file.read(RECORD_SIZE)
                if not raw:
                    break
                if len(raw) != RECORD_SIZE:
                    ignored_tail = True
                    break
                kind, txid, arg, payload_len, aux = _RECORD.unpack(raw)
                if kind == FRAME_RECORD:
                    if payload_len != expected_page_size:
                        ignored_tail = True
                        break
                    payload = file.read(payload_len)
                    if len(payload) != payload_len:
                        ignored_tail = True
                        break
                    if (zlib.crc32(payload) & 0xFFFFFFFF) != aux:
                        ignored_tail = True
                        break
                    if pending_txid is None:
                        pending_txid = txid
                    if txid != pending_txid:
                        ignored_tail = True
                        break
                    pending.append((arg, payload))
                    continue
                if kind == COMMIT_RECORD:
                    if payload_len != 0 or pending_txid is None or txid != pending_txid:
                        ignored_tail = True
                        break
                    if aux != len(pending) or any(page_id >= arg for page_id, _payload in pending):
                        ignored_tail = True
                        break
                    for page_id, payload in pending:
                        overlay[page_id] = payload
                    page_count = arg
                    committed_transactions += 1
                    committed_frames += len(pending)
                    pending_txid = None
                    pending = []
                    last_committed_offset = file.tell()
                    continue
                ignored_tail = True
                break
            if pending:
                ignored_tail = True
        return WALScan(overlay, page_count, committed_transactions, committed_frames, ignored_tail, last_committed_offset)

    @staticmethod
    def _header_bytes(page_size: int) -> bytes:
        return _HEADER.pack(WAL_MAGIC, WAL_VERSION, HEADER_SIZE, page_size, b"\x00" * 8)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
