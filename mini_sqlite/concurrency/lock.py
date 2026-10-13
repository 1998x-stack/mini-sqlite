from __future__ import annotations

import itertools
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from mini_sqlite.concurrency.file_lock import FileLockSet
from mini_sqlite.errors import BusyError, JournalModeConflictError


class ConnectionLock(str, Enum):
    NONE = "none"
    SHARED = "shared"
    RESERVED = "reserved"
    EXCLUSIVE = "exclusive"
    WAL_WRITE = "wal-write"


@dataclass
class _DatabaseLockState:
    journal_mode: str
    connections: set[int] = field(default_factory=set)
    shared: set[int] = field(default_factory=set)
    reserved: int | None = None
    exclusive: int | None = None
    wal_writer: int | None = None
    liveness: dict[int, Callable[[], bool]] = field(default_factory=dict)
    file_locks: dict[int, FileLockSet] = field(default_factory=dict)
    opening_guards: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class Registration:
    connection_id: int
    first_connection: bool


class LockRegistry:
    """Connection lock manager with process-local state + POSIX flock backend.

    v0.9's in-process state machine remains useful for deterministic inspection
    and thread wakeups. v1.1 mirrors every lock transition into kernel `flock`
    sidecars, so independent Python processes now obey the same rollback/WAL
    conflict rules. OS locks, not lock-file existence, define liveness.
    """

    _condition = threading.Condition(threading.RLock())
    _states: dict[str, _DatabaseLockState] = {}
    _ids = itertools.count(1)

    @classmethod
    def register(
        cls,
        path: str | Path,
        journal_mode: str,
        *,
        timeout_ms: int = 0,
    ) -> Registration:
        key = cls._key(path)
        connection_id = next(cls._ids)

        # Decide whether EX probing could mean globally-first. Avoid probing when
        # our own process already has a live connection: its MODE-SH is expected.
        with cls._condition:
            existing = cls._states.get(key)
            if existing is not None:
                cls._prune_dead_locked(existing)
                if not existing.connections:
                    cls._states.pop(key, None)
                    existing = None
            if existing is not None and existing.journal_mode != journal_mode:
                raise JournalModeConflictError(
                    f"database already has live {existing.journal_mode!r} connections; "
                    f"cannot open {journal_mode!r} concurrently"
                )
            probe_global_first = existing is None

        file_lock = FileLockSet(path)
        try:
            global_first = file_lock.register_mode(
                journal_mode,
                timeout_ms=timeout_ms,
                probe_global_first=probe_global_first,
            )
        except BaseException:
            file_lock.close()
            raise

        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._states.get(key)
            if state is not None:
                cls._prune_dead_locked(state)
                if not state.connections:
                    cls._states.pop(key, None)
                    state = None
            if state is not None and state.journal_mode != journal_mode:
                file_lock.close()
                raise JournalModeConflictError(
                    f"database already has live {state.journal_mode!r} connections; "
                    f"cannot open {journal_mode!r} concurrently"
                )
            if state is None:
                state = _DatabaseLockState(journal_mode=journal_mode)
                cls._states[key] = state

            try:
                # In rollback mode Pager construction/recovery must not race an
                # existing EX writer. Hold a temporary SH reader guard until the
                # Database constructor finishes opening its Pager/runtime.
                if journal_mode == "rollback":
                    cls._wait_until(
                        lambda: state.exclusive is None,
                        deadline,
                        "database is busy while another local connection is writing",
                    )
                    file_lock.acquire_opening_reader_guard(timeout_ms=timeout_ms)
                    state.shared.add(connection_id)
                    state.opening_guards.add(connection_id)
                state.connections.add(connection_id)
                state.file_locks[connection_id] = file_lock
                return Registration(connection_id, global_first)
            except BaseException:
                state.shared.discard(connection_id)
                state.opening_guards.discard(connection_id)
                state.connections.discard(connection_id)
                state.file_locks.pop(connection_id, None)
                if not state.connections:
                    cls._states.pop(key, None)
                file_lock.close()
                raise

    @classmethod
    def finish_registration(cls, path: str | Path, connection_id: int) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            handle = cls._handle(state, connection_id)
            handle.finish_registration()
            if connection_id in state.opening_guards:
                state.opening_guards.discard(connection_id)
                state.shared.discard(connection_id)
            cls._condition.notify_all()

    @classmethod
    def bind_liveness(
        cls, path: str | Path, connection_id: int, callback: Callable[[], bool]
    ) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            state.liveness[connection_id] = callback

    @classmethod
    def unregister(cls, path: str | Path, connection_id: int) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._states.get(key)
            if state is None:
                return
            cls._release_all_locked(state, connection_id)
            state.connections.discard(connection_id)
            state.opening_guards.discard(connection_id)
            state.liveness.pop(connection_id, None)
            handle = state.file_locks.pop(connection_id, None)
            if handle is not None:
                handle.close()
            if not state.connections:
                cls._states.pop(key, None)
            cls._condition.notify_all()

    @classmethod
    def acquire_shared(
        cls,
        path: str | Path,
        connection_id: int,
        *,
        timeout_ms: int = 0,
    ) -> None:
        key = cls._key(path)
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if connection_id in state.shared:
                return
            if state.journal_mode == "rollback":
                cls._wait_until(
                    lambda: state.exclusive in (None, connection_id),
                    deadline,
                    "database is locked by an exclusive local writer",
                )
                cls._handle(state, connection_id).acquire_rollback_reader(
                    timeout_ms=timeout_ms
                )
            else:
                cls._handle(state, connection_id).acquire_wal_reader(
                    timeout_ms=timeout_ms
                )
            state.shared.add(connection_id)

    @classmethod
    def acquire_reserved(
        cls,
        path: str | Path,
        connection_id: int,
        *,
        timeout_ms: int = 0,
    ) -> None:
        key = cls._key(path)
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if state.journal_mode != "rollback":
                raise BusyError("RESERVED is only meaningful in rollback mode")
            cls._wait_until(
                lambda: state.reserved in (None, connection_id)
                and state.exclusive in (None, connection_id),
                deadline,
                "another local writer already owns the RESERVED lock",
            )
            cls._handle(state, connection_id).acquire_writer(
                timeout_ms=timeout_ms,
                message="database is busy: another process owns the writer lock",
            )
            state.reserved = connection_id

    @classmethod
    def acquire_exclusive(
        cls,
        path: str | Path,
        connection_id: int,
        *,
        timeout_ms: int = 0,
    ) -> None:
        key = cls._key(path)
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if state.journal_mode != "rollback":
                raise BusyError("EXCLUSIVE rollback lock requested in WAL mode")
            cls._wait_until(
                lambda: state.reserved in (None, connection_id)
                and state.exclusive in (None, connection_id)
                and not (state.shared - {connection_id}),
                deadline,
                "database is busy: local readers prevent EXCLUSIVE writer lock",
            )
            cls._handle(state, connection_id).acquire_reader_exclusive(
                timeout_ms=timeout_ms,
                message="database is busy: cross-process readers prevent EXCLUSIVE writer lock",
            )
            state.reserved = connection_id
            state.exclusive = connection_id

    @classmethod
    def acquire_wal_writer(
        cls,
        path: str | Path,
        connection_id: int,
        *,
        timeout_ms: int = 0,
    ) -> None:
        key = cls._key(path)
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if state.journal_mode != "wal":
                raise BusyError("WAL writer lock requested in rollback mode")
            cls._wait_until(
                lambda: state.wal_writer in (None, connection_id),
                deadline,
                "database is busy: another local WAL writer is active",
            )
            cls._handle(state, connection_id).acquire_writer(
                timeout_ms=timeout_ms,
                message="database is busy: another process owns the WAL writer lock",
            )
            state.wal_writer = connection_id

    @classmethod
    def acquire_checkpoint(
        cls,
        path: str | Path,
        connection_id: int,
        *,
        timeout_ms: int = 0,
    ) -> None:
        key = cls._key(path)
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if state.journal_mode != "wal":
                raise BusyError("checkpoint lock requested in rollback mode")
            cls._wait_until(
                lambda: state.wal_writer in (None, connection_id)
                and not (state.shared - {connection_id}),
                deadline,
                "checkpoint is busy: local WAL reader or writer",
            )
            handle = cls._handle(state, connection_id)
            acquired_writer_here = state.wal_writer != connection_id
            try:
                handle.acquire_writer(
                    timeout_ms=timeout_ms,
                    message="checkpoint is busy: another process owns the WAL writer lock",
                )
                handle.acquire_reader_exclusive(
                    timeout_ms=timeout_ms,
                    message="checkpoint is busy: cross-process WAL reader is active",
                )
                state.wal_writer = connection_id
            except BaseException:
                if acquired_writer_here:
                    handle.release_transaction_locks()
                raise

    @classmethod
    def downgrade_to_shared(cls, path: str | Path, connection_id: int) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            cls._handle(state, connection_id).downgrade_to_shared(
                journal_mode=state.journal_mode
            )
            if state.reserved == connection_id:
                state.reserved = None
            if state.exclusive == connection_id:
                state.exclusive = None
            if state.wal_writer == connection_id:
                state.wal_writer = None
            state.shared.add(connection_id)
            cls._condition.notify_all()

    @classmethod
    def release_all(cls, path: str | Path, connection_id: int) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._states.get(key)
            if state is None:
                return
            cls._release_all_locked(state, connection_id)
            cls._condition.notify_all()

    @classmethod
    def snapshot(cls, path: str | Path, connection_id: int) -> dict[str, object]:
        key = cls._key(path)
        with cls._condition:
            state = cls._require_state(key, connection_id)
            if state.exclusive == connection_id:
                mine = ConnectionLock.EXCLUSIVE.value
            elif state.reserved == connection_id:
                mine = ConnectionLock.RESERVED.value
            elif state.wal_writer == connection_id:
                mine = ConnectionLock.WAL_WRITE.value
            elif connection_id in state.shared:
                mine = ConnectionLock.SHARED.value
            else:
                mine = ConnectionLock.NONE.value
            result = {
                "journal_mode": state.journal_mode,
                "connection_id": connection_id,
                "my_lock": mine,
                "connections": len(state.connections),
                "shared_readers": len(state.shared),
                "reserved_holder": state.reserved,
                "exclusive_holder": state.exclusive,
                "wal_writer": state.wal_writer,
                "pid": os.getpid(),
            }
            result.update(cls._handle(state, connection_id).snapshot())
            return result

    @classmethod
    def _release_all_locked(cls, state: _DatabaseLockState, connection_id: int) -> None:
        handle = state.file_locks.get(connection_id)
        if handle is not None:
            handle.release_transaction_locks()
        state.shared.discard(connection_id)
        if state.reserved == connection_id:
            state.reserved = None
        if state.exclusive == connection_id:
            state.exclusive = None
        if state.wal_writer == connection_id:
            state.wal_writer = None

    @classmethod
    def _require_state(cls, key: str, connection_id: int) -> _DatabaseLockState:
        state = cls._states.get(key)
        if state is not None:
            cls._prune_dead_locked(state)
        if state is None or connection_id not in state.connections:
            raise BusyError("connection is not registered with the lock manager")
        return state

    @staticmethod
    def _handle(state: _DatabaseLockState, connection_id: int) -> FileLockSet:
        handle = state.file_locks.get(connection_id)
        if handle is None:
            raise BusyError("connection has no cross-process lock handle")
        return handle

    @classmethod
    def _prune_dead_locked(cls, state: _DatabaseLockState) -> None:
        dead: list[int] = []
        for connection_id in list(state.connections):
            callback = state.liveness.get(connection_id)
            if callback is None:
                continue
            try:
                alive = bool(callback())
            except Exception:
                alive = False
            if not alive:
                dead.append(connection_id)
        for connection_id in dead:
            cls._release_all_locked(state, connection_id)
            state.connections.discard(connection_id)
            state.opening_guards.discard(connection_id)
            state.liveness.pop(connection_id, None)
            handle = state.file_locks.pop(connection_id, None)
            if handle is not None:
                handle.close()
        if dead:
            cls._condition.notify_all()

    @classmethod
    def _wait_until(cls, predicate, deadline: float | None, message: str) -> None:
        while not predicate():
            if deadline is None:
                raise BusyError(message)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BusyError(f"{message} (busy timeout expired)")
            cls._condition.wait(timeout=remaining)

    @staticmethod
    def _deadline(timeout_ms: int) -> float | None:
        if timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be >= 0")
        if timeout_ms == 0:
            return None
        return time.monotonic() + timeout_ms / 1000.0

    @staticmethod
    def _key(path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())
