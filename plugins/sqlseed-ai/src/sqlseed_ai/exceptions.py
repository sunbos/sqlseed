"""Structured exception types for sqlseed-ai.

Replaces fragile string matching (e.g. ``"context" in err and "exceed" in err``)
with typed exceptions that callers can catch via ``isinstance`` / ``except``.

The classification helper :func:`classify_api_error` centralizes all string-based
detection in one place, so analyzer and refiner modules depend on typed
exceptions rather than error-message substrings.
"""

from __future__ import annotations


class SqlseedAIError(Exception):
    """Base class for all structured sqlseed-ai exceptions."""


class ContextOverflowError(SqlseedAIError):
    """Raised when the LLM context window is exceeded.

    Callers should retry with a more compact prompt (compact / ultra-compact).
    """


class ToolCallError(SqlseedAIError):
    """Raised when Gemma 4 native function calling is not supported by the endpoint.

    Callers should fall back to JSON mode or plain text mode.
    """


class ModelFallbackError(SqlseedAIError):
    """Raised when a model parameter (e.g. ``reasoning_effort``, ``response_format``)
    is not supported and the caller should retry without it.
    """


def _matches_context_overflow(err_msg: str) -> bool:
    """Return True if the error message indicates a context-window overflow."""
    return "context" in err_msg and "exceed" in err_msg


def _matches_tool_call_failure(err_msg: str) -> bool:
    """Return True if the error message indicates tool calling is unsupported."""
    return "tool" in err_msg or "function" in err_msg


def _matches_param_not_supported(err_msg: str) -> bool:
    """Return True if the error message indicates a parameter is not supported.

    Covers ``response_format`` (JSON mode), ``reasoning_effort``, and generic
    ``400 Bad Request`` responses that signal an unsupported parameter.

    Note: patterns are intentionally narrow. Bare substrings like ``"400"`` or
    ``"json"`` are NOT used because they would misclassify unrelated messages
    (e.g. "4000 tokens", "received 400 bytes", "json schema validation").
    """
    return (
        "response_format" in err_msg
        or "reasoning_effort" in err_msg
        or "json mode" in err_msg
        or "json_schema" in err_msg
        or "400 bad request" in err_msg
    )


def classify_api_error(exc: BaseException) -> SqlseedAIError | None:
    """Classify an exception into a structured sqlseed-ai error type.

    Args:
        exc: The original exception raised by the LLM client or a wrapper.

    Returns:
        The matching :class:`SqlseedAIError` subclass instance, or ``None`` if
        the exception does not match any known pattern (caller should re-raise
        the original exception).
    """
    err_msg = str(exc).lower()
    if _matches_context_overflow(err_msg):
        return ContextOverflowError(str(exc))
    if _matches_tool_call_failure(err_msg):
        return ToolCallError(str(exc))
    if _matches_param_not_supported(err_msg):
        return ModelFallbackError(str(exc))
    return None


__all__ = [
    "ContextOverflowError",
    "ModelFallbackError",
    "SqlseedAIError",
    "ToolCallError",
    "classify_api_error",
]
