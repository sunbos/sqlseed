"""Database adapter layer public API exports.

Aggregates protocols, adapters, dialects, bulk write optimizers,
and PRAGMA optimizers for unified import by the upper orchestrator and CLI.
"""

from __future__ import annotations

from sqlseed.database._bulk_optimizer import (
    BulkWriteOptimizer,
    PostgresBulkOptimizer,
    SQLiteBulkOptimizer,
)
from sqlseed.database._dialect import (
    Dialect,
    PostgresDialect,
    SQLiteDialect,
)
from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo, DatabaseAdapter, ForeignKeyInfo, IndexInfo
from sqlseed.database._type_normalizer import NormalizedType, TypeNormalizer
from sqlseed.database.optimizer import PragmaOptimizer, PragmaProfile
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

__all__ = [
    "BulkWriteOptimizer",
    "CheckConstraintInfo",
    "ColumnInfo",
    "DatabaseAdapter",
    "Dialect",
    "ForeignKeyInfo",
    "IndexInfo",
    "NormalizedType",
    "PostgresBulkOptimizer",
    "PostgresDialect",
    "PragmaOptimizer",
    "PragmaProfile",
    "RawSQLiteAdapter",
    "SQLAlchemyAdapter",
    "SQLiteBulkOptimizer",
    "SQLiteDialect",
    "TypeNormalizer",
]
