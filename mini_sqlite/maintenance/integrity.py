from __future__ import annotations

from dataclasses import dataclass

from mini_sqlite.btree.node import BTreeNode
from mini_sqlite.catalog.schema import TableSchema
from mini_sqlite.index.key_codec import KeyCodec
from mini_sqlite.index.node import IndexNode
from mini_sqlite.storage import RecordCodec
from mini_sqlite.storage.meta import DatabaseMeta


@dataclass(frozen=True)
class IntegrityReport:
    """Result of a logical + structural database consistency pass."""

    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    page_count: int
    reachable_pages: int
    free_pages: int
    orphan_pages: tuple[int, ...]
    tables: int
    rows: int
    indexes: int
    index_entries: int

    def render(self) -> str:
        lines = [
            "ok" if self.ok else "corrupt",
            (
                f"pages={self.page_count} reachable={self.reachable_pages} "
                f"free={self.free_pages} orphan={len(self.orphan_pages)} "
                f"tables={self.tables} rows={self.rows} "
                f"indexes={self.indexes} index_entries={self.index_entries}"
            ),
        ]
        if self.errors:
            lines.append("errors:")
            lines.extend(f"  - {message}" for message in self.errors)
        if self.warnings:
            lines.append("warnings:")
            lines.extend(f"  - {message}" for message in self.warnings)
        return "\n".join(lines)


