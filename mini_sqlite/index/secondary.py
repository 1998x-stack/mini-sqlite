from __future__ import annotations

from collections.abc import Callable, Iterable

from mini_sqlite.catalog.schema import IndexSchema, TableSchema
from mini_sqlite.index.btree import ByteKeyBTree
from mini_sqlite.index.key_codec import KeyCodec
from mini_sqlite.storage.pager import Pager


class SecondaryIndex:
    """Typed row-level wrapper around the byte-key index B+Tree."""

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
        self.column_index = table.column_index(schema.column)
        self.column_type = table.columns[self.column_index].type
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

    def insert(self, values: tuple[object, ...], rowid: int) -> None:
        value = values[self.column_index]
        key = KeyCodec.composite_key(value, self.column_type, rowid)
        self.tree.insert(key, KeyCodec.encode_rowid(rowid))

    def delete(self, values: tuple[object, ...], rowid: int) -> bool:
        value = values[self.column_index]
        key = KeyCodec.composite_key(value, self.column_type, rowid)
        return self.tree.delete(key)

    def lookup(self, value: object) -> list[int]:
        prefix = KeyCodec.encode_value(value, self.column_type)
        return [
            KeyCodec.decode_rowid(key)
            for key, _stored_rowid in self.tree.scan_prefix(prefix)
        ]
