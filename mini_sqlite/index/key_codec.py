from __future__ import annotations

from collections.abc import Iterable

from mini_sqlite.catalog.schema import ColumnType
from mini_sqlite.errors import SchemaError


class KeyCodec:
    """Order-preserving scalar/tuple encoding for secondary-index keys."""

    NULL_TAG = b"\x00"
    INTEGER_TAG = b"\x10"
    TEXT_TAG = b"\x20"
    _I64_BIAS = 1 << 63

    @classmethod
    def encode_value(cls, value: object, column_type: ColumnType) -> bytes:
        if value is None:
            return cls.NULL_TAG
        if column_type == ColumnType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise SchemaError("INTEGER index lookup requires an integer literal")
            return cls.INTEGER_TAG + cls._encode_i64(value)
        if column_type == ColumnType.TEXT:
            if not isinstance(value, str):
                raise SchemaError("TEXT index lookup requires a string literal")
            raw = value.encode("utf-8")
            escaped = raw.replace(b"\x00", b"\x00\xff")
            return cls.TEXT_TAG + escaped + b"\x00\x00"
        raise SchemaError(f"unsupported indexed column type: {column_type}")

    @classmethod
    def encode_values(
        cls, values: Iterable[object], column_types: Iterable[ColumnType]
    ) -> bytes:
        values_tuple = tuple(values)
        types_tuple = tuple(column_types)
        if len(values_tuple) != len(types_tuple):
            raise SchemaError("index tuple value/type arity mismatch")
        return b"".join(
            cls.encode_value(value, column_type)
            for value, column_type in zip(values_tuple, types_tuple)
        )

    @classmethod
    def composite_key(cls, value: object, column_type: ColumnType, rowid: int) -> bytes:
        """Historical single-column helper."""
        return cls.encode_value(value, column_type) + cls.encode_rowid(rowid)

    @classmethod
    def index_key(
        cls,
        values: Iterable[object],
        column_types: Iterable[ColumnType],
        rowid: int,
    ) -> bytes:
        return cls.encode_values(values, column_types) + cls.encode_rowid(rowid)

    @staticmethod
    def prefix_successor(prefix: bytes) -> bytes | None:
        """Smallest byte string strictly above every key beginning with prefix."""
        data = bytearray(prefix)
        for i in range(len(data) - 1, -1, -1):
            if data[i] != 0xFF:
                data[i] += 1
                return bytes(data[: i + 1])
        return None

    @classmethod
    def encode_rowid(cls, rowid: int) -> bytes:
        if not isinstance(rowid, int) or isinstance(rowid, bool):
            raise SchemaError("rowid must be an integer")
        return cls._encode_i64(rowid)

    @classmethod
    def decode_rowid(cls, composite_key: bytes) -> int:
        if len(composite_key) < 8:
            raise SchemaError("secondary-index key is too short to contain a rowid")
        biased = int.from_bytes(composite_key[-8:], "big", signed=False)
        return biased - cls._I64_BIAS

    @classmethod
    def _encode_i64(cls, value: int) -> bytes:
        if value < -(1 << 63) or value >= (1 << 63):
            raise SchemaError("INTEGER value is outside signed 64-bit range")
        return (value + cls._I64_BIAS).to_bytes(8, "big", signed=False)
