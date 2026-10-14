from __future__ import annotations

from collections.abc import Callable, Iterable

from mini_sqlite.catalog.schema import IndexSchema, TableSchema
from mini_sqlite.index.btree import ByteKeyBTree
from mini_sqlite.index.key_codec import KeyCodec
from mini_sqlite.storage.pager import Pager


class SecondaryIndex:
    """Typed row-level wrapper around the ordered byte-key index B+Tree."""

    def __init__(
        self,
        pager: Pager,
        table: TableSchema,
        schema: IndexSchema,
        *,
        on_root_change: Callable[[int], None] | None = None,
    ):
        self.pager = pager
        self.table = table
        self.schema = schema
        self.column_indexes = tuple(table.column_index(name) for name in schema.columns)
        self.column_types = tuple(table.columns[i].type for i in self.column_indexes)
        self.tree = ByteKeyBTree(
            pager,
            schema.root_page,
            on_root_change=on_root_change,
        )

    @classmethod
    def create(
        cls,
        pager: Pager,
        table: TableSchema,
        schema: IndexSchema,
        rows: Iterable[tuple[int, tuple[object, ...]]],
        *,
        on_root_change: Callable[[int], None] | None = None,
    ) -> "SecondaryIndex":
        tree = ByteKeyBTree.create(pager)
        schema.root_page = tree.root_page
        index = cls(pager, table, schema, on_root_change=on_root_change)
        for rowid, values in rows:
            index.insert(values, rowid)
        schema.root_page = index.tree.root_page
        return index

    def _values_for_row(self, values: tuple[object, ...]) -> tuple[object, ...]:
        return tuple(values[i] for i in self.column_indexes)

    def insert(self, values: tuple[object, ...], rowid: int) -> None:
        key = KeyCodec.index_key(
            self._values_for_row(values), self.column_types, rowid
        )
        self.tree.insert(key, KeyCodec.encode_rowid(rowid))

    def delete(self, values: tuple[object, ...], rowid: int) -> bool:
        key = KeyCodec.index_key(
            self._values_for_row(values), self.column_types, rowid
        )
        return self.tree.delete(key)

    def lookup(self, value: object) -> list[int]:
        """Historical leftmost-column equality lookup."""
        return self.lookup_prefix((value,))

    def lookup_prefix(self, values: tuple[object, ...]) -> list[int]:
        if len(values) > len(self.column_types):
            return []
        prefix = KeyCodec.encode_values(values, self.column_types[: len(values)])
        return [
            KeyCodec.decode_rowid(key)
            for key, _stored_rowid in self.tree.scan_prefix(prefix)
        ]

    def lookup_range(
        self,
        *,
        equality_values: tuple[object, ...] = (),
        lower: object | None = None,
        lower_inclusive: bool = True,
        upper: object | None = None,
        upper_inclusive: bool = True,
        has_lower: bool = False,
        has_upper: bool = False,
    ) -> list[int]:
        """Scan an index prefix plus an optional range on the next key column."""
        prefix_len = len(equality_values)
        if prefix_len > len(self.column_types):
            return []
        prefix = KeyCodec.encode_values(
            equality_values, self.column_types[:prefix_len]
        )

        # Equality-only prefix scan. This covers full composite equality and the
        # SQL left-prefix rule (for example INDEX(a,b) with WHERE a=1).
        if not has_lower and not has_upper:
            return [
                KeyCodec.decode_rowid(key)
                for key, _ in self.tree.scan_prefix(prefix)
            ]

        if prefix_len >= len(self.column_types):
            return []
        range_type = self.column_types[prefix_len]

        lower_key: bytes | None
        upper_key: bytes | None
        if has_lower:
            encoded = prefix + KeyCodec.encode_value(lower, range_type)
            lower_key = encoded if lower_inclusive else KeyCodec.prefix_successor(encoded)
            if lower_key is None:
                return []
        else:
            # Ordered SQL comparisons never match NULL. A raw prefix would also
            # include the NULL_TAG run, so begin at the current column's type tag.
            tag = (
                KeyCodec.INTEGER_TAG
                if range_type.value == "INTEGER"
                else KeyCodec.TEXT_TAG
            )
            lower_key = prefix + tag

        if has_upper:
            encoded = prefix + KeyCodec.encode_value(upper, range_type)
            upper_key = (
                KeyCodec.prefix_successor(encoded) if upper_inclusive else encoded
            )
        else:
            upper_key = KeyCodec.prefix_successor(prefix) if prefix else None

        return [
            KeyCodec.decode_rowid(key)
            for key, _ in self.tree.scan_range(lower_key, upper_key)
        ]
