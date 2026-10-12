from __future__ import annotations

from mini_sqlite.planner.plan import (
    AccessPath,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Plan,
    SelectPlan,
)
from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode


class Compiler:
    """Compiles logical plans to a tiny SQLite/VDBE-inspired bytecode."""

    def compile(self, plan: Plan) -> list[Instruction]:
        if isinstance(plan, CreateTablePlan):
            return [Instruction(OpCode.CREATE_TABLE, p4=plan), Instruction(OpCode.HALT)]
        if isinstance(plan, InsertPlan):
            return [
                Instruction(OpCode.OPEN_WRITE, p1=0, p4=plan.schema.name),
                Instruction(OpCode.INSERT_ROW, p1=0, p4=plan.values),
                Instruction(OpCode.HALT),
            ]
        if isinstance(plan, SelectPlan):
            return self._select(plan)
        if isinstance(plan, DeletePlan):
            return self._delete(plan)
        raise TypeError(f"unsupported plan {type(plan).__name__}")

    def _select(self, plan: SelectPlan) -> list[Instruction]:
        code: list[Instruction] = [Instruction(OpCode.OPEN_READ, p1=0, p4=plan.schema.name)]
        if plan.access_path == AccessPath.PRIMARY_KEY:
            key = int(plan.where.value)
            code.append(Instruction(OpCode.SEEK_PK, p1=0, p2=4, p4=key))
            code.append(Instruction(OpCode.PROJECT, p1=0, p4=plan.projection))
            code.append(Instruction(OpCode.RESULT_ROW))
            code.append(Instruction(OpCode.HALT))
            return code

        rewind_addr = len(code)
        code.append(Instruction(OpCode.REWIND, p1=0, p2=0))
        loop_addr = len(code)
        if plan.where is not None:
            column_index = plan.schema.column_index(plan.where.column)
            code.append(Instruction(OpCode.FILTER_EQ, p1=0, p2=0, p3=column_index, p4=plan.where.value))
        code.append(Instruction(OpCode.PROJECT, p1=0, p4=plan.projection))
        code.append(Instruction(OpCode.RESULT_ROW))
        next_addr = len(code)
        code.append(Instruction(OpCode.NEXT, p1=0, p2=loop_addr))
        halt_addr = len(code)
        code.append(Instruction(OpCode.HALT))
        code[rewind_addr] = Instruction(OpCode.REWIND, p1=0, p2=halt_addr)
        if plan.where is not None:
            filter_addr = loop_addr
            code[filter_addr] = Instruction(OpCode.FILTER_EQ, p1=0, p2=next_addr, p3=plan.schema.column_index(plan.where.column), p4=plan.where.value)
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

        code.append(Instruction(OpCode.REWIND, p1=0, p2=5))
        code.append(Instruction(OpCode.FILTER_EQ, p1=0, p2=4, p3=plan.schema.column_index(plan.where.column), p4=plan.where.value))
        code.append(Instruction(OpCode.DELETE_CURRENT, p1=0))
        code.append(Instruction(OpCode.NEXT, p1=0, p2=2))
        code.append(Instruction(OpCode.HALT))
        return code

    @staticmethod
    def disassemble(code: list[Instruction]) -> str:
        header = "ADDR OPCODE             P1   P2   P3 P4"
        lines = [header, "---- ---------------- ---- ---- ---- ------------------------------------------"]
        lines.extend(ins.render(i) for i, ins in enumerate(code))
        return "\n".join(lines)
