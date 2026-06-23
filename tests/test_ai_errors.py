"""Tests for error classification handlers in errors.py.

Covers the ``_try_unknown_generator_error``, ``_try_expression_error``,
and ``_extract_column_from_message`` handlers that are not exercised by
``test_refiner.py``.
"""

from __future__ import annotations

import pytest

from sqlseed.generators import UnknownGeneratorError

try:
    from sqlseed_ai.errors import (
        _extract_column_from_message,
        _try_expression_error,
        _try_unknown_generator_error,
    )
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestTryUnknownGeneratorError:
    def test_try_unknown_generator_error_matches(self) -> None:
        """UnknownGeneratorError is classified with generator name and column."""
        exc = UnknownGeneratorError("project_identifier", column_name="project_no")
        summary = _try_unknown_generator_error(exc)
        assert summary is not None
        assert summary.error_type == "unknown_generator"
        assert "project_identifier" in summary.message
        assert summary.column == "project_no"
        assert summary.retryable is True

    def test_try_unknown_generator_error_no_match(self) -> None:
        """Non-UnknownGeneratorError exceptions return None."""
        exc = ValueError("not a generator error")
        result = _try_unknown_generator_error(exc)
        assert result is None


class TestTryExpressionError:
    def test_try_expression_error_matches(self) -> None:
        """simpleeval exceptions are classified as expression_error.

        Covers NameNotDefined and FunctionNotDefined, the two most common
        simpleeval errors raised during expression evaluation.
        """
        import simpleeval  # noqa: PLC0415

        # NameNotDefined: raised when a name is not in the evaluation context
        name_exc = simpleeval.NameNotDefined("undefined_var", "expression")
        name_summary = _try_expression_error(name_exc)
        assert name_summary is not None
        assert name_summary.error_type == "expression_error"
        assert name_summary.retryable is True

        # FunctionNotDefined: raised when a function is not registered
        func_exc = simpleeval.FunctionNotDefined("foo", "expression")
        func_summary = _try_expression_error(func_exc)
        assert func_summary is not None
        assert func_summary.error_type == "expression_error"
        assert func_summary.retryable is True


class TestExtractColumnFromMessage:
    def test_extract_column_from_message_finds_column(self) -> None:
        """Column name is extracted from messages containing 'column' keyword."""
        msg = "Error evaluating expression for column 'user_id': name not defined"
        result = _extract_column_from_message(msg)
        assert result == "user_id"

    def test_extract_column_from_message_returns_none(self) -> None:
        """None is returned when no column reference is in the message."""
        msg = "Generator 'foo' does not exist"
        result = _extract_column_from_message(msg)
        assert result is None
