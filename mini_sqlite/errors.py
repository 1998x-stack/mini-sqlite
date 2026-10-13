class MiniSQLiteError(Exception):
    """Base exception for the project."""


class ParseError(MiniSQLiteError):
    pass


class SchemaError(MiniSQLiteError):
    pass


class StorageError(MiniSQLiteError):
    pass


class BufferPoolFullError(StorageError):
    """No buffer frame can be evicted without violating pin/durability rules."""

    pass


class TransactionError(MiniSQLiteError):
    pass


class DuplicateKeyError(MiniSQLiteError):
    pass


class NotFoundError(MiniSQLiteError):
    pass


class CorruptionError(MiniSQLiteError):
    pass
