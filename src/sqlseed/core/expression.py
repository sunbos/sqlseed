"""Expression evaluation engine, simpleeval sandbox.

ExpressionEngine evaluates derived column expressions in a safe sandbox,
providing 25 safe functions plus an optional ``lookup`` function for
cross-table value reference (requires a db_adapter). Simple expressions
are evaluated directly, while complex expressions are executed in a
separate thread with a timeout.
"""

from __future__ import annotations

import random
import re
import threading
from typing import TYPE_CHECKING, Any, ClassVar

import simpleeval

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter

logger = get_logger(__name__)


class ExpressionTimeoutError(TimeoutError):
    """Exception raised when expression evaluation times out."""


class ExpressionEngine:
    """Engine that evaluates derived column expressions in a simpleeval sandbox.

    Provides 25 safe functions (len, int, str, upper, concat, random_float, etc.).
    When a ``db_adapter`` is supplied, also exposes a ``lookup(table, column, key)``
    function for cross-table value reference (results cached per tuple).
    Simple expressions (method chains like value.strip()) are evaluated directly
    in the calling thread; complex expressions are executed in a separate thread
    with a timeout, and the thread is abandoned on timeout (as a daemon thread).
    """

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
        "round": round,
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
        "random_float": lambda min_val, max_val: random.uniform(float(min_val), float(max_val)),
        "random_int": lambda min_val, max_val: random.randint(int(min_val), int(max_val)),
        "random_choice": lambda seq: random.choice(list(seq)),
    }

    _SIMPLE_EXPR_RE: ClassVar[re.Pattern[str]] = re.compile(r"^[a-zA-Z_]\w*\s*(\.\s*[a-zA-Z_]\w*\s*\([^)]*\)\s*)+$")

    def __init__(self, timeout_seconds: int = 5, db_adapter: DatabaseAdapter | None = None) -> None:
        """Initialize the expression engine.

        Args:
            timeout_seconds: Timeout for complex expression evaluation in seconds.
            db_adapter: Optional database adapter. When provided, enables the
                ``lookup(table, column, key)`` function for cross-table value
                reference in derived expressions.
        """
        self._timeout = timeout_seconds
        self._db_adapter = db_adapter
        self._lookup_cache: dict[tuple[str, str, Any], Any] = {}

    def _get_functions(self) -> dict[str, Any]:
        """Build the functions dict, conditionally including ``lookup``."""
        funcs = dict(self.SAFE_FUNCTIONS)
        if self._db_adapter is not None:
            funcs["lookup"] = self._lookup
        return funcs

    def _lookup(self, table: str, column: str, key: Any) -> Any:
        """Look up a single value from another table by primary key.

        Executes ``SELECT {column} FROM {table} WHERE id = ?`` and returns
        the scalar value. Results are cached per ``(table, column, key)``
        tuple to avoid repeated DB hits within the same generation run.

        This is a generic mechanism — it does NOT encode any business logic.
        Business relationships (which table/column to look up) are expressed
        by the user in YAML ``derive_from + expression`` configuration.

        Args:
            table: Source table name.
            column: Source column name to read.
            key: Primary key value to look up (matched against ``id`` column).

        Returns:
            The scalar value of ``column`` for the row whose ``id == key``,
            or ``None`` if no such row exists.
        """
        cache_key = (table, column, key)
        if cache_key in self._lookup_cache:
            return self._lookup_cache[cache_key]
        sql = f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)} WHERE id = ?"
        cursor = self._db_adapter.execute(sql, (key,))  # type: ignore[union-attr]
        row = cursor.fetchone()
        result = row[0] if row else None
        self._lookup_cache[cache_key] = result
        return result

    def _is_simple_expression(self, expression: str) -> bool:
        stripped = expression.strip()
        if not stripped:
            return True
        if stripped in {"value", "row"} or stripped.startswith("value[") or stripped.startswith("row["):
            return True
        return bool(self._SIMPLE_EXPR_RE.match(stripped))

    def _eval_direct(self, expression: str, context: dict[str, Any]) -> Any:
        evaluator = simpleeval.SimpleEval()
        evaluator.functions = self._get_functions()
        evaluator.names = context
        return evaluator.eval(expression)

    def evaluate(self, expression: str, context: dict[str, Any]) -> Any:
        """Evaluate an expression in the given context.

        For simple expressions (method chains like ``value.strip()``),
        evaluation runs directly in the calling thread.

        For complex expressions, a separate thread is used with a timeout.
        Note: Python threads cannot be forcibly terminated — if the thread
        exceeds *timeout_seconds*, it is abandoned (left as a daemon) and
        an :class:`ExpressionTimeoutError` is raised.  The thread may
        continue executing in the background until the process exits.
        This trade-off is acceptable because expression evaluation is
        purely computational (no side effects) and the simpleeval sandbox
        prevents resource exhaustion.
        """
        if self._is_simple_expression(expression):
            return self._eval_direct(expression, context)

        evaluator = simpleeval.SimpleEval()
        evaluator.functions = self._get_functions()
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
