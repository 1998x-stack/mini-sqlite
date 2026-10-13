from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.btree import BTree, BTreeCursor
from mini_sqlite.catalog import Catalog, IndexSchema, TableSchema
from mini_sqlite.errors import CorruptionError, SchemaError
from mini_sqlite.index import SecondaryIndex, SecondaryIndexCursor
from mini_sqlite.planner.plan import AggregateSpec, AssignmentSpec, OrderSpec
from mini_sqlite.sql.ast import AggregateFunction, CompareOp, ComparisonPredicate
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
    """Tiny VDBE-inspired interpreter.

    v0.4 adds a materialized relational working set. Cursor instructions still
    expose physical access paths, while explicit relational opcodes transform
    rows in the SQL order visible in bytecode:

        source -> filter -> collect -> sort -> aggregate/project -> limit -> emit

    This is deliberately simpler than SQLite's production VDBE and future
    iterator/vectorized engines, but it makes relational stages inspectable.
    """

    def __init__(self, pager: Pager, catalog: Catalog):
        self.pager = pager
        self.catalog = catalog

    def execute(self, code: list[Instruction]) -> VMResult:
        pc = 0
        cursors: dict[int, OpenCursor] = {}
        index_cursors: dict[int, OpenIndexCursor] = {}
        rows: list[tuple[Any, ...]] = []
        working_rows: list[tuple[Any, ...]] = []
        projected: tuple[Any, ...] | None = None  # legacy v0.1-v0.3 path
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
                    cursor=BTreeCursor(
tree
),
                    writable=op == OpCode.OPEN_WRITE