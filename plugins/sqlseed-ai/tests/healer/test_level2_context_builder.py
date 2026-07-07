"""Pure-logic tests for Level2ColumnHealer._build_column_context() (no LLM)."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
from sqlseed_ai.healer.models import FKInfo


def _make_snapshot(tables: dict):
    """Build a fake SchemaSnapshot-like object."""
    snap = MagicMock()
    snap.tables = tables
    return snap


def _make_table_meta(name, columns, column_types, constraints=None, foreign_keys=None):
    """Build a fake TableMeta-like object."""
    meta = MagicMock()
    meta.name = name
    meta.columns = columns
    meta.column_types = column_types
    meta.constraints = constraints or []
    meta.foreign_keys = foreign_keys or []
    return meta


def test_build_context_simple_column():
    """Single column with no dependencies → only target column attributes."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "users",
        columns=["id", "name", "email"],
        column_types={"id": "INTEGER", "name": "TEXT", "email": "TEXT"},
    )
    snap = _make_snapshot({"users": table})
    ctx = healer._build_column_context("users", "name", snap)
    assert ctx.table_name == "users"
    assert ctx.column_name == "name"
    assert ctx.column_type == "TEXT"
    assert ctx.check_constraints == []
    assert ctx.derive_from_sources == []
    assert ctx.derive_from_downstream == []
    assert ctx.cross_column_refs == []
    assert ctx.fk_info is None


def test_build_context_with_single_check():
    """Single-column CHECK → context contains the CHECK expression."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "products",
        columns=["price"],
        column_types={"price": "REAL"},
        constraints=[{"type": "check", "expression": "price > 0", "columns": ["price"]}],
    )
    snap = _make_snapshot({"products": table})
    ctx = healer._build_column_context("products", "price", snap)
    assert len(ctx.check_constraints) == 1
    assert ctx.check_constraints[0]["expression"] == "price > 0"


def test_build_context_with_cross_column_check():
    """Cross-column CHECK → related column appears in cross_column_refs."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "products",
        columns=["cost_price", "unit_price"],
        column_types={"cost_price": "REAL", "unit_price": "REAL"},
        constraints=[
            {"type": "check", "expression": "unit_price > cost_price", "columns": ["unit_price", "cost_price"]}
        ],
    )
    snap = _make_snapshot({"products": table})
    ctx = healer._build_column_context("products", "unit_price", snap)
    # cross_column_refs should contain cost_price
    ref_names = [r[0] for r in ctx.cross_column_refs]
    assert "cost_price" in ref_names
    # The cross-column CHECK should also appear in check_constraints
    assert len(ctx.check_constraints) == 1


def test_build_context_with_fk():
    """FK column → fk_info is populated."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "user_id"],
        column_types={"id": "INTEGER", "user_id": "INTEGER"},
        foreign_keys=[
            {"columns": ["user_id"], "ref_table": "users", "ref_columns": ["id"]}
        ],
    )
    snap = _make_snapshot({"orders": table})
    ctx = healer._build_column_context("orders", "user_id", snap)
    assert ctx.fk_info is not None
    assert ctx.fk_info.ref_table == "users"
    assert ctx.fk_info.ref_column == "id"


def test_build_context_with_unique():
    """UNIQUE constraint → is_unique is True."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "users",
        columns=["email"],
        column_types={"email": "TEXT"},
        constraints=[{"type": "unique", "columns": ["email"]}],
    )
    snap = _make_snapshot({"users": table})
    ctx = healer._build_column_context("users", "email", snap)
    assert ctx.is_unique is True


def test_build_context_with_derive_from_source():
    """derive_from source columns are detected from config (_enrich_with_config)."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "subtotal", "tax", "total"],
        column_types={"id": "INTEGER", "subtotal": "REAL", "tax": "REAL", "total": "REAL"},
    )
    snap = _make_snapshot({"orders": table})
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "subtotal", "generator": "random_float"},
                    {"name": "tax", "generator": "random_float"},
                    {"name": "total", "derive_from": ["subtotal", "tax"], "expression": "subtotal + tax"},
                ],
            }
        ]
    }
    ctx = healer._build_column_context("orders", "total", snap)
    ctx = healer._enrich_with_config(ctx, config)
    src_names = [s[0] for s in ctx.derive_from_sources]
    assert "subtotal" in src_names
    assert "tax" in src_names


def test_build_context_with_downstream():
    """derive_from downstream columns are detected from config (_enrich_with_config)."""
    healer = Level2ColumnHealer(client=MagicMock(), model="any")
    table = _make_table_meta(
        "orders",
        columns=["id", "subtotal", "tax", "total"],
        column_types={"id": "INTEGER", "subtotal": "REAL", "tax": "REAL", "total": "REAL"},
    )
    snap = _make_snapshot({"orders": table})
    config = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "subtotal", "generator": "random_float"},
                    {"name": "tax", "generator": "random_float"},
                    {"name": "total", "derive_from": ["subtotal", "tax"], "expression": "subtotal + tax"},
                ],
            }
        ]
    }
    # subtotal is a source for total → total should appear in downstream.
    ctx = healer._build_column_context("orders", "subtotal", snap)
    ctx = healer._enrich_with_config(ctx, config)
    assert "total" in ctx.derive_from_downstream
