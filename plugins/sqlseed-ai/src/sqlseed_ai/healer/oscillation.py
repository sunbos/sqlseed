"""4c: Oscillation detector.

Spec reference: Section 6.5.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


class OscillationDetector:
    """Detect A↔B alternation in error states.

    Maintains a bounded history of recent violation signatures (column +
    severity pairs). ``check_and_record`` returns True when the current
    signature either exactly matches a prior state or has overlap at or
    above ``partial_threshold`` with any prior state, indicating the
    healer is oscillating between two failure modes.
    """

    def __init__(
        self, max_history: int = 6, partial_threshold: float = 0.8
    ) -> None:
        self._history: list[frozenset[tuple[str, str]]] = []
        self._max_history = max_history
        self._partial_threshold = partial_threshold

    def check_and_record(self, violations: list[ViolationReport]) -> bool:
        """Return True if oscillation detected, else record and return False."""
        current = frozenset(
            (col, v.severity) for v in violations for col in v.columns
        )
        if current in self._history:
            logger.warning("Oscillation detected", history_len=len(self._history))
            return True
        for hist in self._history:
            overlap = len(current & hist) / max(len(current), 1)
            if overlap >= self._partial_threshold:
                logger.warning("Partial oscillation detected", overlap=overlap)
                return True
        self._history.append(current)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        return False
