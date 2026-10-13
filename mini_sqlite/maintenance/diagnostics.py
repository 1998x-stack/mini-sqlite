from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExplainAnalyzeResult:
    plan: str
    bytecode: str
    actual_rows: int
    elapsed_ms: float
    buffer_hits: int
    buffer_misses: int
    buffer_evictions: int
    buffer_dirty_evictions: int

    def render(self) -> str:
        return "\n".join(
            [
                f"PLAN {self.plan}",
                (
                    f"ACTUAL rows={self.actual_rows} elapsed_ms={self.elapsed_ms:.3f} "
                    f"buffer_hits=+{self.buffer_hits} buffer_misses=+{self.buffer_misses} "
                    f"evictions=+{self.buffer_evictions} "
                    f"dirty_evictions=+{self.buffer_dirty_evictions}"
                ),
                "BYTECODE",
                self.bytecode,
            ]
        )


@dataclass(frozen=True)
class VacuumResult:
    before_pages: int
    after_pages: int

    @property
    def reclaimed_pages(self) -> int:
        return max(0, self.before_pages - self.after_pages)

    def render(self) -> str:
        return (
            f"before_pages={self.before_pages} after_pages={self.after_pages} "
            f"reclaimed_pages={self.reclaimed_pages}"
        )
