from __future__ import annotations

from mini_sqlite.planner.plan import (
    AccessPath,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    JoinSelectPlan,
    Plan,
    SelectPlan,
    UpdatePlan,
)
from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode


class Compiler:
    """Compile logical plans to tiny VDBE-inspired bytecode.

    v0.4 makes relational processing visible after row-source enumeration:

        COLLECT_ROW -> SORT_ROWS -> AGGREGATE/PROJECT -> LIMIT_ROWS -> EMIT_ROWS
    """

    def compile(self, plan: Plan) -> list[Instruction]:
        if isinstance(plan, CreateTablePlan):
            return [Instruction(OpCode.CREATE_TABLE, p4=plan), Instruction(OpCode.HALT)]
        if isinstance(plan, CreateIndexPlan):
            return [Instruction(OpCode.CREATE_INDEX, p4=plan), Instruction(OpCode.HALT)]
        if isinstance(plan, InsertPlan):
            return [
                Instruction(OpCode.OPEN_WRITE, p1=0, p4=plan.schema.name),
                Instruction(OpCode.INSERT_ROW, p1=0, p4=plan.values),
                Instruction(OpCode.HALT),
            ]
        if isinstance(plan, JoinSelectPlan):
            return self._join_select(plan)
        if isinstance(plan, SelectPlan):
            return self._select(plan)
        if isinstance(plan, DeletePlan):
            return self._delete(plan)
        if isinstance(plan, UpdatePlan):
            return self._update(plan)
        raise TypeError(f"unsupported plan {type(plan).__name__}")

    def _select(self, plan: SelectPlan) -> list[Instruction]:
        code: list[Instruction] = [Instruction(OpCode.OPEN_READ, p1=0, p4=plan.schema.name)]
        pipeline_jump_sites: list[int] = []

        if plan.access_path == AccessPath.PRIMARY_KEY:
            assert plan.where is not None
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=0, p4=int(plan.where.value)))
            pipeline_jump_sites.append(1)
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))

        elif plan.access_path == AccessPath.SECONDARY_INDEX:
            assert plan.index is not None and plan.where is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            seek_addr = len(code)
            code.append(Instruction(OpCode.SEEK_INDEX_EQ, p1=1, p2=0, p4=plan.where.value))
            pipeline_jump_sites.append(seek_addr)
            loop_addr = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=loop_addr))

        else:
            rewind_addr = len(code)
            code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
            pipeline_jump_sites.append(rewind_addr)
            loop_addr = len(code)
            if plan.where is not None:
                filter_addr = len(code)
                code.append(
                    Instruction(
                        OpCode.FILTER_COMPARE,
                        p1=0,
                        p2=0,
                        p3=plan.schema.column_index(plan.where.column),
                        p4=plan.where,
                    )
                )
            else:
                filter_addr = -1
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))
            next_addr = len(code)
            code.append(Instruction(OpCode.NEXT, p1=0, p2=loop_addr))
            if filter_addr >= 0:
                code[filter_addr] = Instruction(
                    OpCode.FILTER_COMPARE,
                    p1=0,
                    p2=next_addr,
                    p3=plan.schema.column_index(plan.where.column),
                    p4=plan.where,
                )

        pipeline_addr = len(code)
        for addr in pipeline_jump_sites:
            ins = code[addr]
            code[addr] = Instruction(ins.opcode, ins.p1, pipeline_addr, ins.p3, ins.p4)

        if plan.order_by is not None:
            code.append(Instruction(OpCode.SORT_ROWS, p4=plan.order_by))
        if plan.aggregates:
            code.append(Instruction(OpCode.AGGREGATE_ROWS, p4=plan.aggregates))
        else:
            code.append(Instruction(OpCode.PROJECT_ROWS, p4=plan.projection))
        if plan.limit is not None:
            code.append(Instruction(OpCode.LIMIT_ROWS, p1=plan.limit))
        code.append(Instruction(OpCode.EMIT_ROWS))
        code.append(Instruction(OpCode.HALT))
        return code

    def _join_select(self, plan: JoinSelectPlan) -> list[Instruction]:
        """Compile one INNER JOIN while keeping the join algorithm visible.

        The left table is the outer source. The right source is either rewound
        for every outer row (plain nested loop), sought by primary key, or sought
        through a secondary index. Post-join relational operators reuse v0.4.
        """
        code: list[Instruction] = [
            Instruction(OpCode.OPEN_READ, p1=0, p4=plan.left_schema.name),
            Instruction(OpCode.OPEN_READ, p1=1, p4=plan.right_schema.name),
        ]
        if plan.inner_access_path == AccessPath.SECONDARY_INDEX:
            assert plan.inner_index is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=2, p4=plan.inner_index.name))

        left_rewind = len(code)
        code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
        outer_loop = len(code)

        if plan.inner_access_path == AccessPath.PRIMARY_KEY:
            seek_addr = len(code)
            code.append(
                Instruction(
                    OpCode.SEEK_PK_FROM_COLUMN,
                    p1=1,
                    p2=0,
                    p3=plan.join.left_column_index,
                    p4=0,
                )
            )
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            next_left = len(code)
            code.append(Instruction(OpCode.NEXT, p1=0, p2=outer_loop))
            ins = code[seek_addr]
            code[seek_addr] = Instruction(ins.opcode, ins.p1, ins.p2, ins.p3, next_left)

        elif plan.inner_access_path == AccessPath.SECONDARY_INDEX:
            seek_addr = len(code)
            code.append(
                Instruction(
                    OpCode.SEEK_INDEX_FROM_COLUMN,
                    p1=2,
                    p2=0,
                    p3=plan.join.left_column_index,
                    p4=0,
                )
            )
            match_loop = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=2, p2=1))
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            code.append(Instruction(OpCode.INDEX_NEXT, p1=2, p2=match_loop))
            next_left = len(code)
            code.append(Instruction(OpCode.NEXT, p1=0, p2=outer_loop))
            ins = code[seek_addr]
            code[seek_addr] = Instruction(ins.opcode, ins.p1, ins.p2, ins.p3, next_left)

        else:
            right_rewind = len(code)
            code.append(Instruction(OpCode.REWIND, p1=1, p2=0))
            inner_loop = len(code)
            filter_addr = len(code)
            code.append(
                Instruction(
                    OpCode.FILTER_JOIN_EQ,
                    p1=0,
                    p2=1,
                    p3=0,
                    p4=plan.join,
                )
            )
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            next_right = len(code)
            code.append(Instruction(OpCode.NEXT, p1=1, p2=inner_loop))
            next_left = len(code)
            code.append(Instruction(OpCode.NEXT, p1=0, p2=outer_loop))
            rewind = code[right_rewind]
            code[right_rewind] = Instruction(
                rewind.opcode, rewind.p1, next_left, rewind.p3, rewind.p4
            )
            filt = code[filter_addr]
            code[filter_addr] = Instruction(
                filt.opcode, filt.p1, filt.p2, next_right, filt.p4
            )

        pipeline_addr = len(code)
        rewind = code[left_rewind]
        code[left_rewind] = Instruction(
            rewind.opcode, rewind.p1, pipeline_addr, rewind.p3, rewind.p4
        )

        if plan.where is not None:
            code.append(Instruction(OpCode.FILTER_ROWS, p4=plan.where))
        if plan.order_by is not None:
            code.append(Instruction(OpCode.SORT_ROWS, p4=plan.order_by))
        if plan.aggregates:
            code.append(Instruction(OpCode.AGGREGATE_ROWS, p4=plan.aggregates))
        else:
            code.append(Instruction(OpCode.PROJECT_ROWS, p4=plan.projection))
        if plan.limit is not None:
            code.append(Instruction(OpCode.LIMIT_ROWS, p1=plan.limit))
        code.append(Instruction(OpCode.EMIT_ROWS))
        code.append(Instruction(OpCode.HALT))
        return code

    def _delete(self, plan: DeletePlan) -> list[Instruction]:
        code: list[Instruction] = [Instruction(OpCode.OPEN_WRITE, p1=0, p4=plan.schema.name)]
        if plan.where is None:
            code.append(Instruction(OpCode.REWIND, p1=0, p2=4))
            code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
            code.append(Instruction(OpCode.NEXT, p1=0, p2=2))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path == AccessPath.PRIMARY_KEY:
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=3, p4=int(plan.where.value)))
            code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path == AccessPath.SECONDARY_INDEX:
            assert plan.index is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            code.append(Instruction(OpCode.SEEK_INDEX_EQ, p1=1, p2=6, p4=plan.where.value))
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=3))
            code.append(Instruction(OpCode.HALT))
            return code

        code.append(Instruction(OpCode.REWIND, p1=0, p2=5))
        code.append(
            Instruction(
                OpCode.FILTER_COMPARE,
                p1=0,
                p2=4,
                p3=plan.schema.column_index(plan.where.column),
                p4=plan.where,
            )
        )
        code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
        code.append(Instruction(OpCode.NEXT, p1=0, p2=2))
        code.append(Instruction(OpCode.HALT))
        return code

    def _update(self, plan: UpdatePlan) -> list[Instruction]:
        code: list[Instruction] = [Instruction(OpCode.OPEN_WRITE, p1=0, p4=plan.schema.name)]
        if plan.where is None:
            code.append(Instruction(OpCode.REWIND, p1=0, p2=4))
            code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
            code.append(Instruction(OpCode.NEXT, p1=0, p2=2))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path == AccessPath.PRIMARY_KEY:
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=3, p4=int(plan.where.value)))
            code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path == AccessPath.SECONDARY_INDEX:
            assert plan.index is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            code.append(Instruction(OpCode.SEEK_INDEX_EQ, p1=1, p2=6, p4=plan.where.value))
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=3))
            code.append(Instruction(OpCode.HALT))
            return code

        code.append(Instruction(OpCode.REWIND, p1=0, p2=5))
        code.append(
            Instruction(
                OpCode.FILTER_COMPARE,
                p1=0,
                p2=4,
                p3=plan.schema.column_index(plan.where.column),
                p4=plan.where,
            )
        )
        code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
        code.append(Instruction(OpCode.NEXT, p1=0, p2=2))
        code.append(Instruction(OpCode.HALT))
        return code

    @staticmethod
    def disassemble(code: list[Instruction]) -> str:
        header = "ADDR OPCODE             P1   P2   P3 P4"
        lines = [header, "---- ---------------- ---- ---- ---- ------------------------------------------"]
        lines.extend(ins.render(i) for i, ins in enumerate(code))
        return "\n".join(lines)
