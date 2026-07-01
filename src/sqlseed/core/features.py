"""Layer 1: Normalized structural features for cross-database schema analysis.

Defines dialect-agnostic dataclasses for schema introspection results.
Used by Layer 2 (stage relevance) and Layer 3 (staged LLM pipeline) in
the sqlseed-ai plugin.

This module is in the CORE layer (no business logic, no LLM code).
It builds on the existing DatabaseAdapter Protocol
(src/sqlseed/database/_protocol.py) and adds normalized containers
that support composite FK, composite UNIQUE, partial indexes, collation,
and other features the Protocol does not directly expose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter, ForeignKeyInfo


def _parse_max_length(type_str: str) -> int | None:
    """Parse max_length from type string like 'VARCHAR(255)' -> 255."""
    import re

    match = re.match(r"^\s*\w+\s*\(\s*(\d+)\s*\)", type_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


@dataclass
class ColumnFeatures:
    """Normalized column features, dialect-agnostic.

    Extends ColumnInfo with optional max_length (parsed from type string
    like VARCHAR(255)) and collation (dialect-specific).
    """

    name: str
    type: str  # Original type string (e.g., "VARCHAR(255)", "INTEGER")
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool
    # Optional extensions (filled by dialect-specific extractor)
    max_length: int | None = None  # Parsed from VARCHAR(N)/CHAR(N) etc.
    collation: str | None = None  # SQLite: NOCASE/BINARY/RTRIM; PG: COLLATION name


@dataclass
class ForeignKeyFeatures:
    """Normalized foreign key features, supports composite FK.

    P2 #1 fix: each single-column ForeignKeyInfo from the Protocol is
    preserved as a separate ForeignKeyFeatures with columns=[col].
    Composite FK (multi-column) is only created when the dialect
    extension detects multiple columns share the same FK name/id.
    """

    table: str
    columns: list[str]  # Single-col FK: len==1; composite FK: len>1
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None  # Requires dialect extension
    on_update: str | None = None  # Requires dialect extension


@dataclass
class UniqueConstraintFeatures:
    """Normalized UNIQUE constraint, supports composite.

    Derived from IndexInfo(unique=True) (is_index_based=True) or from
    DDL parsing of table-level UNIQUE constraints (is_index_based=False).
    """

    table: str
    columns: list[str]
    is_index_based: bool
    partial_predicate: str | None = None  # Requires dialect extension


@dataclass
class CheckConstraintFeatures:
    """Normalized CHECK constraint. Direct mapping from CheckConstraintInfo."""

    table: str
    name: str
    expression: str  # Raw SQL expression
    columns: list[str]  # Extracted column references


@dataclass
class IndexFeatures:
    """Normalized index. Based on IndexInfo with optional partial predicate."""

    table: str
    name: str
    columns: list[str]
    unique: bool
    partial_predicate: str | None = None  # Requires dialect extension


@dataclass
class TableFeatures:
    """Normalized table features."""

    name: str
    columns: list[ColumnFeatures]
    primary_key: list[str]  # Composite PK supported (from get_primary_keys)
    foreign_keys: list[ForeignKeyFeatures]  # Per-column (P2 #1 fix)
    unique_constraints: list[UniqueConstraintFeatures]
    check_constraints: list[CheckConstraintFeatures]
    indexes: list[IndexFeatures]
    # SQLite-specific (PG: always default values)
    is_strict: bool = False
    is_without_rowid: bool = False
    on_conflict: str | None = None


@dataclass
class DialectSpecificFeatures:
    """Dialect-specific features not in the common model."""

    dialect: str  # "sqlite" | "postgresql"
    features: dict[str, Any]


@dataclass
class StructuralFeatures:
    """Complete normalized schema features, dialect-agnostic.

    Output of StructuralFeatureExtractor.extract(). Consumed by Layer 2
    (stage relevance determination) and Layer 3 (staged LLM pipeline).
    """

    dialect: str
    tables: list[TableFeatures]
    schema_hash: str  # For cache key
    dialect_specific: DialectSpecificFeatures | None = None
    # views omitted: Protocol does not provide get_view_names()


class StructuralFeatureExtractor:
    """Extract structural features from any supported database.

    Uses DatabaseAdapter Protocol API + dialect extensions. Does NOT
    call non-existent methods like get_columns/get_pk_constraint.

    Spec §4.2: feature extractor with actual Protocol API.
    """

    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        # dialect via hasattr (Protocol does not declare attributes)
        self.dialect = getattr(adapter, "dialect", "sqlite")

    def extract(self, table_names: list[str] | None = None) -> StructuralFeatures:
        """Extract structural features.

        Args:
            table_names: None extracts all tables; provided extracts only
                those tables + FK parent closure (on-demand analysis).
        """
        tables_to_analyze = self._resolve_scope(table_names)
        tables = [self._extract_table_common(name) for name in tables_to_analyze]
        # Dialect-specific extensions fill Protocol gaps
        dialect_specific = self._extract_dialect_specific(tables_to_analyze)
        if dialect_specific:
            self._merge_dialect_specific(tables, dialect_specific)
        schema_hash = self._compute_schema_hash(tables)
        return StructuralFeatures(
            dialect=self.dialect,
            tables=tables,
            schema_hash=schema_hash,
            dialect_specific=dialect_specific,
        )

    def _resolve_scope(self, table_names: list[str] | None) -> list[str]:
        """On-demand: all tables or target tables + FK parent closure."""
        if table_names is None:
            return self.adapter.get_table_names()
        scope = set(table_names)
        changed = True
        while changed:
            changed = False
            for table in list(scope):
                fks = self.adapter.get_foreign_keys(table)
                for fk in fks:
                    if fk.ref_table not in scope:
                        scope.add(fk.ref_table)
                        changed = True
        return sorted(scope)

    def _extract_table_common(self, table_name: str) -> TableFeatures:
        """Common extraction using existing Protocol API."""
        # Uses get_column_info (NOT get_columns)
        column_infos = self.adapter.get_column_info(table_name)
        columns = [
            ColumnFeatures(
                name=ci.name,
                type=ci.type,
                nullable=ci.nullable,
                default=ci.default,
                is_primary_key=ci.is_primary_key,
                is_autoincrement=ci.is_autoincrement,
                is_computed=ci.is_computed,
                max_length=_parse_max_length(ci.type),
                # collation filled by dialect extension, default None
            )
            for ci in column_infos
        ]

        # Uses get_primary_keys (NOT get_pk_constraint)
        pk = self.adapter.get_primary_keys(table_name)

        # Uses get_foreign_keys + preserves per-column (P2 #1 fix)
        raw_fks = self.adapter.get_foreign_keys(table_name)
        fks = self._preserve_foreign_keys(raw_fks, table_name)

        # Derive UNIQUE constraints from get_index_info (Protocol has no get_unique_constraints)
        index_infos = self.adapter.get_index_info(table_name)
        unique_constraints = [
            UniqueConstraintFeatures(
                table=table_name,
                columns=list(idx.columns),
                is_index_based=True,
                # partial_predicate filled by dialect extension
            )
            for idx in index_infos
            if idx.unique
        ]
        indexes = [
            IndexFeatures(
                table=table_name,
                name=idx.name,
                columns=list(idx.columns),
                unique=idx.unique,
                # partial_predicate filled by dialect extension
            )
            for idx in index_infos
        ]

        # Uses get_check_constraints (direct mapping)
        check_infos = self.adapter.get_check_constraints(table_name)
        check_constraints = [
            CheckConstraintFeatures(
                table=table_name,
                name=cci.name,
                expression=cci.expression,
                columns=list(cci.columns),
            )
            for cci in check_infos
        ]

        return TableFeatures(
            name=table_name,
            columns=columns,
            primary_key=pk,
            foreign_keys=fks,
            unique_constraints=unique_constraints,
            check_constraints=check_constraints,
            indexes=indexes,
            # is_strict/is_without_rowid/on_conflict filled by dialect extension
        )

    def _preserve_foreign_keys(self, raw_fks: list[ForeignKeyInfo], table: str) -> list[ForeignKeyFeatures]:
        """P2 #1 fix: preserve each single-column FK as separate features.

        Do NOT group by ref_table (that would incorrectly merge
        created_by -> users(id) and approved_by -> users(id)).
        Composite FK detection requires dialect extension to read FK name/id.
        """
        return [
            ForeignKeyFeatures(
                table=table,
                columns=[fk.column],
                ref_table=fk.ref_table,
                ref_columns=[fk.ref_column],
                # on_delete/on_update filled by dialect extension
            )
            for fk in raw_fks
        ]

    def _extract_dialect_specific(self, tables: list[str]) -> DialectSpecificFeatures | None:
        """Dialect-specific extraction: fills Protocol gaps."""
        if self.dialect == "sqlite":
            return self._extract_sqlite_specific(tables)
        if self.dialect == "postgresql":
            return self._extract_postgresql_specific(tables)
        return None

    def _extract_sqlite_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """SQLite-specific: STRICT, WITHOUT ROWID, ON CONFLICT, COLLATE.

        Uses sqlite_master.sql DDL parsing (no extra Protocol methods needed).
        """
        import re

        features: dict[str, Any] = {}
        for table_name in tables:
            table_features: dict[str, Any] = {}
            # Read DDL from sqlite_master
            try:
                result = self.adapter.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                rows = result.fetchall() if hasattr(result, "fetchall") else []
                ddl = rows[0][0] if rows and rows[0] else ""
            except Exception:
                ddl = ""

            if ddl:
                # STRICT table
                if re.search(r"\bSTRICT\b", ddl, re.IGNORECASE):
                    table_features["is_strict"] = True
                # WITHOUT ROWID
                if re.search(r"\bWITHOUT\s+ROWID\b", ddl, re.IGNORECASE):
                    table_features["is_without_rowid"] = True
                # ON CONFLICT clause (rare)
                on_conflict_match = re.search(
                    r"\bON\s+CONFLICT\s+(ROLLBACK|ABORT|FAIL|IGNORE|REPLACE)\b",
                    ddl,
                    re.IGNORECASE,
                )
                if on_conflict_match:
                    table_features["on_conflict"] = on_conflict_match.group(1).upper()

                # Per-column COLLATE
                col_collations: dict[str, str] = {}
                # Match: column_name TYPE ... COLLATE COLLATION_NAME
                # Skip CONSTRAINT keyword to avoid table-level constraints
                col_pattern = re.compile(
                    r'"?(\w+)"?\s+\w+(?:\s*\([^)]*\))?'
                    r"(?:\s+(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|UNIQUE|DEFAULT\s+\S+))*"
                    r"\s+COLLATE\s+(\w+)",
                    re.IGNORECASE,
                )
                for match in col_pattern.finditer(ddl):
                    col_name = match.group(1)
                    collation = match.group(2).upper()
                    col_collations[col_name] = collation
                if col_collations:
                    table_features["column_collations"] = col_collations

            # Partial index predicates via PRAGMA index_list
            index_predicates: dict[str, str] = {}
            try:
                from sqlseed._utils.sql_safe import quote_identifier

                safe_table = quote_identifier(table_name)
                result = self.adapter.execute(f"PRAGMA index_list({safe_table})")
                rows = result.fetchall() if hasattr(result, "fetchall") else []
                for row in rows:
                    # row: (seq, name, unique, origin, partial)
                    if len(row) >= 5 and row[4]:
                        idx_name = row[1]
                        partial = row[4]
                        if isinstance(partial, str) and partial.strip():
                            index_predicates[idx_name] = partial
            except Exception:
                pass
            if index_predicates:
                table_features["index_predicates"] = index_predicates

            if table_features:
                features[table_name] = table_features

        return DialectSpecificFeatures(dialect="sqlite", features=features)

    def _extract_postgresql_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """PostgreSQL-specific: SEQUENCE, EXCLUSION, PARTITION, INHERITANCE, COLLATION.

        Phase 1 stub: returns empty features. Full implementation deferred
        to a future phase (tracked in spec §11.3 as a non-blocking enhancement).
        When implemented, this method will query:
        - pg_sequences for SEQUENCE objects (SERIAL/IDENTITY)
        - pg_constraint conflist for EXCLUSION constraints
        - pg_partitioned_table for PARTITION BY
        - pg_inherits for INHERITS
        - pg_collation per column for COLLATION

        The stub is intentional: Phase 1 focuses on SQLite + core PostgreSQL
        feature parity (tables, columns, PKs, FKs, indexes, checks, uniques)
        which the DatabaseAdapter Protocol already exposes.
        """
        return DialectSpecificFeatures(dialect="postgresql", features={})

    def _merge_dialect_specific(self, tables: list[TableFeatures], dialect_specific: DialectSpecificFeatures) -> None:
        """Merge dialect-specific fields into TableFeatures.

        Fills is_strict, is_without_rowid, on_conflict, collation,
        partial_predicate. Dialect-specific fields are populated by
        `_extract_sqlite_specific` (Task 3) or `_extract_postgresql_specific`
        (Task 4 stub); this method merges them into TableFeatures.
        """
        features = dialect_specific.features
        for table in tables:
            table_features = features.get(table.name, {})
            if "is_strict" in table_features:
                table.is_strict = table_features["is_strict"]
            if "is_without_rowid" in table_features:
                table.is_without_rowid = table_features["is_without_rowid"]
            if "on_conflict" in table_features:
                table.on_conflict = table_features["on_conflict"]
            # collation / partial_predicate filled per-column/per-index
            col_collations = table_features.get("column_collations", {})
            if col_collations:
                for col in table.columns:
                    if col.name in col_collations:
                        col.collation = col_collations[col.name]
            index_predicates = table_features.get("index_predicates", {})
            if index_predicates:
                for idx in table.indexes:
                    if idx.name in index_predicates:
                        idx.partial_predicate = index_predicates[idx.name]

    def _compute_schema_hash(self, tables: list[TableFeatures]) -> str:
        """Compute stable hash of schema for cache key."""
        # Hash table names + columns + constraints (deterministic order)
        payload = []
        for table in sorted(tables, key=lambda t: t.name):
            payload.append(
                {
                    "name": table.name,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "nullable": c.nullable,
                            "pk": c.is_primary_key,
                            "ai": c.is_autoincrement,
                        }
                        for c in table.columns
                    ],
                    "pk": table.primary_key,
                    "fks": [
                        {"cols": fk.columns, "ref_table": fk.ref_table, "ref_cols": fk.ref_columns}
                        for fk in table.foreign_keys
                    ],
                    "checks": [
                        {"name": c.name, "expr": c.expression, "cols": c.columns} for c in table.check_constraints
                    ],
                    "uniques": [{"cols": u.columns, "index_based": u.is_index_based} for u in table.unique_constraints],
                }
            )
        json_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()[:16]
