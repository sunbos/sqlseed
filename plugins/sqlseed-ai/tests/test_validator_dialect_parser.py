"""Tests for DialectErrorParser (Defense 3, Section 14.1)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from sqlseed_ai.validator.dialect_parser import DialectErrorParser
from sqlseed_ai.validator.models import ConstraintType
from sqlseed_ai.validator.schema_snapshot import ConstraintInfo, SchemaSnapshot


def test_parse_sqlite_check_violation():
    err = sqlite3.IntegrityError("CHECK constraint failed: sale_price >= cost_price")
    report = DialectErrorParser.parse(err, "sqlite", table="products", snapshot=None)
    assert report is not None
    assert report.constraint_type == ConstraintType.CHECK
    assert report.raw_expression == "sale_price >= cost_price"
    assert report.severity == "crash"


def test_parse_sqlite_unique_violation():
    err = sqlite3.IntegrityError("UNIQUE constraint failed: products.sku")
    report = DialectErrorParser.parse(err, "sqlite", table="products", snapshot=None)
    assert report is not None
    assert report.constraint_type == ConstraintType.UNIQUE
    assert "sku" in report.columns


def test_parse_sqlite_fk_violation_returns_empty_columns():
    """SQLite FK errors don't include column info — Section 14.1/14.3."""
    err = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    report = DialectErrorParser.parse(err, "sqlite", table="orders", snapshot=None)
    assert report is not None
    assert report.constraint_type == ConstraintType.FK
    assert report.columns == []
    assert report.fix_hint == "shadow_fk_scan"


def test_parse_pg_uses_constraint_map():
    err = MagicMock()
    diag = MagicMock()
    diag.constraint_name = "products_check_price"
    diag.table_name = "products"
    err.diag = diag
    snapshot = MagicMock(spec=SchemaSnapshot)
    snapshot.constraint_map = {
        "products_check_price": ConstraintInfo(
            name="products_check_price",
            columns=["sale_price", "cost_price"],
            constraint_type=ConstraintType.CHECK,
            expression="sale_price >= cost_price",
        )
    }
    report = DialectErrorParser.parse(err, "postgresql", table="products", snapshot=snapshot)
    assert report is not None
    assert report.constraint_name == "products_check_price"
    assert report.columns == ["sale_price", "cost_price"]
    assert report.raw_expression == "sale_price >= cost_price"


def test_parse_unknown_dialect_returns_none():
    err = ValueError("some error")
    assert DialectErrorParser.parse(err, "mysql", table="t", snapshot=None) is None


def test_parse_sqlite_not_null_violation():
    err = sqlite3.IntegrityError("NOT NULL constraint failed: users.email")
    report = DialectErrorParser.parse(err, "sqlite", table="users", snapshot=None)
    assert report is not None
    assert report.constraint_type == ConstraintType.NOT_NULL
    assert "email" in report.columns


def test_parse_sqlite_unrecognized_error_returns_none():
    err = sqlite3.IntegrityError("something else entirely")
    assert DialectErrorParser.parse(err, "sqlite", table="t", snapshot=None) is None


def test_parse_pg_returns_none_when_no_diag():
    err = ValueError("no diag attribute")
    assert DialectErrorParser.parse(err, "postgresql", table="t", snapshot=None) is None


def test_parse_pg_returns_none_when_constraint_not_in_map():
    err = MagicMock()
    diag = MagicMock()
    diag.constraint_name = "unknown_constraint"
    err.diag = diag
    snapshot = MagicMock(spec=SchemaSnapshot)
    snapshot.constraint_map = {}
    assert DialectErrorParser.parse(err, "postgresql", table="t", snapshot=snapshot) is None


def test_parse_sqlite_unique_composite_violation():
    err = sqlite3.IntegrityError("UNIQUE constraint failed: items.a, items.b")
    report = DialectErrorParser.parse(err, "sqlite", table="items", snapshot=None)
    assert report is not None
    assert report.constraint_type == ConstraintType.UNIQUE
    assert "a" in report.columns
    assert "b" in report.columns
