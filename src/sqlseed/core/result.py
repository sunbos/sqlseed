from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    table_name: str
    count: int
    elapsed: float
    rows_per_second: float = 0.0
    batch_count: int = 0
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.count > 0 and self.elapsed > 0:
            self.rows_per_second = self.count / self.elapsed

    def __str__(self) -> str:
        return (
            f"GenerationResult(table={self.table_name}, count={self.count}, "
            f"elapsed={self.elapsed:.2f}s, speed={self.rows_per_second:.0f} rows/s)"
        )
