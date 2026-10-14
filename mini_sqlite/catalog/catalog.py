from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from mini_sqlite.btree import BTree
from mini_sqlite.catalog.schema import Column, ColumnType, IndexSchema, TableSchema
from mini_sqlite.catalog.statistics import ColumnStats, TableStats
from mini_sqlite.errors import SchemaError
from mini_sqlite.index.node import IndexNode
from mini_sqlite.index.secondary import SecondaryIndex
from mini_sqlite.storage import RecordCodec
from mini_sqlite.storage.meta import DatabaseMeta
from mini_sqlite.constants import FORMAT_VERSION
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

    def create_index(self, name: str, table_name: str, column_names) -> IndexSchema:
        try:
            self.get_index(name)
        except SchemaError:
            pass
        else:
            raise SchemaError(f"index already exists: {name}")

        table = self.get_table(table_name)
        if isinstance(column_names, str):
            requested = (column_names,)
        else:
            requested = tuple(column_names)
        if not requested:
            raise SchemaError("CREATE INDEX requires at least one column")
        canonical = tuple(table.column(name).name for name in requested)
        if len(canonical) > 1:
            # Composite index metadata changes the catalog interpretation. Persist
            # format v3 before making that schema reachable so older engines fail
            # loudly instead of treating the index as single-column.
            self.meta.version = FORMAT_VERSION
            self._persist_meta(self.meta)
        if len({name.lower() for name in canonical}) != len(canonical):
            raise SchemaError("index column list contains duplicates")
        existing = table.index_on_columns(canonical)
        if existing is not None:
            raise SchemaError(
                f"columns {table.name}({', '.join(canonical)}) already have index {existing.name}"
            )

        table_tree = BTree(self.pager, table.root_page)
        decoded_rows = (
            (rowid, RecordCodec.decode(raw)) for rowid, raw in table_tree.scan()
        )
        index_schema = IndexSchema(name=name, columns=canonical, root_page=0, unique=False)

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


    def _index_tree_pages(self, root_page: int) -> list[int]:
        pages: list[int] = []
        stack = [root_page]
        seen: set[int] = set()
        while stack:
            page_id = stack.pop()
            if page_id in seen:
                raise SchemaError(f"index tree contains a cycle at page {page_id}")
            seen.add(page_id)
            pages.append(page_id)
            with self.pager.pin_page(page_id) as raw:
                node = IndexNode.decode(page_id, raw)
            if not node.is_leaf:
                stack.extend(reversed(node.children()))
        return pages

    def reindex(self, index_name: str | None = None) -> int:
        """Rebuild one or every secondary index into fresh B+Tree pages.

        Old index pages become unreachable and are intentionally left for VACUUM.
        The caller owns the surrounding transaction, so a failed rebuild truncates
        newly allocated pages and restores the previous catalog root atomically.
        """
        names = [index_name] if index_name is not None else [
            index.name for _table, index in self.list_indexes()
        ]
        rebuilt = 0
        for name in names:
            table, old = self.get_index(name)
            old_pages = self._index_tree_pages(old.root_page)
            table_tree = BTree(self.pager, table.root_page)
            rows = ((rowid, RecordCodec.decode(raw)) for rowid, raw in table_tree.scan())
            replacement = IndexSchema(
                name=old.name,
                columns=old.columns,
                root_page=0,
                unique=old.unique,
            )

            def root_changed(root_page: int) -> None:
                replacement.root_page = root_page

            SecondaryIndex.create(
                self.pager,
                table,
                replacement,
                rows,
                on_root_change=root_changed,
            )
            latest = self.get_table(table.name)
            target = latest.get_index(old.name)
            target.root_page = replacement.root_page
            self._save_table(latest)
            for page_id in old_pages:
                self.pager.free_page(page_id)
            rebuilt += 1
        return rebuilt

    def analyze(self, table_name: str | None = None) -> int:
        """Collect exact statistics and persist them in catalog rows.

        v0.8 deliberately performs a full scan so the relationship between data,
        statistics, selectivity, and plan choice stays observable. Statistics are
        snapshots: later writes do not silently refresh them; run ANALYZE again.
        """
        tables = [self.get_table(table_name)] if table_name is not None else self.list_tables()
        analyzed = 0
        for table in tables:
            tree = BTree(self.pager, table.root_page)
            values_by_column: list[list[object]] = [[] for _ in table.columns]
            row_count = 0
            for _rowid, raw in tree.scan():
                row = RecordCodec.decode(raw)
                row_count += 1
                for i, value in enumerate(row):
                    values_by_column[i].append(value)

            column_stats: dict[str, ColumnStats] = {}
            for column, values in zip(table.columns, values_by_column):
                non_null = [value for value in values if value is not None]
                counts = Counter(non_null)
                column_stats[column.name] = ColumnStats(
                    null_count=len(values) - len(non_null),
                    distinct_count=len(counts),
                    min_value=min(non_null) if non_null else None,
                    max_value=max(non_null) if non_null else None,
                    most_common=counts.most_common(16),
                )
            table.stats = TableStats(row_count=row_count, columns=column_stats)
            self._save_table(table)
            analyzed += 1
        return analyzed

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
