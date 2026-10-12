from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.btree import BTree, BTreeCursor
from mini_sqlite.catalog import Catalog, TableSchema
from mini_sqlite.errors import SchemaError
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
class VMResult:
    rows: list[tuple[Any, ...]]
    rowcount: int = 0


class VirtualMachine:
    """A tiny register-less VDBE-inspired interpreter."""

    def __init__(self, pager: Pager, catalog: Catalog):
        self.pager = pager
        self.catalog = catalog

    def execute(self, code: list[Instruction]) -> VMResult:
        pc = 0
        cursors: dict[int, OpenCursor] = {}
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
            elif op in (OpCode.OPEN_READ, OpCode.OPEN_WRITE):
                schema = self.catalog.get_table(str(ins.p4))
                def root_changed(root_page: int, table_id=schema.table_id) -> None:
                    self.catalog.update_root_page(table_id, root_page)
                tree = BTree(self.pager, schema.root_page, on_root_change=root_changed)
                cursors[ins.p1] = OpenCursor(schema=schema, tree=tree, cursor=BTreeCursor(tree), writable=op == OpCode.OPEN_WRITE)
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
            elif op == OpCode.INSERT_ROW:
                cur = cursors[ins.p1]
                self._require_write(cur)
                values = tuple(ins.p4)
                cur.schema.validate_row(values)
                pk = int(values[cur.schema.primary_key_index])
                cur.tree.insert(pk, RecordCodec.encode(values))
                rowcount += 1
            elif op == OpCode.DELETE_CURRENT:
                cur = cursors[ins.p1]
                self._require_write(cur)
                current = cur.cursor.current
                if current is not None and cur.tree.delete(current.key):
                    rowcount += 1
            elif op == OpCode.HALT:
                break
            else:
                raise RuntimeError(f"unknown opcode {op}")
            pc += 1
        return VMResult(rows=rows, rowcount=rowcount)

    @staticmethod
    def _require_write(cursor: OpenCursor) -> None:
        if not cursor.writable:
            raise SchemaError("attempt to modify a read-only cursor")
