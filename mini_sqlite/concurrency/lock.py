from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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


@dataclass(frozen=True)
class Registration:
    connection_id: int
    first_connection: bool


class LockRegistry:
    """Process-local database lock registry used by v0.9.

    The registry models SQLite-style connection conflicts while deliberately
    remaining small enough to read. It is process-local: cross-process OS locks
    are a v1.x concern. Every live Database object registered for the same
    canonical path shares one state machine.
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
        deadline = cls._deadline(timeout_ms)
        with cls._condition:
            state = cls._states.get(key)
            if state is not None:
                cls._prune_dead_locked(state)
                if not state.connections:
                    cls._states.pop(key, None)
                    state = None
            if state is not None and state.journal_mode != journal_mode:
                raise JournalModeConflictError(
                    f"database already has live {state.journal_mode!r} connections; "
                    f"cannot open {journal_mode!r} concurrently"
                )
            first = state is None
            if state is None:
                state = _DatabaseLockState(journal_mode=journal_mode)
                cls._states[key] = state
            # Rollback writers may have uncommitted bytes in the main DB, so a
            # new Pager must not open until EXCLUSIVE ends. WAL writers append to
            # a sidecar; a new reader may safely scan only its committed prefix.
            if journal_mode == "rollback":
                cls._wait_until(
                    lambda: state.exclusive is None,
                    deadline,
                    "database is busy while another connection is writing",
                )
            state.connections.add(connection_id)
            return Registration(connection_id, first)

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
            state.liveness.pop(connection_id, None)
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
            if state.journal_mode == "rollback":
                cls._wait_until(
                    lambda: state.exclusive in (None, connection_id),
                    deadline,
                    "database is locked by an exclusive writer",
                )
            # WAL readers intentionally coexist with the single writer.
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
                "another writer already owns the RESERVED lock",
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
                "database is busy: readers prevent EXCLUSIVE writer lock",
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
                "database is busy: another WAL writer is active",
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
        """Acquire the WAL maintenance lock used by checkpoint.

        Checkpoint changes the main database file, so explicit WAL snapshots must
        finish first; otherwise a reader could combine an old WAL overlay with
        newly checkpointed main-file pages.
        """
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
                "checkpoint is busy: active WAL reader or writer",
            )
            state.wal_writer = connection_id

    @classmethod
    def downgrade_to_shared(cls, path: str | Path, connection_id: int) -> None:
        key = cls._key(path)
        with cls._condition:
            state = cls._require_state(key, connection_id)
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
            return {
                "journal_mode": state.journal_mode,
                "connection_id": connection_id,
                "my_lock": mine,
                "connections": len(state.connections),
                "shared_readers": len(state.shared),
                "reserved_holder": state.reserved,
                "exclusive_holder": state.exclusive,
                "wal_writer": state.wal_writer,
            }

    @classmethod
    def _release_all_locked(cls, state: _DatabaseLockState, connection_id: int) -> None:
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
            state.liveness.pop(connection_id, None)
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
