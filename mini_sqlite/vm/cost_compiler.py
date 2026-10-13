from __future__ import annotations

from mini_sqlite.planner.plan import AccessPath, AnalyzePlan, JoinSelectPlan, Plan
from mini_sqlite.vm.compiler import Compiler as LegacyCompiler
from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode


class CostBasedCompiler(LegacyCompiler):
    """v0.8 compiler delta: ANALYZE plus cost-selected JOIN orientation."""

    def compile(self, plan: Plan) -> list[Instruction]:
        if isinstance(plan, AnalyzePlan):
            return [Instruction(OpCode.ANALYZE, p4=plan.table), Instruction(OpCode.HALT)]
        return super().compile(plan)

    def _join_select(self, plan: JoinSelectPlan) -> list[Instruction]:
        outer = plan.outer_side
        inner = 1 - outer
        outer_join_col = (
            plan.join.left_column_index if outer == 0 else plan.join.right_column_index
        )
        code: list[Instruction] = [
            Instruction(OpCode.OPEN_READ, p1=0, p4=plan.left_schema.name),
            Instruction(OpCode.OPEN_READ, p1=1, p4=plan.right_schema.name),
        ]
        if plan.inner_access_path == AccessPath.SECONDARY_INDEX:
            assert plan.inner_index is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=2, p4=plan.inner_index.name))

        outer_rewind = len(code)
        code.append(Instruction(OpCode.REWIND, p1=outer, p2=0))
        outer_loop = len(code)

        if plan.inner_access_path == AccessPath.PRIMARY_KEY:
            seek_addr = len(code)
            code.append(
                Instruction(
                    OpCode.SEEK_PK_FROM_COLUMN,
                    p1=inner,
                    p2=outer,
                    p3=outer_join_col,
                    p4=0,
                )
            )
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            next_outer = len(code)
            code.append(Instruction(OpCode.NEXT, p1=outer, p2=outer_loop))
            ins = code[seek_addr]
            code[seek_addr] = Instruction(ins.opcode, ins.p1, ins.p2, ins.p3, next_outer)

        elif plan.inner_access_path == AccessPath.SECONDARY_INDEX:
            seek_addr = len(code)
            code.append(
                Instruction(
                    OpCode.SEEK_INDEX_FROM_COLUMN,
                    p1=2,
                    p2=outer,
                    p3=outer_join_col,
                    p4=0,
                )
            )
            match_loop = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=2, p2=inner))
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            code.append(Instruction(OpCode.INDEX_NEXT, p1=2, p2=match_loop))
            next_outer = len(code)
            code.append(Instruction(OpCode.NEXT, p1=outer, p2=outer_loop))
            ins = code[seek_addr]
            code[seek_addr] = Instruction(ins.opcode, ins.p1, ins.p2, ins.p3, next_outer)

        else:
            inner_rewind = len(code)
            code.append(Instruction(OpCode.REWIND, p1=inner, p2=0))
            inner_loop = len(code)
            filter_addr = len(code)
            code.append(Instruction(OpCode.FILTER_JOIN_EQ, p1=0, p2=1, p3=0, p4=plan.join))
            code.append(Instruction(OpCode.COLLECT_JOIN_ROW, p1=0, p2=1))
            next_inner = len(code)
            code.append(Instruction(OpCode.NEXT, p1=inner, p2=inner_loop))
            next_outer = len(code)
            code.append(Instruction(OpCode.NEXT, p1=outer, p2=outer_loop))
            rewind = code[inner_rewind]
            code[inner_rewind] = Instruction(
                rewind.opcode, rewind.p1, next_outer, rewind.p3, rewind.p4
            )
            filt = code[filter_addr]
            code[filter_addr] = Instruction(
                filt.opcode, filt.p1, filt.p2, next_inner, filt.p4
            )

        pipeline_addr = len(code)
        rewind = code[outer_rewind]
        code[outer_rewind] = Instruction(
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
