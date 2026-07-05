"""[Defense 8] Static schema snapshot + optimistic lock.

Locks schema_hash at startup; verifies unchanged before writing YAML.
Also pre-caches constraint_map for PostgreSQL error reverse-lookup
(Section 14.1: SQLite does not use constraint_map — its CHECK constraints
are usually unnamed, so we parse error text directly).

Spec reference: Section 7.4, 14.1.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import yaml
from sqlseed_ai.validator.models import ConstraintType

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)


class SchemaDriftError(RuntimeError):
    """Raised when database schema changed since snapshot was taken."""


@dataclass
class ConstraintInfo:
    """Reverse-lookup entry for PG constraint_name -> columns/expression."""

    name: str
    columns: list[str]
    constraint_type: ConstraintType
    expression: str | None = None


@dataclass
class TableMeta:
    """Captured metadata for a single table within a schema snapshot."""

    name: str
    columns: list[str]
    column_types: dict[str, str]
    constraints: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)


class SchemaSnapshot:
    """[Defense 8] Static snapshot locked at startup.

    Captures schema via SQLAlchemy reflection, computes a stable hash,
    and exposes ``validate_against_current`` for the write phase. Also
    pre-caches a ``constraint_map`` (PG-only path) for reverse-lookup of
    constraint_name -> columns/expression in the dialect error parser.
    """

    def __init__(self, db_path: str | None = None, url: str | None = None) -> None:
        self.captured_at = datetime.now()
        self.db_path = db_path
        self.url = url
        self.tables: dict[str, TableMeta] = self._capture()
        self.schema_hash = self._compute_hash()
        self.constraint_map: dict[str, ConstraintInfo] = self._build_constraint_map()

    def _capture(self) -> dict[str, TableMeta]:
        """Capture schema via SQLAlchemy reflection."""
        from sqlalchemy import create_engine, inspect

        if self.url:
            engine = create_engine(self.url)
        elif self.db_path:
            engine = create_engine(f"sqlite:///{self.db_path}")
        else:
            return {}

        try:
            inspector = inspect(engine)
            tables: dict[str, TableMeta] = {}
            for tname in inspector.get_table_names():
                cols = inspector.get_columns(tname)
                fks = inspector.get_foreign_keys(tname)
                uniques = inspector.get_unique_constraints(tname)
                checks = inspector.get_check_constraints(tname)
                pk = inspector.get_pk_constraint(tname)
                constraints_list: list[dict[str, Any]] = []
                for u in uniques:
                    constraints_list.append(
                        {
                            "type": "unique",
                            "columns": u["column_names"],
                            "name": u.get("name"),
                        }
                    )
                for c in checks:
                    constraints_list.append(
                        {
                            "type": "check",
                            "columns": c.get("column_names") or [],
                            "expression": c["sqltext"],
                            "name": c.get("name"),
                        }
                    )
                if pk["constrained_columns"]:
                    constraints_list.append(
                        {
                            "type": "primary_key",
                            "columns": pk["constrained_columns"],
                            "name": pk.get("name"),
                        }
                    )
                tables[tname] = TableMeta(
                    name=tname,
                    columns=[c["name"] for c in cols],
                    column_types={c["name"]: str(c["type"]) for c in cols},
                    constraints=constraints_list,
                    foreign_keys=[
                        {
                            "columns": fk["constrained_columns"],
                            "ref_table": fk["referred_table"],
                            "ref_columns": fk["referred_columns"],
                        }
                        for fk in fks
                    ],
                )
            return tables
        finally:
            engine.dispose()

    def _compute_hash(self) -> str:
        content = json.dumps(
            {
                t: {
                    "columns": c.columns,
                    "column_types": c.column_types,
                    "constraints": c.constraints,
                    "foreign_keys": c.foreign_keys,
                }
                for t, c in self.tables.items()
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _build_constraint_map(self) -> dict[str, ConstraintInfo]:
        """Pre-cache named constraints for PG reverse-lookup.

        SQLite CHECKs are usually unnamed -> constraint_map may be empty for
        SQLite. SQLite error parsing uses regex on error text instead
        (Section 14.1).
        """
        cmap: dict[str, ConstraintInfo] = {}
        for table in self.tables.values():
            for c in table.constraints:
                name = c.get("name")
                if not name:
                    continue
                ctype_map = {
                    "unique": ConstraintType.UNIQUE,
                    "check": ConstraintType.CHECK,
                    "primary_key": ConstraintType.NOT_NULL,
                }
                ctype = ctype_map.get(c["type"], ConstraintType.CHECK)
                cmap[name] = ConstraintInfo(
                    name=name,
                    columns=c.get("columns") or [],
                    constraint_type=ctype,
                    expression=c.get("expression"),
                )
        return cmap

    def get_column_type(self, table: str, column: str) -> str:
        """Return the column type string, or 'ANY' if unknown."""
        t = self.tables.get(table)
        if t is None:
            return "ANY"
        return t.column_types.get(column, "ANY")

    def validate_against_current(
        self,
        db_path: str | None = None,
        url: str | None = None,
    ) -> bool:
        """Return True if current schema hash matches this snapshot's hash."""
        current = SchemaSnapshot(db_path=db_path, url=url)
        if current.schema_hash != self.schema_hash:
            logger.error(
                "Schema drift detected",
                snapshot_hash=self.schema_hash,
                current_hash=current.schema_hash,
            )
            return False
        return True


def write_yaml_with_optimistic_lock(
    config: dict[str, Any],
    output_path: Path,
    snapshot: SchemaSnapshot,
    db_path: str | None = None,
    url: str | None = None,
) -> None:
    """[Defense 8] Verify schema unchanged before writing YAML."""
    if not snapshot.validate_against_current(db_path=db_path, url=url):
        raise SchemaDriftError(
            "Database schema has changed since analysis started. "
            "Please re-run ai-analyze to get a fresh snapshot."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
