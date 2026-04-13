from __future__ import annotations

import threading
from typing import Any, ClassVar

import simpleeval

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class ExpressionTimeoutError(TimeoutError):
    pass


class ExpressionEngine:
    """安全表达式求值器"""

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

    def __init__(self, timeout_seconds: int = 5) -> None:
        self._timeout = timeout_seconds
        self._evaluator = simpleeval.SimpleEval()
        self._evaluator.functions = dict(self.SAFE_FUNCTIONS)

    def evaluate(self, expression: str, context: dict[str, Any]) -> Any:
        self._evaluator.names = context
        result: Any = None
        error: Exception | None = None

        def _eval() -> None:
            nonlocal result, error
            try:
                result = self._evaluator.eval(expression)
            except Exception as e:
                error = e

        thread = threading.Thread(target=_eval)
        thread.start()
        thread.join(timeout=self._timeout)

        if thread.is_alive():
            raise ExpressionTimeoutError(
                f"Expression evaluation timed out after {self._timeout}s: {expression[:100]}"
            )

        if error is not None:
            raise error

        return result