class IntegrityChecker:
    """Validate page trees, rows, catalog references, and secondary indexes.

    This is deliberately stronger than merely decoding every page. It checks that
    parent/child relationships form trees, leaf sibling chains are coherent, table
    rowids agree with INTEGER PRIMARY KEY values, and each persisted secondary
    index is exactly the set implied by table rows.
    """

    def __init__(self, pager, catalog, meta: DatabaseMeta):
        self.pager = pager
        self.catalog = catalog
        self.meta = meta
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.owners: dict[int, str] = {0: "meta"}
        self.total_rows = 0
        self.total_indexes = 0
        self.total_index_entries = 0
        self.total_free_pages = 0

    def run(self) -> IntegrityReport:
        if self.pager.page_count == 0:
            self.errors.append("database has no metadata page")
            return self._report(0, 0)

        if self.meta.catalog_root_page <= 0 or self.meta.catalog_root_page >= self.pager.page_count:
            self.errors.append(
                f"catalog root page {self.meta.catalog_root_page} is outside logical page range"
            )
            return self._report(0, 0)

        try:
            free_pages = self.pager.free_list_pages()
        except Exception as exc:
            self.errors.append(f"free-list cannot be traversed: {exc}")
            free_pages = []
        self.total_free_pages = len(free_pages)
        for page_id in free_pages:
            self._claim(page_id, "free-list")

        self._walk_integer_tree(self.meta.catalog_root_page, "catalog")
        try:
            tables = self.catalog.list_tables()
        except Exception as exc:
            self.errors.append(f"catalog rows cannot be decoded: {exc}")
            return self._report(0, 0)

        table_rows: dict[int, list[tuple[int, tuple[object, ...]]]] = {}
        for table in tables:
            rows = self._check_table(table)
            table_rows[table.table_id] = rows
            self.total_rows += len(rows)

        for table in tables:
            for index in table.indexes:
                self.total_indexes += 1
                self.total_index_entries += self._check_index(
                    table, index, table_rows.get(table.table_id, [])
                )

        for table in tables:
            if table.stats is not None:
                actual = len(table_rows.get(table.table_id, []))
                if table.stats.row_count != actual:
                    self.warnings.append(
                        f"statistics for {table.name} are stale: "
                        f"row_count={table.stats.row_count}, actual={actual}; run ANALYZE"
                    )

        reachable = set(self.owners)
        orphan = tuple(sorted(set(range(self.pager.page_count)) - reachable))
        if orphan:
            sample = ", ".join(str(page) for page in orphan[:12])
            suffix = "…" if len(orphan) > 12 else ""
            self.warnings.append(
                f"{len(orphan)} unreachable page(s) can be reclaimed by VACUUM: {sample}{suffix}"
            )
        return IntegrityReport(
            ok=not self.errors,
            errors=tuple(self.errors),
            warnings=tuple(self.warnings),
            page_count=self.pager.page_count,
            reachable_pages=len(reachable),
            free_pages=self.total_free_pages,
            orphan_pages=orphan,
            tables=len(tables),
            rows=self.total_rows,
            indexes=self.total_indexes,
            index_entries=self.total_index_entries,
        )

    def _report(self, tables: int, rows: int) -> IntegrityReport:
        reachable = set(self.owners)
        orphan = tuple(sorted(set(range(self.pager.page_count)) - reachable))
        return IntegrityReport(
            ok=not self.errors,
            errors=tuple(self.errors),
            warnings=tuple(self.warnings),
            page_count=self.pager.page_count,
            reachable_pages=len(reachable),
            free_pages=self.total_free_pages,
            orphan_pages=orphan,
            tables=tables,
            rows=rows,
            indexes=self.total_indexes,
            index_entries=self.total_index_entries,
        )

    def _claim(self, page_id: int, owner: str) -> bool:
        if page_id <= 0 or page_id >= self.pager.page_count:
            self.errors.append(f"{owner} references out-of-range page {page_id}")
            return False
        existing = self.owners.get(page_id)
        if existing is not None and existing != owner:
            self.errors.append(f"page {page_id} is shared by {existing} and {owner}")
            return False
        self.owners[page_id] = owner
        return True

    def _read_page(self, page_id: int) -> bytes:
        with self.pager.pin_page(page_id) as raw:
            return bytes(raw)

    def _walk_integer_tree(self, root_page: int, owner: str) -> list[BTreeNode]:
        leaves: list[BTreeNode] = []
        visiting: set[int] = set()

        def visit(page_id: int, expected_parent: int, low: int | None, high: int | None) -> None:
            if page_id in visiting:
                self.errors.append(f"{owner} contains a page cycle at {page_id}")
                return
            if not self._claim(page_id, owner):
                return
            visiting.add(page_id)
            try:
                node = BTreeNode.decode(page_id, self._read_page(page_id))
            except Exception as exc:
                self.errors.append(f"{owner} page {page_id} cannot be decoded: {exc}")
                visiting.remove(page_id)
                return
            if node.parent != expected_parent:
                self.errors.append(
                    f"{owner} page {page_id} parent={node.parent}, expected={expected_parent}"
                )

            if node.is_leaf:
                keys = [cell.key for cell in node.leaf_cells]
                if keys != sorted(keys) or len(keys) != len(set(keys)):
                    self.errors.append(f"{owner} leaf page {page_id} keys are not strictly ordered")
                for key in keys:
                    if low is not None and key < low:
                        self.errors.append(f"{owner} key {key} on page {page_id} is below {low}")
                    if high is not None and key >= high:
                        self.errors.append(f"{owner} key {key} on page {page_id} is not below {high}")
                leaves.append(node)
            else:
                seps = [cell.key for cell in node.internal_cells]
                if seps != sorted(seps) or len(seps) != len(set(seps)):
                    self.errors.append(
                        f"{owner} internal page {page_id} separators are not strictly ordered"
                    )
                children = node.children()
                if not children or any(child == 0 for child in children):
                    self.errors.append(f"{owner} internal page {page_id} has a zero/missing child")
                for i, child in enumerate(children):
                    child_low = low if i == 0 else seps[i - 1]
                    child_high = high if i == len(children) - 1 else seps[i]
                    visit(child, page_id, child_low, child_high)
            visiting.remove(page_id)

        visit(root_page, 0, None, None)
        for i, leaf in enumerate(leaves):
            expected = leaves[i + 1].page_id if i + 1 < len(leaves) else 0
            if leaf.right_sibling != expected:
                self.errors.append(
                    f"{owner} leaf page {leaf.page_id} right={leaf.right_sibling}, expected={expected}"
                )
        return leaves

    def _walk_index_tree(self, root_page: int, owner: str) -> list[IndexNode]:
        leaves: list[IndexNode] = []
        visiting: set[int] = set()

        def visit(page_id: int, expected_parent: int, low: bytes | None, high: bytes | None) -> None:
            if page_id in visiting:
                self.errors.append(f"{owner} contains a page cycle at {page_id}")
                return
            if not self._claim(page_id, owner):
                return
            visiting.add(page_id)
            try:
                node = IndexNode.decode(page_id, self._read_page(page_id))
            except Exception as exc:
                self.errors.append(f"{owner} page {page_id} cannot be decoded: {exc}")
                visiting.remove(page_id)
                return
            if node.parent != expected_parent:
                self.errors.append(
                    f"{owner} page {page_id} parent={node.parent}, expected={expected_parent}"
                )

            if node.is_leaf:
                keys = [cell.key for cell in node.leaf_cells]
                if keys != sorted(keys) or len(keys) != len(set(keys)):
                    self.errors.append(f"{owner} leaf page {page_id} keys are not strictly ordered")
                for key in keys:
                    if low is not None and key < low:
                        self.errors.append(f"{owner} key on page {page_id} is below lower bound")
                    if high is not None and key >= high:
                        self.errors.append(f"{owner} key on page {page_id} exceeds upper bound")
                leaves.append(node)
            else:
                seps = [cell.key for cell in node.internal_cells]
                if seps != sorted(seps) or len(seps) != len(set(seps)):
                    self.errors.append(
                        f"{owner} internal page {page_id} separators are not strictly ordered"
                    )
                children = node.children()
                if not children or any(child == 0 for child in children):
                    self.errors.append(f"{owner} internal page {page_id} has a zero/missing child")
                for i, child in enumerate(children):
                    child_low = low if i == 0 else seps[i - 1]
                    child_high = high if i == len(children) - 1 else seps[i]
                    visit(child, page_id, child_low, child_high)
            visiting.remove(page_id)

        visit(root_page, 0, None, None)
        for i, leaf in enumerate(leaves):
            expected = leaves[i + 1].page_id if i + 1 < len(leaves) else 0
            if leaf.right_sibling != expected:
                self.errors.append(
                    f"{owner} leaf page {leaf.page_id} right={leaf.right_sibling}, expected={expected}"
                )
        return leaves

    def _check_table(self, table: TableSchema) -> list[tuple[int, tuple[object, ...]]]:
        owner = f"table:{table.name}"
        leaves = self._walk_integer_tree(table.root_page, owner)
        rows: list[tuple[int, tuple[object, ...]]] = []
        seen: set[int] = set()
        for leaf in leaves:
            for cell in leaf.leaf_cells:
                try:
                    row = RecordCodec.decode(cell.value)
                    table.validate_row(row)
                except Exception as exc:
                    self.errors.append(
                        f"{owner} rowid {cell.key} cannot be decoded/validated: {exc}"
                    )
                    continue
                if cell.key in seen:
                    self.errors.append(f"{owner} contains duplicate rowid {cell.key}")
                seen.add(cell.key)
                if row[table.primary_key_index] != cell.key:
                    self.errors.append(
                        f"{owner} rowid {cell.key} disagrees with primary key "
                        f"{row[table.primary_key_index]!r}"
                    )
                rows.append((cell.key, row))
        return rows

    def _check_index(self, table, index, rows: list[tuple[int, tuple[object, ...]]]) -> int:
        owner = f"index:{index.name}"
        leaves = self._walk_index_tree(index.root_page, owner)
        actual: list[tuple[bytes, bytes]] = []
        for leaf in leaves:
            actual.extend((cell.key, cell.value) for cell in leaf.leaf_cells)

        column_indexes = tuple(table.column_index(name) for name in index.columns)
        column_types = tuple(table.columns[i].type for i in column_indexes)
        expected = sorted(
            (
                KeyCodec.index_key(
                    tuple(values[i] for i in column_indexes), column_types, rowid
                ),
                KeyCodec.encode_rowid(rowid),
            )
            for rowid, values in rows
        )
        if actual != expected:
            self.errors.append(
                f"{owner} contents disagree with {table.name}({', '.join(index.columns)}): "
                f"expected {len(expected)} entries, found {len(actual)}"
            )
        for key, stored in actual:
            try:
                rowid_from_key = KeyCodec.decode_rowid(key)
                rowid_from_value = KeyCodec.decode_rowid(stored)
            except Exception as exc:
                self.errors.append(f"{owner} contains invalid rowid encoding: {exc}")
                continue
            if rowid_from_key != rowid_from_value:
                self.errors.append(
                    f"{owner} key rowid {rowid_from_key} != stored rowid {rowid_from_value}"
                )
        return len(actual)
