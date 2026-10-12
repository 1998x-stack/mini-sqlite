from __future__ import annotations

from collections.abc import Callable

from mini_sqlite.btree import BTree
from mini_sqlite.catalog.schema import Column, ColumnType, IndexSchema, TableSchema
from mini_sqlite.errors import SchemaError
from mini_sqlite.index.secondary import SecondaryIndex
from mini_sqlite.storage import RecordCodec
from mini_sqlite.storage.meta import DatabaseMeta
from mini_sqlite.storage.pager import Pager

MetaUpdate = Callable[[DatabaseMeta], None]


class Catalog:
    """Schema catalog persisted in its own integer-key B+Tree.

    v0.3 keeps index metadata nested inside each TableSchema. This deliberately
    avoids inventing a second hidden in-memory catalog and lets a v0.3 reader
    decode table records written by v0.1/v0.2 (their JSON simply lacks indexes).
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
            raise SchemaError("mini-sqlite requires exactly one PRIMARY KEY")
        if primary_keys[0].type != ColumnType.INTEGER:
            raise SchemaError("mini-sqlite PRIMARY KEY must be INTEGER")

        table_tree = BTree.create(self.pager)
        table_id = self.meta.next_table_id
        self.meta.next_table_id += 1
        schema = TableSchema(table_id, name, table_tree.root_page, columns)
        self.tree.insert(table_id, schema.encode())
        self._persist_meta(self.meta)
        return schema

    def list_indexes(self) -> list[tuple[TableSchema, IndexSchema]]:
        result: list[tuple[TableSchema, IndexSchema]] = []
        for table in self.list_tables():
            result.extend((table, index) for index in table.indexes)
        return result

    def get_index(self, name: str) -> tuple[TableSchema, IndexSchema]:
        lowered = name.lower()
        for table, index in self.list_indexes():
            if index.name.lower() == lowered:
                return table, index
        raise SchemaError(f"no such index: {name}")

    def create_index(self, name: str, table_name: str, column_name: str) -> IndexSchema:
        try:
            self.get_index(name)
        except SchemaError:
            pass
        else:
            raise SchemaError(f"index already exists: {name}")

        table = self.get_table(table_name)
        column = table.column(column_name)  # validate column
        if table.index_on_column(column.name) is not None:
            existing = table.index_on_column(column.name)
            assert existing is not None
            raise SchemaError(
                f"column {table.name}.{column.name} already has index {existing.name}"
            )

        table_tree = BTree(self.pager, table.root_page)
        decoded_rows = (
            (rowid, RecordCodec.decode(raw)) for rowid, raw in table_tree.scan()
        )
        index_schema = IndexSchema(name=name, column=column.name, root_page=0, unique=False)

        # During initial build, root changes update the local schema object. The
        # table catalog row is written only after all existing rows are indexed.
        def root_changed(root_page: int) -> None:
            index_schema.root_page = root_page

        SecondaryIndex.create(
            self.pager,
            table,
            index_schema,
            decoded_rows,
            on_root_change=root_changed,
        )
        table.indexes.append(index_schema)
        self._save_table(table)
        return index_schema

    def update_root_page(self, table_id: int, root_page: int) -> None:
        schema = self._get_table_by_id(table_id)
        schema.root_page = root_page
        self._save_table(schema)

    def update_index_root(self, table_id: int, index_name: str, root_page: int) -> None:
        schema = self._get_table_by_id(table_id)
        index = schema.get_index(index_name)
        index.root_page = root_page
        self._save_table(schema)

    def _get_table_by_id(self, table_id: int) -> TableSchema:
        raw = self.tree.search(table_id)
        if raw is None:
            raise SchemaError(f"catalog entry {table_id} missing")
        return TableSchema.decode(raw)

    def _save_table(self, schema: TableSchema) -> None:
        # The educational catalog B+Tree has no general update operation yet;
        # delete+insert is enough and keeps root-split handling visible.
        self.tree.delete(schema.table_id)
        self.tree.insert(schema.table_id, schema.encode())
