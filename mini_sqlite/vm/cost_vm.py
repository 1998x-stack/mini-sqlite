from __future__ import annotations

from mini_sqlite.vm.instruction import Instruction
from mini_sqlite.vm.opcode import OpCode
from mini_sqlite.vm.vm import VMResult, VirtualMachine as LegacyVirtualMachine


class CostBasedVirtualMachine(LegacyVirtualMachine):
    """v0.8 VM delta: make ANALYZE a transactional catalog write."""

    def execute(self, code: list[Instruction]) -> VMResult:
        if code and code[0].opcode == OpCode.ANALYZE:
            return VMResult([], self.catalog.analyze(code[0].p4))
        return super().execute(code)
