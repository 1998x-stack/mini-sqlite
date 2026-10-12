from __future__ import annotations

from collections.abc import Callable

from mini_sqlite.btree import BTree
from mini_sqlite.catalog.schema import Column, ColumnType, TableSchema
from mini_sqlite.errors import SchemaError
from mini_sqlite.storage.meta import DatabaseMeta
from mini_sqlite.storage.pager import Pager

MetaUpdate = Callable[[DatabaseMeta], None]


class Catalog:
    """Schema catalog persisted in its own B+Tree.

    Catalog entries use monotonically increasing table_id keys. Name lookup is a
    small scan in v0.1; v0.3 can add a catalog name index without changing the
    TableSchema representation.
    """

    def __init__(self, pager: Pager, meta: DatabaseMeta, persist_meta: MetaUpdate):
        self.pager = pager
        self.meta = meta
        self._persist_meta = persist_meta
        self.tree = BTree(
            pager,
            meta.catalog_root_page,
            on_root_change=self._catalog_root_changed,
        )

    def _catalog_root_changed(self, root_page: int) -> None:
        self.meta.catalog_root_page = root_page
        self._persist_meta(self.meta)

    def list_tables(self) -> list[TableSchema]:
        return [TableSchema.decode(raw) for _, raw in self.tree.scan()]

    def get_table(self, name: str) -> TableSchema:
        lowered = name.lower()
        for schema in self.list_tables():
            if schema.name.lower() == lowered:
                return schema
        raise SchemaError(f"no such table: {name}")

    def create_table(self, name: str, columns: list[Column]) -> TableSchema:
        try:
            self.get_table(name)
        except SchemaError:
            pass
        else:
            raise SchemaError(f"table already exists: {name}")

        primary_keys = [c for c in columns if c.primary_key]
        if len(primary_keys) != 1:
            raise SchemaError("v0.1 requires exactly one PRIMARY KEY")
        if primary_keys[0].type != ColumnType.INTEGER:
            raise SchemaError("v0.1 PRIMARY KEY must be INTEGER")

        table_tree = BTree.create(self.pager)
        table_id = self.meta.next_table_id
        self.meta.next_table_id += 1
        schema = TableSchema(table_id, name, table_tree.root_page, columns)
        self.tree.insert(table_id, schema.encode())
        self._persist_meta(self.meta)
        return schema

    def update_root_page(self, table_id: int, root_page: int) -> None:
        raw = self.tree.search(table_id)
        if raw is None:
            raise SchemaError(f"catalog entry {table_id} missing")
        schema = TableSchema.decode(raw)
        schema.root_page = root_page
        # BTree v0.1 intentionally has no general update; delete + insert is
        # enough for tiny catalog rows and exercises persistent mutation.
        self.tree.delete(table_id)
        self.tree.insert(table_id, schema.encode())
