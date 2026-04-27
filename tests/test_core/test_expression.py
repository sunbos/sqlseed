from __future__ import annotations

import time

import pytest
import simpleeval

from sqlseed.core.expression import ExpressionEngine, ExpressionTimeoutError


class TestExpressionEngine:
    def test_slice_expression(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("value[-8:]", {"value": "1A2B3C4D5E"})
        assert result == "2B3C4D5E"

    def test_function_call(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("upper(value)", {"value": "hello"})
        assert result == "HELLO"

    def test_nested_expression(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("hex(int(value))", {"value": "255"})
        assert result == "0xff"

    def test_concat(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("concat('PREFIX_', value)", {"value": "123"})
        assert result == "PREFIX_123"

    def test_replace(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("replace(value, '-', '')", {"value": "1-2-3"})
        assert result == "123"

    def test_zfill(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("zfill(value, 8)", {"value": "42"})
        assert result == "00000042"

    def test_substr(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("substr(value, 0, 3)", {"value": "ABCDEF"})
        assert result == "ABC"

    def test_lpad(self) -> None:
        engine = ExpressionEngine()
        result = engine.evaluate("lpad(value, 6)", {"value": "42"})
        assert result == "000042"

    def test_undefined_variable_raises(self) -> None:
        engine = ExpressionEngine()
        with pytest.raises(simpleeval.NameNotDefined):
            engine.evaluate("undefined_var + 1", {})

    def test_timeout_on_slow_expression(self) -> None:
        engine = ExpressionEngine(timeout_seconds=1)
        original_functions = dict(ExpressionEngine.SAFE_FUNCTIONS)
        ExpressionEngine.SAFE_FUNCTIONS["slow_fn"] = lambda: time.sleep(5)
        try:
            with pytest.raises(ExpressionTimeoutError):
                engine.evaluate("slow_fn()", {})
        finally:
            ExpressionEngine.SAFE_FUNCTIONS = original_functions

    def test_no_timeout_on_fast_expression(self) -> None:
        engine = ExpressionEngine(timeout_seconds=5)
        result = engine.evaluate("value[-8:]", {"value": "1A2B3C4D5E"})
        assert result == "2B3C4D5E"

    def test_timeout_error_message_contains_expression(self) -> None:
        engine = ExpressionEngine(timeout_seconds=1)
        original_functions = dict(ExpressionEngine.SAFE_FUNCTIONS)
        ExpressionEngine.SAFE_FUNCTIONS["slow_fn"] = lambda: time.sleep(5)
        try:
            with pytest.raises(ExpressionTimeoutError, match="timed out"):
                engine.evaluate("slow_fn()", {})
        finally:
            ExpressionEngine.SAFE_FUNCTIONS = original_functions

    def test_default_timeout_is_5_seconds(self) -> None:
        engine = ExpressionEngine()
        assert engine._timeout == 5

    def test_custom_timeout(self) -> None:
        engine = ExpressionEngine(timeout_seconds=10)
        assert engine._timeout == 10

    def test_safe_function_whitelist(self) -> None:
        engine = ExpressionEngine()
        assert "len" in engine.SAFE_FUNCTIONS
        assert "upper" in engine.SAFE_FUNCTIONS
        assert "replace" in engine.SAFE_FUNCTIONS
