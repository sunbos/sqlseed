from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ErrorSummary:
    error_type: str
    message: str
    column: str | None
    retryable: bool

    def to_prompt_str(self) -> str:
        parts = [f"Error Type: {self.error_type}", f"Message: {self.message}"]
        if self.column:
            parts.append(f"Affected Column: {self.column}")
        return "\n".join(parts)


def summarize_error(exc: Exception) -> ErrorSummary:
    import json as _json

    try:
        from pydantic import ValidationError

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
    except ImportError:
        pass

    if isinstance(exc, _json.JSONDecodeError):
        return ErrorSummary(
            error_type="json_syntax",
            message=f"JSON parsing failed at position {exc.pos}: {exc.msg}",
            column=None,
            retryable=True,
        )

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

    try:
        from sqlseed.generators.stream import UnknownGeneratorError
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
    except ImportError:
        pass

    exc_type_name = type(exc).__name__
    exc_module = str(getattr(type(exc), "__module__", ""))
    if "ExpressionTimeout" in exc_type_name or "simpleeval" in exc_module:
        return ErrorSummary(
            error_type="expression_error",
            message=f"Expression evaluation failed: {str(exc)[:150]}",
            column=_extract_column_from_message(str(exc)),
            retryable=True,
        )

    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return ErrorSummary(
            error_type="fatal",
            message=str(exc)[:200],
            column=None,
            retryable=False,
        )

    return ErrorSummary(
        error_type="runtime_error",
        message=f"{exc_type_name}: {str(exc)[:200]}",
        column=_extract_column_from_message(str(exc)),
        retryable=True,
    )


def _extract_column_from_pydantic_loc(loc: tuple[Any, ...]) -> str | None:
    if len(loc) >= 3 and loc[0] == "columns":
        if hasattr(loc[2], "value"):
            return loc[2].value.get("name") if isinstance(loc[2].value, dict) else str(loc[2].value)
        return str(loc[2])
    if len(loc) >= 2 and loc[0] == "columns":
        return str(loc[1])
    return None


def _extract_column_from_message(msg: str) -> str | None:
    match = re.search(r"column[:\s]+'?(\w+)'?", msg, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_generator_name(msg: str) -> str:
    match = re.search(r"generate_(\w+)", msg)
    return match.group(1) if match else "unknown"
