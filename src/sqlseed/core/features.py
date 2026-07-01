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

from dataclasses import dataclass
from typing import Any


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
