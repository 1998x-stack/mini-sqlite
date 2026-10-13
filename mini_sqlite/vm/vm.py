from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.btree import BTree, BTreeCursor
from mini_sqlite.catalog import Catalog, IndexSchema, TableSchema
from mini_sqlite.errors import CorruptionError, SchemaError
from mini_sqlite.index import SecondaryIndex, SecondaryIndexCursor
from mini_sqlite.planner.plan import (
    AggregateSpec,
    AssignmentSpec,
    JoinedPredicateSpec,
    JoinSpec,
    OrderSpec,
)
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

    v0.5 keeps the materialized relational working set and adds explicit
    two-source join instructions. Cursor instructions still
    expose physical access paths, while explicit relational opcodes transform
    rows in the SQL order visible in bytecode:

        source(s) -> join -> filter -> sort -> aggregate/project -> limit -> emit

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

            elif op == OpCode.SEEK_PK_FROM_COLUMN:
                target = cursors[ins.p1]
                source = cursors[ins.p2]
                source_values = self._cursor_values(source, "SEEK_PK_FROM_COLUMN")
                key = source_values[ins.p3]
                if key is None or not isinstance(key, int) or not target.cursor.seek(key):
                    pc = int(ins.p4)
                    continue

            elif op == OpCode.SEEK_INDEX_FROM_COLUMN:
                index_cur = index_cursors[ins.p1]
                source = cursors[ins.p2]
                source_values = self._cursor_values(source, "SEEK_INDEX_FROM_COLUMN")
                value = source_values[ins.p3]
                if not index_cur.cursor.seek_equal(value):
                    pc = int(ins.p4)
                    continue

            elif op == OpCode.FILTER_JOIN_EQ:
                left = cursors[ins.p1]
                right = cursors[ins.p2]
                spec: JoinSpec = ins.p4
                left_values = self._cursor_values(left, "FILTER_JOIN_EQ")
                right_values = self._cursor_values(right, "FILTER_JOIN_EQ")
                if left_values[spec.left_column_index] != right_values[spec.right_column_index]:
                    pc = ins.p3
                    continue

            elif op == OpCode.COLLECT_JOIN_ROW:
                left = cursors[ins.p1]
                right = cursors[ins.p2]
                left_values = self._cursor_values(left, "COLLECT_JOIN_ROW")
                right_values = self._cursor_values(right, "COLLECT_JOIN_ROW")
                working_rows.append(tuple(left_values) + tuple(right_values))

            elif op == OpCode.FILTER_ROWS:
                spec: JoinedPredicateSpec = ins.p4
                working_rows = [
                    row
                    for row in working_rows
                    if self._compare(row[spec.column_index], spec.op, spec.value)
                ]

            elif op == OpCode.FILTER_EQ:  # historical bytecode support
                cur = cursors[ins.p1]
                current = cur.cursor.current
                if current is None:
                    pc = ins.p2
                    continue
                values = RecordCodec.decode(current.value)
                if values[ins.p3] != ins.p4:
                    pc = ins.p2
                    continue

            elif op == OpCode.FILTER_COMPARE:
                cur = cursors[ins.p1]
                current = cur.cursor.current
                predicate: ComparisonPredicate = ins.p4
                if current is None:
                    pc = ins.p2
                    continue
                values = RecordCodec.decode(current.value)
                if not self._compare(values[ins.p3], predicate.op, predicate.value):
                    pc = ins.p2
                    continue

            elif op == OpCode.COLLECT_ROW:
                cur = cursors[ins.p1]
                current = cur.cursor.current
                if current is None:
                    raise RuntimeError("COLLECT_ROW without current row")
                working_rows.append(tuple(RecordCodec.decode(current.value)))

            elif op == OpCode.SORT_ROWS:
                spec: OrderSpec = ins.p4
                # Educational NULL policy: NULL sorts before non-NULL in ASC and
                # therefore after non-NULL in DESC. Values in one column share a type.
                working_rows.sort(
                    key=lambda row, i=spec.column_index: (row[i] is not None, row[i]),
                    reverse=spec.descending,
                )

            elif op == OpCode.PROJECT_ROWS:
                projection: list[int] = ins.p4
                working_rows = [tuple(row[i] for i in projection) for row in working_rows]

            elif op == OpCode.AGGREGATE_ROWS:
                specs: tuple[AggregateSpec, ...] = ins.p4
                working_rows = [self._aggregate(working_rows, specs)]

            elif op == OpCode.LIMIT_ROWS:
                working_rows = working_rows[: ins.p1]

            elif op == OpCode.EMIT_ROWS:
                rows.extend(working_rows)
                working_rows = []

            elif op == OpCode.PROJECT:  # historical bytecode support
                cur = cursors[ins.p1]
                current = cur.cursor.current
                if current is None:
                    raise RuntimeError("PROJECT without current row")
                values = RecordCodec.decode(current.value)
                projected = tuple(values[i] for i in ins.p4)

            elif op == OpCode.RESULT_ROW:  # historical bytecode support
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
                for index_schema in cur.schema.indexes:
                    self._secondary_index(cur.schema, index_schema).insert(values, rowid)
                rowcount += 1

            elif op == OpCode.UPDATE_CURRENT:
                cur = cursors[ins.p1]
                self._require_write(cur)
                current = cur.cursor.current
                if current is not None:
                    old_values = tuple(RecordCodec.decode(current.value))
                    new_values = list(old_values)
                    assignments: tuple[AssignmentSpec, ...] = ins.p4
                    for assignment in assignments:
                        new_values[assignment.column_index] = assignment.value
                    new_tuple = tuple(new_values)
                    cur.schema.validate_row(new_tuple)
                    rowid = current.key

                    # Remove old secondary entries before replacing the table row.
                    # The surrounding rollback-journal transaction makes the whole
                    # table+all-index mutation atomic on failure/crash.
                    for index_schema in cur.schema.indexes:
                        deleted = self._secondary_index(cur.schema, index_schema).delete(
                            old_values, rowid
                        )
                        if not deleted:
                            raise CorruptionError(
                                f"index {index_schema.name} missing entry for rowid {rowid}"
                            )
                    if not cur.tree.delete(rowid):
                        raise CorruptionError(f"table rowid {rowid} disappeared during UPDATE")
                    cur.tree.insert(rowid, RecordCodec.encode(new_tuple))
                    for index_schema in cur.schema.indexes:
                        self._secondary_index(cur.schema, index_schema).insert(new_tuple, rowid)
                    rowcount += 1

            elif op == OpCode.DELETE_CURRENT:
                cur = cursors[ins.p1]
                self._require_write(cur)
                current = cur.cursor.current
                if current is not None:
                    values = tuple(RecordCodec.decode(current.value))
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

    @staticmethod
    def _cursor_values(cursor: OpenCursor, operation: str) -> tuple[Any, ...]:
        current = cursor.cursor.current
        if current is None:
            raise RuntimeError(f"{operation} without current row")
        return tuple(RecordCodec.decode(current.value))

    @staticmethod
    def _compare(left: object, op: CompareOp, right: object) -> bool:
        if op == CompareOp.EQ:
            return left == right
        if op == CompareOp.NE:
            return left != right
        # The project intentionally does not model SQL three-valued logic yet.
        # Ordered comparison involving NULL simply does not match.
        if left is None or right is None:
            return False
        if op == CompareOp.LT:
            return left < right
        if op == CompareOp.LE:
            return left <= right
        if op == CompareOp.GT:
            return left > right
        if op == CompareOp.GE:
            return left >= right
        raise RuntimeError(f"unknown comparison operator {op}")

    @staticmethod
    def _aggregate(
        rows: list[tuple[Any, ...]], specs: tuple[AggregateSpec, ...]
    ) -> tuple[Any, ...]:
        result: list[Any] = []
        for spec in specs:
            if spec.function == AggregateFunction.COUNT:
                if spec.column_index is None:
                    result.append(len(rows))
                else:
                    result.append(sum(row[spec.column_index] is not None for row in rows))
                continue

            assert spec.column_index is not None
            values = [row[spec.column_index] for row in rows if row[spec.column_index] is not None]
            if spec.function == AggregateFunction.SUM:
                result.append(sum(values) if values else None)
            elif spec.function == AggregateFunction.MIN:
                result.append(min(values) if values else None)
            elif spec.function == AggregateFunction.MAX:
                result.append(max(values) if values else None)
            else:
                raise RuntimeError(f"unknown aggregate function {spec.function}")
        return tuple(result)

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
