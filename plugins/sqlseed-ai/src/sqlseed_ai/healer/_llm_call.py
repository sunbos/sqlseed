"""Shared RPC failure policy and timing for the three LLM healer levels."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class LLMCallOutcome:
    """An unvalidated client response or the original recoverable RPC failure."""

    response: Any
    error: Exception | None
    elapsed_seconds: float


def call_llm(
    request: Callable[[], Any], *, started_at: float, on_failure: Callable[[Exception], None]
) -> LLMCallOutcome:
    """Call once, preserving network propagation and failure-log accounting order.

    The deferred request includes argument evaluation. Response inspection and
    client ownership remain with the caller, as in the LLMClient protocol.
    """
    try:
        response = request()
    except (RuntimeError, AttributeError, ValueError) as exc:
        if issubclass(type(exc), OSError):
            raise
        on_failure(exc)
        return LLMCallOutcome(None, exc, time.monotonic() - started_at)
    return LLMCallOutcome(response, None, time.monotonic() - started_at)
