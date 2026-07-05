"""In-memory shadow FK scan (Section 14.3).

Triggered when DialectErrorParser returns a FK ViolationReport with empty
columns (SQLite case). Localizes the offending FK column by sampling
generated values against parent PK set.

Spec reference: Section 14.3.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai.validator.models import ConstraintType, ViolationReport

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


class ShadowFKScanner:
    """Localize FK violation column via in-memory value scan.

    When SQLite raises a ``FOREIGN KEY constraint failed`` error, the error
    text does not include the offending column name (Section 14.1). This
    scanner inspects the generated batch against the parent table's PK set
    to identify which FK column caused the violation.
    """

    def __init__(
        self,
        db_path: str | None = None,
        snapshot: SchemaSnapshot | None = None,
        url: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._url = url
        self._snapshot = snapshot

    def scan(
        self,
        report: ViolationReport,
        batch: list[dict[str, Any]],
    ) -> ViolationReport:
        """Backfill report.columns with the offending FK column.

        Args:
            report: FK ViolationReport with empty columns.
            batch: Sample of generated rows for the failing table.

        Returns:
            Updated ViolationReport with columns populated. If no culprit
            found, returns the report unchanged (with a logged warning).
        """
        if report.columns:
            return report  # Already localized
        if report.constraint_type != ConstraintType.FK:
            return report
        if self._snapshot is None:
            logger.warning("ShadowFKScanner requires snapshot; skipping")
            return report
        if not (self._db_path or self._url):
            logger.warning(
                "ShadowFKScanner has no db_path or url; cannot localize FK",
                table=report.table,
            )
            return report

        table_meta = self._snapshot.tables.get(report.table)
        if table_meta is None:
            return report

        for fk in table_meta.foreign_keys:
            fk_cols = fk.get("columns") or []
            parent_table = fk.get("ref_table")
            parent_cols = fk.get("ref_columns") or []
            if not (fk_cols and parent_table and parent_cols):
                continue
            parent_pk_set = self._load_parent_pk_set(parent_table, parent_cols[0])
            for fk_col in fk_cols:
                generated_values = {
                    row.get(fk_col) for row in batch if row.get(fk_col) is not None
                }
                offending = generated_values - parent_pk_set
                if offending:
                    logger.info(
                        "Shadow FK scan localized offender",
                        table=report.table,
                        column=fk_col,
                        offending_count=len(offending),
                    )
                    report.columns = [fk_col]
                    return report
        logger.warning("Shadow FK scan found no culprit", table=report.table)
        return report

    def _load_parent_pk_set(self, parent_table: str, parent_col: str) -> set[Any]:
        """Load parent PK values from snapshot cache or DB.

        Adversarial fix (B2 from cross-agent review): use ``quote_identifier()``
        instead of ``validate_table_name()``. The latter returns a **quoted**
        identifier (e.g., ``"users"``), so calling it without using the return
        value leaves the raw ``parent_table`` in the f-string SQL — both unsafe
        and a misuse of the API. ``quote_identifier()`` returns the quoted form
        which we then use directly in the SQL.

        Adversarial fix (reviewer feedback): support both ``db_path`` (SQLite
        file path) and ``url`` (database URL via SQLAlchemy). The constructor
        already accepts ``url``, but without this branch the scanner silently
        returns an empty set whenever the user connects via ``--url``,
        defeating Defense 3 (shadow FK localization) for PostgreSQL and
        in-memory SQLite.
        """
        from sqlseed._utils.sql_safe import quote_identifier

        safe_table = quote_identifier(parent_table)
        safe_col = quote_identifier(parent_col)
        # SQLite file path: direct sqlite3 connection (fast, zero-dep)
        if self._db_path:
            import sqlite3

            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(f"SELECT {safe_col} FROM {safe_table}").fetchall()
            return {r[0] for r in rows}
        # Database URL (PostgreSQL, sqlite:////path, memory): use SQLAlchemy
        if self._url:
            from sqlalchemy import create_engine, text

            engine = create_engine(self._url)
            try:
                with engine.connect() as conn:
                    sa_rows = conn.execute(
                        text(f"SELECT {safe_col} FROM {safe_table}")
                    ).fetchall()
                return {r[0] for r in sa_rows}
            finally:
                engine.dispose()
        # No connection info available — return empty set (caller handles)
        logger.warning(
            "ShadowFKScanner has no db_path or url; returning empty PK set",
            parent_table=parent_table,
        )
        return set()
