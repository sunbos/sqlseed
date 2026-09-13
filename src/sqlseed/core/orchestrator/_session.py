"""Per-fill accounting through successful commits and terminal failure."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlseed.core.result import GenerationResult
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from types import TracebackType


@dataclass
class FillSession:
    """Own the report of one fill without claiming transaction-wide atomicity.

    The insertion loop advances counters only after the adapter acknowledges
    a batch. Operational failures become the terminal result; configuration
    errors and process-control exceptions continue to the caller.
    """

    rows: int = 0
    batches: int = 0
    started: float = field(default_factory=time.monotonic)
    elapsed: float = 0.0
    error: Exception | None = None

    def __enter__(self) -> FillSession:
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if not isinstance(error, Exception) or isinstance(error, ConfigurationError):
            return False
        self.error = error
        self.elapsed = time.monotonic() - self.started
        return True

    def result(self, table_name: str) -> GenerationResult:
        """Build the same accounting report on both successful and failed fills."""
        return GenerationResult(
            table_name=table_name,
            count=self.rows,
            elapsed=self.elapsed,
            batch_count=self.batches,
            errors=[str(self.error)] if self.error is not None else [],
        )
