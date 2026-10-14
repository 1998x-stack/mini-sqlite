from __future__ import annotations

from mini_sqlite.planner.indexing import find_equality
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
from mini_sqlite.sql.ast import ComparisonPredicate
from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode


class Compiler:
    """Compile logical plans to tiny VDBE-inspired bytecode."""

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
            key = find_equality(plan.where, plan.schema.primary_key.name)
            assert key is not None
            seek_addr = len(code)
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=0, p4=int(key)))
            pipeline_jump_sites.append(seek_addr)
            if plan.where is not None and not isinstance(plan.where, ComparisonPredicate):
                filt = len(code)
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
                pipeline_jump_sites.append(filt)
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))

        elif plan.access_path in (AccessPath.SECONDARY_INDEX, AccessPath.SECONDARY_INDEX_RANGE):
            assert plan.index is not None and plan.index_probe is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            seek_addr = len(code)
            if plan.access_path == AccessPath.SECONDARY_INDEX:
                value = plan.index_probe.equality_values[0]
                code.append(Instruction(OpCode.SEEK_INDEX_EQ, p1=1, p2=0, p4=value))
            else:
                code.append(
                    Instruction(OpCode.SEEK_INDEX_RANGE, p1=1, p2=0, p4=plan.index_probe)
                )
            pipeline_jump_sites.append(seek_addr)
            loop_addr = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            filter_addr = -1
            if plan.where is not None and not isinstance(plan.where, ComparisonPredicate):
                filter_addr = len(code)
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))
            next_addr = len(code)
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=loop_addr))
            if filter_addr >= 0:
                ins = code[filter_addr]
                code[filter_addr] = Instruction(ins.opcode, ins.p1, next_addr, ins.p3, ins.p4)

        else:
            rewind_addr = len(code)
            code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
            pipeline_jump_sites.append(rewind_addr)
            loop_addr = len(code)
            filter_addr = -1
            if isinstance(plan.where, ComparisonPredicate):
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
            elif plan.where is not None:
                filter_addr = len(code)
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
            code.append(Instruction(OpCode.COLLECT_ROW, p1=0))
            next_addr = len(code)
            code.append(Instruction(OpCode.NEXT, p1=0, p2=loop_addr))
            if filter_addr >= 0:
                ins = code[filter_addr]
                code[filter_addr] = Instruction(ins.opcode, ins.p1, next_addr, ins.p3, ins.p4)

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
            key = find_equality(plan.where, plan.schema.primary_key.name)
            assert key is not None
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=4, p4=int(key)))
            if not isinstance(plan.where, ComparisonPredicate):
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=4, p4=plan.where))
            code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path in (AccessPath.SECONDARY_INDEX, AccessPath.SECONDARY_INDEX_RANGE):
            assert plan.index is not None and plan.index_probe is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            seek_addr = len(code)
            seek_op = (
                OpCode.SEEK_INDEX_EQ
                if plan.access_path == AccessPath.SECONDARY_INDEX
                else OpCode.SEEK_INDEX_RANGE
            )
            seek_payload = (
                plan.index_probe.equality_values[0]
                if seek_op == OpCode.SEEK_INDEX_EQ
                else plan.index_probe
            )
            code.append(Instruction(seek_op, p1=1, p2=0, p4=seek_payload))
            loop_addr = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            filter_addr = -1
            if not isinstance(plan.where, ComparisonPredicate):
                filter_addr = len(code)
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
            code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
            next_addr = len(code)
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=loop_addr))
            halt = len(code)
            code.append(Instruction(OpCode.HALT))
            ins = code[seek_addr]
            code[seek_addr] = Instruction(ins.opcode, ins.p1, halt, ins.p3, ins.p4)
            if filter_addr >= 0:
                ins = code[filter_addr]
                code[filter_addr] = Instruction(ins.opcode, ins.p1, next_addr, ins.p3, ins.p4)
            return code

        code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
        loop_addr = len(code)
        filter_addr = len(code)
        if isinstance(plan.where, ComparisonPredicate):
            code.append(Instruction(OpCode.FILTER_COMPARE, p1=0, p2=0, p3=plan.schema.column_index(plan.where.column), p4=plan.where))
        else:
            code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
        code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
        next_addr = len(code)
        code.append(Instruction(OpCode.NEXT, p1=0, p2=loop_addr))
        halt = len(code)
        code.append(Instruction(OpCode.HALT))
        rw=code[1]; code[1]=Instruction(rw.opcode,rw.p1,halt,rw.p3,rw.p4)
        flt=code[filter_addr]; code[filter_addr]=Instruction(flt.opcode,flt.p1,next_addr,flt.p3,flt.p4)
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
            key = find_equality(plan.where, plan.schema.primary_key.name)
            assert key is not None
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=4, p4=int(key)))
            if not isinstance(plan.where, ComparisonPredicate):
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=4, p4=plan.where))
            code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
            code.append(Instruction(OpCode.HALT))
            return code
        if plan.access_path in (AccessPath.SECONDARY_INDEX, AccessPath.SECONDARY_INDEX_RANGE):
            assert plan.index is not None and plan.index_probe is not None
            code.append(Instruction(OpCode.OPEN_INDEX, p1=1, p4=plan.index.name))
            seek_addr = len(code)
            seek_op = OpCode.SEEK_INDEX_EQ if plan.access_path == AccessPath.SECONDARY_INDEX else OpCode.SEEK_INDEX_RANGE
            payload = plan.index_probe.equality_values[0] if seek_op == OpCode.SEEK_INDEX_EQ else plan.index_probe
            code.append(Instruction(seek_op, p1=1, p2=0, p4=payload))
            loop_addr = len(code)
            code.append(Instruction(OpCode.INDEX_TO_TABLE, p1=1, p2=0))
            filter_addr = -1
            if not isinstance(plan.where, ComparisonPredicate):
                filter_addr = len(code)
                code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
            code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
            next_addr = len(code)
            code.append(Instruction(OpCode.INDEX_NEXT, p1=1, p2=loop_addr))
            halt = len(code)
            code.append(Instruction(OpCode.HALT))
            ins=code[seek_addr]; code[seek_addr]=Instruction(ins.opcode,ins.p1,halt,ins.p3,ins.p4)
            if filter_addr >= 0:
                ins=code[filter_addr]; code[filter_addr]=Instruction(ins.opcode,ins.p1,next_addr,ins.p3,ins.p4)
            return code

        code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
        loop_addr = len(code)
        filter_addr = len(code)
        if isinstance(plan.where, ComparisonPredicate):
            code.append(Instruction(OpCode.FILTER_COMPARE, p1=0, p2=0, p3=plan.schema.column_index(plan.where.column), p4=plan.where))
        else:
            code.append(Instruction(OpCode.FILTER_PREDICATE, p1=0, p2=0, p4=plan.where))
        code.append(Instruction(OpCode.UPDATE_CURRENT, p1=0, p4=plan.assignments))
        next_addr = len(code)
        code.append(Instruction(OpCode.NEXT, p1=0, p2=loop_addr))
        halt = len(code)
        code.append(Instruction(OpCode.HALT))
        rw=code[1]; code[1]=Instruction(rw.opcode,rw.p1,halt,rw.p3,rw.p4)
        flt=code[filter_addr]; code[filter_addr]=Instruction(flt.opcode,flt.p1,next_addr,flt.p3,flt.p4)
        return code

    @staticmethod
    def disassemble(code: list[Instruction]) -> str:
        header = "ADDR OPCODE             P1   P2   P3 P4"
        lines = [header, "---- ---------------- ---- ---- ---- ------------------------------------------"]
        lines.extend(ins.render(i) for i, ins in enumerate(code))
        return "\n".join(lines)
