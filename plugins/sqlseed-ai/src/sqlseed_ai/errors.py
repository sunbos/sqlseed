"""Error summarization for LLM-driven schema analysis.

This module converts exceptions raised during schema analysis and
template generation into structured :class:`ErrorSummary` objects that
can be fed back to the LLM as retry context. A chain of single-purpose
``_try_*`` handlers inspects the exception type and message; the first
matching handler wins, and a catch-all :func:`_default_error` handles
everything else.
"""

from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from sqlseed.generators import UnknownGeneratorError

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class ErrorSummary:
    """Structured summary of an error, suitable for LLM retry prompts.

    Attributes:
        error_type: Short label categorizing the error (e.g.,
            "pydantic_validation", "json_syntax", "unknown_generator").
        message: Human-readable description, truncated for prompt safety.
        column: Name of the affected column, if identifiable.
        retryable: Whether the LLM should retry after seeing this error.
    """

    error_type: str
    message: str
    column: str | None
    retryable: bool

    def to_prompt_str(self) -> str:
        """Render the summary as a multi-line string for an LLM prompt."""
        parts = [f"Error Type: {self.error_type}", f"Message: {self.message}"]
        if self.column:
            parts.append(f"Affected Column: {self.column}")
        return "\n".join(parts)


def summarize_error(exc: Exception) -> ErrorSummary:
    """Classify an exception into an :class:`ErrorSummary`.

    Runs the exception through a chain of ``_try_*`` handlers and
    returns the first non-None result. Falls back to
    :func:`_default_error` when no handler matches.
    """
    handlers: list[Callable[[Exception], ErrorSummary | None]] = [
        _try_pydantic_error,
        _try_json_error,
        _try_attribute_generator_error,
        _try_unknown_generator_error,
        _try_expression_error,
        _try_file_error,
    ]
    for handler in handlers:
        result = handler(exc)
        if result is not None:
            return result
    return _default_error(exc)


def _try_pydantic_error(exc: Exception) -> ErrorSummary | None:
    """Handle pydantic ValidationError (schema/template validation)."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = " → ".join(str(part) for part in first["loc"])
        col_name = _extract_column_from_pydantic_loc(first["loc"])
        return ErrorSummary(
            error_type="pydantic_validation",
            message=f"Field '{loc}': {first['msg']} (type={first['type']})",
            column=col_name,
            retryable=True,
        )
    return None


def _try_json_error(exc: Exception) -> ErrorSummary | None:
    """Handle JSONDecodeError (malformed LLM output)."""
    if isinstance(exc, _json.JSONDecodeError):
        return ErrorSummary(
            error_type="json_syntax",
            message=f"JSON parsing failed at position {exc.pos}: {exc.msg}",
            column=None,
            retryable=True,
        )
    return None


def _try_attribute_generator_error(exc: Exception) -> ErrorSummary | None:
    """Handle AttributeError referencing a missing generate_* method."""
    if isinstance(exc, AttributeError) and "generate_" in str(exc):
        gen_name = _extract_generator_name(str(exc))
        return ErrorSummary(
            error_type="unknown_generator",
            message=(
                f"Generator '{gen_name}' does not exist. "
                "Use one of the available generators listed in the system prompt."
            ),
            column=None,
            retryable=True,
        )
    return None


def _try_unknown_generator_error(exc: Exception) -> ErrorSummary | None:
    """Handle UnknownGeneratorError raised by the generator registry."""
    if isinstance(exc, UnknownGeneratorError):
        return ErrorSummary(
            error_type="unknown_generator",
            message=(
                f"Generator '{exc.generator_name}' does not exist. "
                "Use one of the available generators listed in the system prompt."
            ),
            column=exc.column_name,
            retryable=True,
        )
    return None


def _try_expression_error(exc: Exception) -> ErrorSummary | None:
    """Handle errors from simpleeval expression evaluation (incl. timeouts)."""
    exc_type_name = type(exc).__name__
    exc_module = str(getattr(type(exc), "__module__", ""))
    if "ExpressionTimeout" in exc_type_name or "simpleeval" in exc_module:
        return ErrorSummary(
            error_type="expression_error",
            message=f"Expression evaluation failed: {str(exc)[:150]}",
            column=_extract_column_from_message(str(exc)),
            retryable=True,
        )
    return None


def _try_file_error(exc: Exception) -> ErrorSummary | None:
    """Handle FileNotFoundError / PermissionError as non-retryable fatal errors."""
    if isinstance(exc, FileNotFoundError | PermissionError):
        return ErrorSummary(
            error_type="fatal",
            message=str(exc)[:200],
            column=None,
            retryable=False,
        )
    return None


def _default_error(exc: Exception) -> ErrorSummary:
    """Catch-all handler for unrecognized exceptions.

    Infrastructure errors (no model available, missing API key) are
    marked non-retryable; everything else is retryable.
    """
    exc_type_name = type(exc).__name__
    msg = str(exc)
    # Infrastructure errors (no model available, backend unreachable) should not be retried
    is_infrastructure = (
        "No other model available" in msg
        or "No more models available" in msg
        or "Only one model available" in msg
        or "API key not configured" in msg
    )
    return ErrorSummary(
        error_type="runtime_error",
        message=f"{exc_type_name}: {msg[:200]}",
        column=_extract_column_from_message(msg),
        retryable=not is_infrastructure,
    )


def _extract_column_from_pydantic_loc(loc: tuple[Any, ...]) -> str | None:
    """Extract a column name from a pydantic error location tuple."""
    if len(loc) >= 3 and loc[0] == "columns":
        if hasattr(loc[2], "value"):
            return loc[2].value.get("name") if isinstance(loc[2].value, dict) else str(loc[2].value)
        return str(loc[2])
    if len(loc) >= 2 and loc[0] == "columns":
        return str(loc[1])
    return None


def _extract_column_from_message(msg: str) -> str | None:
    """Extract a column name from an error message via regex."""
    match = re.search(r"column[:\s]+'?(\w+)'?", msg, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_generator_name(msg: str) -> str:
    """Extract the generator name from a ``generate_*`` attribute error."""
    match = re.search(r"generate_(\w+)", msg)
    return match.group(1) if match else "unknown"
