"""Bulk write performance optimizer protocol.

Abstracts bulk write optimization strategies across databases:
- SQLite: PRAGMA synchronous = OFF, journal_mode = MEMORY
- PostgreSQL: SET synchronous_commit = OFF
- MySQL: SET unique_checks = 0, foreign_key_checks = 0

Phase 1 defines the protocol and SQLiteBulkOptimizer (delegating to the existing PragmaOptimizer).
Phase 3 adds PostgresBulkOptimizer; MySQLBulkOptimizer is left for future work.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.database.optimizer import PragmaOptimizer


@runtime_checkable
class BulkWriteOptimizer(Protocol):
    """Bulk write performance optimizer protocol.

    Lifecycle:
        preserve()  -> save current database configuration
        optimize()  -> apply bulk write optimization
        ... bulk write operations ...
        restore()   -> restore original configuration
    """

    def preserve(self) -> None:
        """Save current database configuration (called before optimization)."""
        ...

    def optimize(self, expected_rows: int | None = None) -> None:
        """Apply bulk write optimization.

        Args:
            expected_rows: Expected number of rows to write, used to select the optimization level.
                          Uses default value (typically 10000) when None.
        """
        ...

    def restore(self) -> None:
        """Restore original configuration (called after write completes)."""
        ...


class SQLiteBulkOptimizer:
    """SQLite bulk write optimizer.

    Delegates to the existing ``PragmaOptimizer``, preserving the existing SQLite performance optimization behavior.
    """

    def __init__(
        self,
        execute_fn: Callable[..., Any],
        fetch_pragma_fn: Callable[[str], Any],
    ) -> None:
        """Initialize the SQLite bulk write optimizer.

        Args:
            execute_fn: Callable that executes PRAGMA SQL.
            fetch_pragma_fn: Callable that retrieves the current PRAGMA value.
        """
        # Lazy import to avoid circular dependency
        from sqlseed.database.optimizer import PragmaOptimizer  # noqa: PLC0415

        self._optimizer: PragmaOptimizer = PragmaOptimizer(
            execute_fn=execute_fn,
            fetch_pragma_fn=fetch_pragma_fn,
        )

    def preserve(self) -> None:
        """Save current PRAGMA configuration."""
        self._optimizer.preserve()

    def optimize(self, expected_rows: int | None = None) -> None:
        """Apply PRAGMA bulk write optimization.

        Selects the optimization level based on expected_rows:
        - >100000: aggressive (synchronous=OFF, journal_mode=OFF)
        - >10000: moderate (synchronous=OFF, journal_mode=MEMORY)
        - otherwise: light (synchronous=NORMAL, temp_store=MEMORY)
        """
        self._optimizer.optimize(expected_rows)

    def restore(self) -> None:
        """Restore original PRAGMA configuration."""
        self._optimizer.restore()


class PostgresBulkOptimizer:
    """PostgreSQL bulk write optimizer.

    PG bulk write optimization strategy:
    - ``SET synchronous_commit = OFF``: disable synchronous commit (each transaction does not wait for WAL flush)
    - Optional ``SET session_replication_role = 'replica'``: disable triggers (FK checks, etc.)

    Unlike SQLite PRAGMAs, PG session-level parameters auto-expire when the connection closes,
    but in long-lived connection pools an explicit restore is still required to avoid affecting subsequent operations.
    """

    def __init__(self, execute_fn: Callable[..., Any]) -> None:
        """Initialize the PG bulk write optimizer.

        Args:
            execute_fn: Callable that executes SQL with signature ``(sql, params=None) -> cursor``.
                        The SQL used takes no parameters, so params is optional.
        """
        self._execute_fn = execute_fn
        self._original_synchronous_commit: str | None = None
        self._original_replication_role: str | None = None

    def preserve(self) -> None:
        """Save current synchronous_commit and session_replication_role configuration."""
        try:
            cursor = self._execute_fn("SHOW synchronous_commit")
            row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
            self._original_synchronous_commit = row[0] if row else "on"
        except Exception:
            self._original_synchronous_commit = "on"

        try:
            cursor = self._execute_fn("SHOW session_replication_role")
            row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
            self._original_replication_role = row[0] if row else "origin"
        except Exception:
            self._original_replication_role = "origin"

    def optimize(self, expected_rows: int | None = None) -> None:
        """Apply PG bulk write optimization.

        Args:
            expected_rows: Expected number of rows to write.
                          When >10000, additionally disables triggers (session_replication_role = replica)
                          to skip FK checks and other overhead. Small batches keep origin mode to preserve constraints.
        """
        # Disable synchronous commit (safe: only the last few uncommitted transactions are lost on crash)
        self._execute_fn("SET synchronous_commit = OFF")

        # Disable triggers for large batches (FK checks, index maintenance, etc.)
        # Note: requires SUPERUSER privileges; ordinary users will fail, silently degrade here
        threshold = 10000
        if expected_rows is not None and expected_rows > threshold:
            # Silently degrade on insufficient privileges or unsupported session-level setting
            with contextlib.suppress(Exception):
                self._execute_fn("SET session_replication_role = 'replica'")

    def restore(self) -> None:
        """Restore original synchronous_commit and session_replication_role configuration."""
        if self._original_synchronous_commit is not None:
            with contextlib.suppress(Exception):
                self._execute_fn(f"SET synchronous_commit = '{self._original_synchronous_commit}'")
        if self._original_replication_role is not None:
            with contextlib.suppress(Exception):
                self._execute_fn(f"SET session_replication_role = '{self._original_replication_role}'")


__all__ = ["BulkWriteOptimizer", "PostgresBulkOptimizer", "SQLiteBulkOptimizer"]
