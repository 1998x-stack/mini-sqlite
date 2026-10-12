from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from typing import BinaryIO, Iterator

from mini_sqlite.errors import CorruptionError, StorageError

JOURNAL_MAGIC = b"MSQLJNL2"
JOURNAL_VERSION = 1
_HEADER = struct.Struct("<8sHHIQ8s")
_ENTRY_HEADER = struct.Struct("<QII")  # page_id, crc32, reserved
HEADER_SIZE = _HEADER.size


class RollbackJournal:
    """Physical before-image rollback journal.

    The journal records each pre-existing page at most once, before that page's
    first transaction-local modification. Newly allocated pages need no image:
    recovery truncates the database back to ``original_page_count``.

    Commit protocol:
      1. fsync journal
      2. write + fsync database pages
      3. delete journal (the commit point)

    If the process dies before step 3, startup treats the remaining journal as
    hot and restores the old database state.
    """

    def __init__(
        self,
        path: Path,
        file: BinaryIO,
        *,
        page_size: int,
        original_page_count: int,
    ) -> None:
        self.path = path
        self._file = file
        self.page_size = page_size
        self.original_page_count = original_page_count
        self._closed = False

    @classmethod
    def create(
        cls, database_path: str | Path, *, page_size: int, original_page_count: int
    ) -> "RollbackJournal":
        path = cls.path_for(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file = path.open("w+b")
        header = _HEADER.pack(
            JOURNAL_MAGIC,
            JOURNAL_VERSION,
            HEADER_SIZE,
            page_size,
            original_page_count,
            b"\x00" * 8,
        )
        file.write(header)
        file.flush()
        os.fsync(file.fileno())
        cls._fsync_directory(path.parent)
        return cls(
            path,
            file,
            page_size=page_size,
            original_page_count=original_page_count,
        )

    @staticmethod
    def path_for(database_path: str | Path) -> Path:
        db = Path(database_path)
        return db.with_name(db.name + "-journal")

    def append_before_image(self, page_id: int, data: bytes | bytearray) -> None:
        if self._closed:
            raise StorageError("rollback journal is closed")
        if len(data) != self.page_size:
            raise StorageError(
                f"journal image must be {self.page_size} bytes, got {len(data)}"
            )
        payload = bytes(data)
        checksum = zlib.crc32(payload) & 0xFFFFFFFF
        self._file.seek(0, os.SEEK_END)
        self._file.write(_ENTRY_HEADER.pack(page_id, checksum, 0))
        self._file.write(payload)

    def sync(self) -> None:
        if self._closed:
            return
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True

    def delete(self) -> None:
        self.close()
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory(self.path.parent)

    def restore_into(self, database_file: BinaryIO) -> None:
        """Restore every complete, validated before-image then truncate DB."""
        self.sync()
        for page_id, image in self._iter_entries_from_path(self.path, self.page_size):
            if page_id >= self.original_page_count:
                raise CorruptionError(
                    f"journal page {page_id} exceeds original page count "
                    f"{self.original_page_count}"
                )
            database_file.seek(page_id * self.page_size)
            database_file.write(image)
        database_file.truncate(self.original_page_count * self.page_size)
        database_file.flush()
        os.fsync(database_file.fileno())

    @classmethod
    def recover_if_hot(
        cls, database_path: str | Path, database_file: BinaryIO, *, expected_page_size: int
    ) -> bool:
        path = cls.path_for(database_path)
        if not path.exists():
            return False

        page_size, original_page_count = cls._read_header(path)
        if page_size != expected_page_size:
            raise CorruptionError(
                f"journal page size {page_size} != expected {expected_page_size}"
            )

        for page_id, image in cls._iter_entries_from_path(path, page_size):
            if page_id >= original_page_count:
                raise CorruptionError(
                    f"journal page {page_id} exceeds original page count {original_page_count}"
                )
            database_file.seek(page_id * page_size)
            database_file.write(image)

        database_file.truncate(original_page_count * page_size)
        database_file.flush()
        os.fsync(database_file.fileno())
        path.unlink()
        cls._fsync_directory(path.parent)
        return True

    @classmethod
    def _read_header(cls, path: Path) -> tuple[int, int]:
        with path.open("rb") as f:
            raw = f.read(HEADER_SIZE)
        if len(raw) != HEADER_SIZE:
            raise CorruptionError("truncated rollback journal header")
        magic, version, header_size, page_size, original_page_count, _ = _HEADER.unpack(raw)
        if magic != JOURNAL_MAGIC:
            raise CorruptionError("invalid rollback journal magic")
        if version != JOURNAL_VERSION:
            raise CorruptionError(f"unsupported rollback journal version {version}")
        if header_size != HEADER_SIZE:
            raise CorruptionError(f"invalid rollback journal header size {header_size}")
        if page_size <= 0:
            raise CorruptionError("invalid rollback journal page size")
        return page_size, original_page_count

    @classmethod
    def _iter_entries_from_path(
        cls, path: Path, page_size: int
    ) -> Iterator[tuple[int, bytes]]:
        with path.open("rb") as f:
            f.seek(HEADER_SIZE)
            while True:
                raw_header = f.read(_ENTRY_HEADER.size)
                if not raw_header:
                    return
                if len(raw_header) != _ENTRY_HEADER.size:
                    # A torn trailing journal write is safe to ignore because the
                    # database page could not be flushed until journal fsync.
                    return
                page_id, expected_crc, _ = _ENTRY_HEADER.unpack(raw_header)
                image = f.read(page_size)
                if len(image) != page_size:
                    return
                actual_crc = zlib.crc32(image) & 0xFFFFFFFF
                if actual_crc != expected_crc:
                    raise CorruptionError(
                        f"rollback journal checksum mismatch for page {page_id}"
                    )
                yield page_id, image

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        # Directory fsync makes journal creation/deletion durable on POSIX.
        if os.name != "posix":
            return
        flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
        try:
            fd = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
