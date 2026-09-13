"""TimeBudgetController — per-table dynamic time allocation.

Spec reference: Section 13.

Spans all layers: when the total budget is exhausted, the orchestrator
falls back to deterministic generation (Layer 4d ProgressiveDegrade) for
any remaining tables.
"""

from __future__ import annotations

import time

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class TimeBudgetController:
    """Track remaining time budget across the auto-heal pipeline."""

    def __init__(self, *, total_seconds: float, table_count: int) -> None:
        self._start = time.monotonic()
        self._total = total_seconds
        self._table_count = max(table_count, 1)  # avoid div-by-zero

    def per_table_budget(self) -> float:
        """Return the per-table budget (total / table_count)."""
        return self._total / self._table_count

    def time_remaining(self) -> float:
        """Return remaining time in seconds (clamped to >= 0)."""
        elapsed = time.monotonic() - self._start
        return max(0.0, self._total - elapsed)

    def is_expired(self) -> bool:
        """Return True if the budget is exhausted."""
        return self.time_remaining() <= 0.0

    def extend(self, additional_seconds: float) -> None:
        """Extend the total budget (e.g., for retry allocation)."""
        self._total += additional_seconds
        logger.info("Extended time budget", added=additional_seconds, new_total=self._total)
