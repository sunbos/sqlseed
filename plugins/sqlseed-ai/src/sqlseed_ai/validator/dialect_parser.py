"""[Defense 3] Dialect-aware integrity error parser.

Section 14.1: SQLite uses regex on error text (constraints usually unnamed).
PostgreSQL uses diag.constraint_name + pre-cached constraint_map.

Spec reference: Section 4.5, 14.1.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed_ai.validator.models import ConstraintType, ViolationReport

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class DialectErrorParser:
    """Normalize SQLAlchemy/DBAPI exceptions to :class:`ViolationReport`.

    SQLite CHECK constraints are usually unnamed, so we parse the error
    message text directly. PostgreSQL exposes ``diag.constraint_name`` which
    is reverse-looked-up in :attr:`SchemaSnapshot.constraint_map`.

    Returns ``None`` for unrecognized dialects or unparseable messages so
    callers can fall back to a generic error path.
    """

    @classmethod
    def parse(
        cls,
        error: Exception,
        dialect: str,
        table: str | None,
        snapshot: SchemaSnapshot | None,
    ) -> ViolationReport | None:
        """Dispatch to dialect-specific parser. Returns None if unrecognized."""
        if dialect == "sqlite":
            return cls._parse_sqlite(error, table)
        if dialect == "postgresql":
            return cls._parse_postgresql(error, table, snapshot)
        return None

    @staticmethod
    def _parse_sqlite(error: Exception, table: str | None) -> ViolationReport | None:
        """Parse SQLite integrity error text via substring matching."""
        msg = str(error)
        if "CHECK constraint failed" in msg:
            expr = msg.rsplit("CHECK constraint failed:", maxsplit=1)[-1].strip()
            return ViolationReport(
                table=table or "",
                columns=[],
                constraint_type=ConstraintType.CHECK,
                severity="crash",
                raw_expression=expr,
                message=msg,
            )
        if "UNIQUE constraint failed" in msg:
            cols_str = msg.rsplit("UNIQUE constraint failed:", maxsplit=1)[-1].strip()
            # Format: table.col1, table.col2
            cols = [c.split(".")[-1].strip() for c in cols_str.split(",")]
            return ViolationReport(
                table=table or "",
                columns=cols,
                constraint_type=ConstraintType.UNIQUE,
                severity="crash",
                is_composite=len(cols) > 1,
                message=msg,
            )
        if "FOREIGN KEY constraint failed" in msg:
            # SQLite FK errors don't include column info (Section 14.1).
            # Caller runs ShadowFKScanner (Section 14.3).
            return ViolationReport(
                table=table or "",
                columns=[],
                constraint_type=ConstraintType.FK,
                severity="crash",
                fix_hint="shadow_fk_scan",
                message=msg,
            )
        if "NOT NULL constraint failed" in msg:
            cols_str = msg.rsplit("NOT NULL constraint failed:", maxsplit=1)[-1].strip()
            cols = [c.split(".")[-1].strip() for c in cols_str.split(",")]
            return ViolationReport(
                table=table or "",
                columns=cols,
                constraint_type=ConstraintType.NOT_NULL,
                severity="crash",
                message=msg,
            )
        return None

    @staticmethod
    def _parse_postgresql(
        error: Exception,
        table: str | None,
        snapshot: SchemaSnapshot | None,
    ) -> ViolationReport | None:
        """Parse PostgreSQL error via diag.constraint_name + constraint_map."""
        diag = getattr(error, "diag", None)
        if diag is None:
            return None
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name is None or snapshot is None:
            return None
        info = snapshot.constraint_map.get(constraint_name)
        if info is None:
            return None
        return ViolationReport(
            table=table or getattr(diag, "table_name", "") or "",
            columns=info.columns,
            constraint_type=info.constraint_type,
            severity="crash",
            constraint_name=constraint_name,
            raw_expression=info.expression,
            is_composite=len(info.columns) > 1,
            message=str(error),
        )
