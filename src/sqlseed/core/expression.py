"""Expression evaluation engine, simpleeval sandbox.

ExpressionEngine evaluates derived column expressions in a safe sandbox,
providing 26 safe functions plus an optional ``lookup`` function for
cross-table value reference (requires a db_adapter). Simple expressions
are evaluated directly, while complex expressions are executed in a
separate thread with a timeout.
"""

from __future__ import annotations

import ast
import random
import re
import threading
from datetime import timedelta
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

    Provides 26 safe functions (len, int, str, upper, concat, random_float,
    timedelta, etc.). When a ``db_adapter`` is supplied, also exposes a
    ``lookup(table, column, key, key_column='id')`` function for cross-table
    value reference (results cached per tuple). Simple expressions (method
    chains like value.strip()) are evaluated directly in the calling thread;
    complex expressions are executed in a separate thread with a timeout,
    and the thread is abandoned on timeout (as a daemon thread).
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
        # timedelta enables date arithmetic in derived expressions, e.g.
        # ``value + timedelta(days=7)`` to add a week to a date source column.
        # Supports days/seconds/hours/minutes/weeks — the common units LLMs
        # naturally emit (hours is especially common for state-machine date
        # constraints like paid_at = created_at + timedelta(hours=N)).
        # Microseconds/milliseconds are omitted (rarely needed for test data).
        "timedelta": lambda days=0, seconds=0, hours=0, minutes=0, weeks=0: timedelta(
            days=int(days), seconds=int(seconds), hours=int(hours), minutes=int(minutes), weeks=int(weeks)
        ),
    }

    _SIMPLE_EXPR_RE: ClassVar[re.Pattern[str]] = re.compile(r"^[a-zA-Z_]\w*\s*(\.\s*[a-zA-Z_]\w*\s*\([^)]*\)\s*)+$")

    def __init__(self, timeout_seconds: int = 5, db_adapter: DatabaseAdapter | None = None) -> None:
        """Initialize the expression engine.

        Args:
            timeout_seconds: Timeout for complex expression evaluation in seconds.
            db_adapter: Optional database adapter. When provided, enables the
                ``lookup(table, column, key, key_column='id')`` function for
                cross-table value reference in derived expressions.
        """
        self._timeout = timeout_seconds
        self._db_adapter = db_adapter
        self._lookup_cache: dict[tuple[str, str, Any, str], Any] = {}

    def _get_functions(self) -> dict[str, Any]:
        """Build the functions dict, conditionally including ``lookup``."""
        funcs = dict(self.SAFE_FUNCTIONS)
        if self._db_adapter is not None:
            funcs["lookup"] = self._lookup
        return funcs

    def _configure_evaluator(self, evaluator: simpleeval.SimpleEval) -> None:
        """Add list/tuple literal support to a simpleeval evaluator.

        The default simpleeval ``nodes`` dict does not include handlers for
        ``ast.List`` or ``ast.Tuple``, so expressions like
        ``value in ['captain', 'first_officer']`` raise
        ``FeatureNotAvailable: List is not available``. This method adds
        safe handlers that evaluate each element in the sandbox (so nested
        function calls and names still work) and return a Python list/tuple.

        This enables natural ``in`` membership tests in derived expressions,
        which both the AI auto-heal pipeline and user-written YAML configs
        commonly produce.
        """
        evaluator.nodes[ast.List] = lambda node: [evaluator._eval(e) for e in node.elts]
        evaluator.nodes[ast.Tuple] = lambda node: tuple(evaluator._eval(e) for e in node.elts)

    def _lookup(self, table: str, column: str, key: Any, key_column: str = "id") -> Any:
        """Look up a single value from another table by a key column.

        Executes ``SELECT {column} FROM {table} WHERE {key_column} = ?`` and
        returns the scalar value. Results are cached per
        ``(table, column, key, key_column)`` tuple to avoid repeated DB hits
        within the same generation run.

        This is a generic mechanism — it does NOT encode any business logic.
        Business relationships (which table/column to look up) are expressed
        by the user in YAML ``derive_from + expression`` configuration.

        Args:
            table: Source table name.
            column: Source column name to read.
            key: Key value to look up (matched against ``key_column``).
            key_column: Name of the column to match ``key`` against.
                Defaults to ``"id"`` (the conventional primary key name).
                Useful when a table uses a non-standard primary key column
                (e.g. ``user_id``, ``sku``) or when looking up by a unique
                non-PK column.

        Returns:
            The scalar value of ``column`` for the row whose
            ``key_column == key``, or ``None`` if no such row exists.
        """
        cache_key = (table, column, key, key_column)
        if cache_key in self._lookup_cache:
            return self._lookup_cache[cache_key]
        sql = (
            f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)} WHERE {quote_identifier(key_column)} = ?"
        )
        cursor = self._db_adapter.execute(sql, (key,))  # type: ignore[union-attr]
        try:
            row = cursor.fetchone()
            result = row[0] if row else None
        finally:
            # Close cursor so the underlying DBAPI connection is returned
            # to the pool promptly (see SQLAlchemyAdapter.execute docstring).
            cursor.close()
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
        self._configure_evaluator(evaluator)
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
        self._configure_evaluator(evaluator)
        result_container: list[Any] = [None]
        error_container: list[Exception | None] = [None]

        def _eval() -> None:
            try:
                result_container[0] = evaluator.eval(expression)
            except (ValueError, SyntaxError, TypeError, simpleeval.InvalidExpression) as e:
                error_container[0] = e

        # daemon=True ensures the thread cannot block interpreter shutdown
        # if simpleeval gets stuck (deep recursion / infinite loop). The
        # thread is abandoned on timeout and will be cleaned up by the OS
        # when the process exits.
        thread = threading.Thread(target=_eval, daemon=True)
        thread.start()
        thread.join(timeout=self._timeout)

        if thread.is_alive():
            raise ExpressionTimeoutError(f"Expression evaluation timed out after {self._timeout}s: {expression[:100]}")

        error = error_container[0]
        if error is not None:
            raise error

        return result_container[0]
