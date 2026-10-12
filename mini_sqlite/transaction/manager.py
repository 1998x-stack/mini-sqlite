from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from typing import Iterator

from mini_sqlite.errors import TransactionError
from mini_sqlite.storage.pager import Pager


class TransactionState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    COMMITTING = "committing"
    ROLLING_BACK = "rolling-back"


class TransactionManager:
    """Connection-level transaction state around the Pager durability API."""

    def __init__(self, pager: Pager):
        self.pager = pager
        self.state = TransactionState.IDLE

    @property
    def active(self) -> bool:
        return self.state == TransactionState.ACTIVE

    def begin(self) -> None:
        if self.state != TransactionState.IDLE:
            raise TransactionError("cannot start a transaction within a transaction")
        self.pager.begin_transaction()
        self.state = TransactionState.ACTIVE

    def commit(self) -> None:
        if self.state != TransactionState.ACTIVE:
            raise TransactionError("cannot COMMIT: no transaction is active")
        self.state = TransactionState.COMMITTING
        try:
            self.pager.commit_transaction()
        except Exception:
            # If commit fails before journal deletion, leave recovery possible.
            self.state = TransactionState.ACTIVE
            raise
        else:
            self.state = TransactionState.IDLE

    def rollback(self) -> None:
        if self.state != TransactionState.ACTIVE:
            raise TransactionError("cannot ROLLBACK: no transaction is active")
        self.state = TransactionState.ROLLING_BACK
        try:
            self.pager.rollback_transaction()
        finally:
            self.state = TransactionState.IDLE

    @contextmanager
    def scope(self) -> Iterator[None]:
        self.begin()
        try:
            yield
        except BaseException:
            if self.active:
                self.rollback()
            raise
        else:
            self.commit()
