from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mini_sqlite.vm.opcode import OpCode


@dataclass(frozen=True)
class Instruction:
    opcode: OpCode
    p1: int = 0
    p2: int = 0
    p3: int = 0
    p4: Any = None

    def render(self, addr: int) -> str:
        p4 = "" if self.p4 is None else repr(self.p4)
        if len(p4) > 42:
            p4 = p4[:39] + "..."
        return f"{addr:>4} {self.opcode.name:<16} {self.p1:>4} {self.p2:>4} {self.p3:>4} {p4}"
