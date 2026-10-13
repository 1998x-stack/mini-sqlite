from __future__ import annotations

import errno
import os
import time
from dataclasses import dataclass
from pathlib import Path

from mini_sqlite.errors import BusyError, CrossProcessLockError, JournalModeConflictError

try:  # POSIX backend used by macOS and Linux.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX platforms
    fcntl = None  # type: ignore[assignment]


@dataclass(frozen=True)
class LockPaths:
    mode: Path
    pending: Path
    readers: Path
    writer: Path

    def all(self) -> tuple[Path, ...]:
        return (self.mode, self.pending, self.readers, self.writer)


def lock_paths(path: str | Path) -> LockPaths:
    db = Path(path).expanduser().resolve()
    return LockPaths(
        mode=db.with_name(db.name + "-lock-mode"),
        pending=db.with_name(db.name + "-lock-pending"),
        readers=db.with_name(db.name + "-lock-readers"),
        writer=db.with_name(db.name + "-lock-writer"),
    )


class FileLockSet:
    """Per-connection POSIX flock handles for one database path.

    Four tiny sidecars separate concerns:

    * mode: all live connections hold SH; the globally first opener holds EX
      through recovery/bootstrap, writes rollback/wal, then downgrades to SH;
    * pending: rollback writers/checkpoints hold EX while draining readers so
      new readers cannot starve them;
    * readers: normal readers hold SH, rollback EX writers/checkpoint hold EX;
    * writer: one RESERVED/WAL writer at a time holds EX.

    Lock-file presence is never a liveness signal. The kernel lock is the
    signal, and it vanishes automatically when a process exits.
    """

    backend = "posix-flock"

    def __init__(self, path: str | Path):
        if fcntl is None:  # pragma: no cover - non-POSIX only
            raise CrossProcessLockError(
                "v1.1 cross-process locking requires POSIX flock (macOS/Linux)"
            )
        self.db_path = Path(path).expanduser().resolve()
        self.paths = lock_paths(self.db_path)
        self._mode_fd = self._open(self.paths.mode)
        self._pending_fd = self._open(self.paths.pending)
        self._readers_fd = self._open(self.paths.readers)
        self._writer_fd = self._open(self.paths.writer)
        self._mode_lock: str | None = None
        self._pending_lock: str | None = None
        self._readers_lock: str | None = None
        self._writer_lock: str | None = None
        self._opening_reader_guard = False
        self._closed = False

    @staticmethod
    def _open(path: Path) -> int:
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        return os.open(path, flags, 0o600)

    @staticmethod
    def _deadline(timeout_ms: int) -> float | None:
        if timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be >= 0")
        if timeout_ms == 0:
            return None
        return time.monotonic() + timeout_ms / 1000.0

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - time.monotonic()

    def _lock(self, fd: int, kind: str, deadline: float | None, message: str) -> None:
        op = fcntl.LOCK_SH if kind == "shared" else fcntl.LOCK_EX
        while True:
            try:
                fcntl.flock(fd, op | fcntl.LOCK_NB)
                return
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                remaining = self._remaining(deadline)
                if remaining is None:
                    raise BusyError(message) from None
                if remaining <= 0:
                    raise BusyError(f"{message} (busy timeout expired)") from None
                time.sleep(min(0.005, remaining))

    def _try_exclusive(self, fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise

    @staticmethod
    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

    def _write_mode(self, mode: str) -> None:
        data = (mode + "\n").encode("ascii")
        os.lseek(self._mode_fd, 0, os.SEEK_SET)
        os.ftruncate(self._mode_fd, 0)
        os.write(self._mode_fd, data)
        os.fsync(self._mode_fd)

    def _read_mode(self) -> str:
        os.lseek(self._mode_fd, 0, os.SEEK_SET)
        return os.read(self._mode_fd, 32).decode("ascii", errors="replace").strip()

    def register_mode(
        self,
        journal_mode: str,
        *,
        timeout_ms: int,
        probe_global_first: bool,
    ) -> bool:
        """Join the cross-process mode domain.

        Returns True only when no other process/local file description currently
        holds the mode file and this connection therefore owns crash recovery.
        The first opener deliberately keeps MODE-EX until finish_registration(),
        serializing hot-journal/WAL recovery and empty-database bootstrap.
        """
        deadline = self._deadline(timeout_ms)
        if probe_global_first and self._try_exclusive(self._mode_fd):
            self._mode_lock = "exclusive"
            self._write_mode(journal_mode)
            return True

        self._lock(
            self._mode_fd,
            "shared",
            deadline,
            "database is busy while another process is opening or recovering it",
        )
        self._mode_lock = "shared"
        active_mode = self._read_mode()
        if active_mode and active_mode != journal_mode:
            self.close()
            raise JournalModeConflictError(
                f"database already has live {active_mode!r} process(es); "
                f"cannot open {journal_mode!r} concurrently"
            )
        if not active_mode:
            # Defensive fallback for a stale/empty sidecar created by an older
            # experiment. A live SH holder with empty content is not a valid mode.
            self.close()
            raise CrossProcessLockError("live database mode lock has no mode metadata")
        return False

    def acquire_opening_reader_guard(self, *, timeout_ms: int) -> None:
        self.acquire_rollback_reader(timeout_ms=timeout_ms)
        self._opening_reader_guard = True

    def finish_registration(self) -> None:
        if self._opening_reader_guard:
            self._release_readers()
            self._opening_reader_guard = False
        if self._mode_lock == "exclusive":
            # Downgrading is conflict-free: EX already owns the mode domain.
            fcntl.flock(self._mode_fd, fcntl.LOCK_SH)
            self._mode_lock = "shared"

    def acquire_rollback_reader(self, *, timeout_ms: int) -> None:
        if self._readers_lock == "shared":
            return
        deadline = self._deadline(timeout_ms)
        self._lock(
            self._pending_fd,
            "shared",
            deadline,
            "database is busy: a rollback writer is pending",
        )
        self._pending_lock = "shared"
        try:
            self._lock(
                self._readers_fd,
                "shared",
                deadline,
                "database is locked by an exclusive rollback writer",
            )
            self._readers_lock = "shared"
        finally:
            self._release_pending()

    def acquire_wal_reader(self, *, timeout_ms: int) -> None:
        if self._readers_lock == "shared":
            return
        self._lock(
            self._readers_fd,
            "shared",
            self._deadline(timeout_ms),
            "database readers are blocked by checkpoint",
        )
        self._readers_lock = "shared"

    def acquire_writer(self, *, timeout_ms: int, message: str) -> None:
        if self._writer_lock == "exclusive":
            return
        self._lock(self._writer_fd, "exclusive", self._deadline(timeout_ms), message)
        self._writer_lock = "exclusive"

    def acquire_reader_exclusive(self, *, timeout_ms: int, message: str) -> None:
        """Drain readers while preventing new readers from entering.

        A rollback writer already owns WRITER-EX before this call. PENDING-EX
        closes the reader turnstile. If this connection itself held READERS-SH
        (explicit read -> write upgrade), release that SH only after the turnstile
        closes; on timeout restore it before reopening the turnstile.
        """
        if self._readers_lock == "exclusive":
            return
        deadline = self._deadline(timeout_ms)
        self._lock(
            self._pending_fd,
            "exclusive",
            deadline,
            "database is busy: another writer/checkpoint is pending",
        )
        self._pending_lock = "exclusive"
        had_shared = self._readers_lock == "shared"
        if had_shared:
            self._release_readers()
        try:
            self._lock(self._readers_fd, "exclusive", deadline, message)
            self._readers_lock = "exclusive"
        except BaseException:
            if had_shared:
                # Existing readers are compatible with SH, and PENDING-EX stops
                # newcomers while we restore our transaction snapshot lock.
                self._lock(
                    self._readers_fd,
                    "shared",
                    deadline,
                    "failed to restore shared reader lock after write-upgrade timeout",
                )
                self._readers_lock = "shared"
            self._release_pending()
            raise

    def downgrade_to_shared(self, *, journal_mode: str) -> None:
        if journal_mode == "rollback" and self._readers_lock == "exclusive":
            fcntl.flock(self._readers_fd, fcntl.LOCK_SH)
            self._readers_lock = "shared"
        self._release_pending()
        self._release_writer()

    def release_transaction_locks(self) -> None:
        self._release_readers()
        self._release_pending()
        self._release_writer()

    def _release_readers(self) -> None:
        if self._readers_lock is not None:
            self._unlock(self._readers_fd)
            self._readers_lock = None

    def _release_pending(self) -> None:
        if self._pending_lock is not None:
            self._unlock(self._pending_fd)
            self._pending_lock = None

    def _release_writer(self) -> None:
        if self._writer_lock is not None:
            self._unlock(self._writer_fd)
            self._writer_lock = None

    def snapshot(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "pid": os.getpid(),
            "mode_lock": self._mode_lock,
            "pending_lock": self._pending_lock,
            "readers_lock": self._readers_lock,
            "writer_lock": self._writer_lock,
            "lock_files": tuple(str(p) for p in self.paths.all()),
        }

    def close(self) -> None:
        if self._closed:
            return
        self.release_transaction_locks()
        if self._mode_lock is not None:
            self._unlock(self._mode_fd)
            self._mode_lock = None
        for fd in (self._mode_fd, self._pending_fd, self._readers_fd, self._writer_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        self._closed = True
