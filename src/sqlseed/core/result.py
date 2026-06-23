"""Generation result data class.

Encapsulates statistics after executing a data generation task:
for use by upper-layer callers and CLI output.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    """Data generation result: records table name, row count, elapsed time, and error info.

    Field descriptions:
    - table_name: Target table name;
    - count: Actual number of rows generated;
    - elapsed: Generation elapsed time (seconds);
    - rows_per_second: Average generation speed (rows/sec), auto-computed by __post_init__;
    - batch_count: Number of batch writes;
    - errors: List of error messages accumulated during writes.
    """

    table_name: str
    count: int
    elapsed: float
    rows_per_second: float = 0.0
    batch_count: int = 0
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Compute average generation speed (rows/sec) after initialization."""
        if self.count > 0 and self.elapsed > 0:
            self.rows_per_second = self.count / self.elapsed

    def __str__(self) -> str:
        """Return a human-readable result summary string."""
        return (
            f"GenerationResult(table={self.table_name}, count={self.count}, "
            f"elapsed={self.elapsed:.2f}s, speed={self.rows_per_second:.2f} rows/s)"
        )
