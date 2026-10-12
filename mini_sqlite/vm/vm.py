from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.btree import BTree, BTreeCursor
from mini_sqlite.catalog import Catalog, IndexSchema, TableSchema
from mini_sqlite.errors import CorruptionError, SchemaError
from mini_sqlite.index import SecondaryIndex, SecondaryIndexCursor
from mini_sqlite.storage import Pager, RecordCodec
from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode


@dataclass
class OpenCursor:
    schema: TableSchema
    tree: BTree
    cursor: BTreeCursor
    writable: bool


@dataclass
class OpenIndexCursor:
    table: TableSchema
    schema: IndexSchema
    index: SecondaryIndex
    cursor: SecondaryIndexCursor


@dataclass
class VMResult:
    rows: list[tuple[Any, ...]]
    rowcount: int = 0


class VirtualMachine:
    """Tiny register-less VDBE-inspired interpreter.

    v0.3 adds a second cursor family for secondary indexes. Index cursors yield
    rowids; table cursors still own actual row records. The explicit
    INDEX_TO_TABLE opcode makes the classic secondary-index "back to table"
    lookup visible in bytecode.
    """

    def __init__(self, pager: Pager, catalog: Catalog):
        self.pager = pager
        self.catalog = catalog

    def execute(self, code: list[Instruction]) -> VMResult:
        pc = 0
        cursors: dict[int, OpenCursor] = {}
        index_cursors: dict[int, OpenIndexCursor] = {}
        rows: list[tuple[Any, ...]] = []
        projected: tuple[Any, ...] | None = None
        rowcount = 0

        while pc < len(code):
            ins = code[pc]
            op = ins.opcode

            if op == OpCode.CREATE_TABLE:
                plan = ins.p4
                self.catalog.create_table(plan.name, plan.columns)
                rowcount += 1

            elif op == OpCode.CREATE_INDEX:
                plan = ins.p4
                self.catalog.create_index(plan.name, plan.table, plan.column)
                rowcount += 1

            elif op in (OpCode.OPEN_READ, OpCode.OPEN_WRITE):
                schema = self.catalog.get_table(str(ins.p4))

                def root_changed(root_page: int, table_id=schema.table_id) -> None:
                    self.catalog.update_root_page(table_id, root_page)

                tree = BTree(
                    self.pager,
                    schema.root_page,
                    on_root_change=root_changed,
                )
                cursors[ins.p1] = OpenCursor(
                    schema=schema,
                    tree=tree,
                    cursor=BTreeCursor(tree),
                    writable=op == OpCode.OPEN_WRITE,
                )

            elif op == OpCode.OPEN_INDEX:
                table, index_schema = self.catalog.get_index(str(ins.p4))
                index = self._secondary_index(table, index_schema)
                index_cursors[ins.p1] = OpenIndexCursor(
                    table=table,
                    schema=index_schema,
                    index=index,
                    cursor=SecondaryIndexCursor(index),
                )

            elif op == OpCode.REWIND:
                cur = cursors[ins.p1]
                if not cur.cursor.rewind():
                    pc = ins.p2
                    continue

            elif op == OpCode.SEEK_PK:
                cur = cursors[ins.p1]
                if not cur.cursor.seek(int(ins.p4)):
                    pc = ins.p2
                    continue

            elif op == OpCode.SEEK_INDEX_EQ:
                cur = index_cursors[ins.p1]
                if not cur.cursor.seek_equal(ins.p4):
                    pc = ins.p2
                    continue

            elif op == OpCode.INDEX_TO_TABLE:
                index_cur = index_cursors[ins.p1]
                table_cur = cursors[ins.p2]
                rowid = index_cur.cursor.current_rowid
                if rowid is None:
                    raise RuntimeError("INDEX_TO_TABLE without current index rowid")
                if not table_cur.cursor.seek(rowid):
                    raise CorruptionError(
                        f"index {index_cur.schema.name} references missing rowid {rowid}"
                    )

            elif op == OpCode.FILTER_EQ:
                cur = cursors[ins.p1]
                current = cur.cursor.current
                if current is None:
                    pc = ins.p2
                    continue
                values = RecordCodec.decode(current.value)
                if values[ins.p3] != ins.p4:
                    pc = ins.p2
                    continue

            elif op == OpCode.PROJECT:
                cur = cursors[ins.p1]
                current = cur.cursor.current
                if current is None:
                    raise RuntimeError("PROJECT without current row")
                values = RecordCodec.decode(current.value)
                projected = tuple(values[i] for i in ins.p4)

            elif op == OpCode.RESULT_ROW:
                if projected is None:
                    raise RuntimeError("RESULT_ROW without PROJECT")
                rows.append(projected)
                projected = None

            elif op == OpCode.NEXT:
                cur = cursors[ins.p1]
                if cur.cursor.next():
                    pc = ins.p2
                    continue

            elif op == OpCode.INDEX_NEXT:
                cur = index_cursors[ins.p1]
                if cur.cursor.next():
                    pc = ins.p2
                    continue

            elif op == OpCode.INSERT_ROW:
                cur = cursors[ins.p1]
                self._require_write(cur)
                values = tuple(ins.p4)
                cur.schema.validate_row(values)
                rowid = int(values[cur.schema.primary_key_index])
                cur.tree.insert(rowid, RecordCodec.encode(values))
                # Table + all index mutations share the same surrounding v0.2
                # transaction. Any failure aborts the statement/transaction.
                for index_schema in cur.schema.indexes:
                    self._secondary_index(cur.schema, index_schema).insert(values, rowid)
                rowcount += 1

            elif op == OpCode.DELETE_CURRENT:
                cur = cursors[ins.p1]
                self._require_write(cur)
                current = cur.cursor.current
                if current is not None:
                    values = RecordCodec.decode(current.value)
                    rowid = current.key
                    for index_schema in cur.schema.indexes:
                        deleted = self._secondary_index(cur.schema, index_schema).delete(
                            values, rowid
                        )
                        if not deleted:
                            raise CorruptionError(
                                f"index {index_schema.name} missing entry for rowid {rowid}"
                            )
                    if cur.tree.delete(rowid):
                        rowcount += 1

            elif op == OpCode.HALT:
                break

            else:
                raise RuntimeError(f"unknown opcode {op}")
            pc += 1

        return VMResult(rows=rows, rowcount=rowcount)

    def _secondary_index(self, table: TableSchema, schema: IndexSchema) -> SecondaryIndex:
        def root_changed(
            root_page: int,
            table_id=table.table_id,
            index_name=schema.name,
        ) -> None:
            self.catalog.update_index_root(table_id, index_name, root_page)

        return SecondaryIndex(
            self.pager,
            table,
            schema,
            on_root_change=root_changed,
        )

    @staticmethod
    def _require_write(cursor: OpenCursor) -> None:
        if not cursor.writable:
            raise SchemaError("attempt to modify a read-only cursor")
