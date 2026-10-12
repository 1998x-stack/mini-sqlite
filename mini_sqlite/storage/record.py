from __future__ import annotations

import struct
from typing import Any, Iterable

from mini_sqlite.errors import CorruptionError, SchemaError

TYPE_NULL = 0
TYPE_INTEGER = 1
TYPE_TEXT = 2

_U16 = struct.Struct("<H")
_I64 = struct.Struct("<q")


class RecordCodec:
    """A compact typed row codec.

    Format:
        u16 column_count
        repeated descriptors: u8 type, u32 payload_length
        payload bytes concatenated

    It is intentionally self-describing so schema evolution experiments can be
    added later without changing page or B+Tree formats.
    """

    @staticmethod
    def encode(values: Iterable[Any]) -> bytes:
        vals = list(values)
        header = bytearray(_U16.pack(len(vals)))
        payload = bytearray()

        for value in vals:
            if value is None:
                header += struct.pack("<BI", TYPE_NULL, 0)
            elif isinstance(value, bool):
                header += struct.pack("<BI", TYPE_INTEGER, 8)
                payload += _I64.pack(int(value))
            elif isinstance(value, int):
                header += struct.pack("<BI", TYPE_INTEGER, 8)
                payload += _I64.pack(value)
            elif isinstance(value, str):
                raw = value.encode("utf-8")
                header += struct.pack("<BI", TYPE_TEXT, len(raw))
                payload += raw
            else:
                raise SchemaError(f"unsupported value type: {type(value).__name__}")
        return bytes(header + payload)

    @staticmethod
    def decode(raw: bytes | bytearray) -> tuple[Any, ...]:
        if len(raw) < 2:
            raise CorruptionError("record missing column count")
        (count,) = _U16.unpack_from(raw, 0)
        descriptor_size = count * 5
        payload_start = 2 + descriptor_size
        if payload_start > len(raw):
            raise CorruptionError("record descriptors exceed payload")

        descriptors: list[tuple[int, int]] = []
        off = 2
        for _ in range(count):
            type_tag, length = struct.unpack_from("<BI", raw, off)
            descriptors.append((type_tag, length))
            off += 5

        result: list[Any] = []
        cursor = payload_start
        for type_tag, length in descriptors:
            end = cursor + length
            if end > len(raw):
                raise CorruptionError("record payload truncated")
            chunk = raw[cursor:end]
            cursor = end
            if type_tag == TYPE_NULL:
                if length != 0:
                    raise CorruptionError("NULL must have zero payload")
                result.append(None)
            elif type_tag == TYPE_INTEGER:
                if length != 8:
                    raise CorruptionError("INTEGER payload must be 8 bytes")
                result.append(_I64.unpack(chunk)[0])
            elif type_tag == TYPE_TEXT:
                result.append(bytes(chunk).decode("utf-8"))
            else:
                raise CorruptionError(f"unknown record type tag {type_tag}")
        return tuple(result)
