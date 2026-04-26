from __future__ import annotations

import re
import threading
from typing import Any, ClassVar

import simpleeval

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class ExpressionTimeoutError(TimeoutError):
    pass


class ExpressionEngine:
    SAFE_FUNCTIONS: ClassVar[dict[str, Any]] = {
        "len": len,
        "int": int,
        "str": str,
        "float": float,
        "hex": hex,
        "oct": oct,
        "bin": bin,
        "abs": abs,
        "min": min,
        "max": max,
        "upper": lambda s: s.upper(),
        "lower": lambda s: s.lower(),
        "strip": lambda s: s.strip(),
        "lstrip": lambda s: s.lstrip(),
        "rstrip": lambda s: s.rstrip(),
        "zfill": lambda s, w: str(s).zfill(w),
        "replace": lambda s, old, new: str(s).replace(old, new),
        "substr": lambda s, start, end=None: str(s)[start:end],
        "lpad": lambda s, width, char="0": str(s).rjust(width, char),
        "rpad": lambda s, width, char="0": str(s).ljust(width, char),
        "concat": lambda *args: "".join(str(a) for a in args),
    }

    _SIMPLE_EXPR_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-zA-Z_][a-zA-Z0-9_]*\s*(\.\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)\s*)+$"
    )

    def __init__(self, timeout_seconds: int = 5) -> None:
        self._timeout = timeout_seconds

    def _is_simple_expression(self, expression: str) -> bool:
        stripped = expression.strip()
        if not stripped:
            return True
        if stripped in ("value", "row") or stripped.startswith("value[") or stripped.startswith("row["):
            return True
        return bool(self._SIMPLE_EXPR_RE.match(stripped))

    def _eval_direct(self, expression: str, context: dict[str, Any]) -> Any:
        evaluator = simpleeval.SimpleEval()
        evaluator.functions = dict(self.SAFE_FUNCTIONS)
        evaluator.names = context
        return evaluator.eval(expression)

    def evaluate(self, expression: str, context: dict[str, Any]) -> Any:
        if self._is_simple_expression(expression):
            try:
                return self._eval_direct(expression, context)
            except (ValueError, SyntaxError, TypeError, simpleeval.InvalidExpression) as e:
                raise e

        evaluator = simpleeval.SimpleEval()
        evaluator.functions = dict(self.SAFE_FUNCTIONS)
        evaluator.names = context
        result_container: list[Any] = [None]
        error_container: list[Exception | None] = [None]

        def _eval() -> None:
            try:
                result_container[0] = evaluator.eval(expression)
            except (ValueError, SyntaxError, TypeError, simpleeval.InvalidExpression) as e:
                error_container[0] = e

        thread = threading.Thread(target=_eval)
        thread.start()
        thread.join(timeout=self._timeout)

        if thread.is_alive():
            raise ExpressionTimeoutError(f"Expression evaluation timed out after {self._timeout}s: {expression[:100]}")

        error = error_container[0]
        if error is not None:
            raise error

        return result_container[0]
