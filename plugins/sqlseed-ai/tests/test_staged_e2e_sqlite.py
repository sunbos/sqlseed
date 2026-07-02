"""E2E tests for the staged pipeline on SQLite (no real LLM required).

These tests exercise the full Layer 1 -> Layer 2 -> Layer 3 pipeline with
mocked LLM responses, validating that the final YAML config is well-formed
and that the StagedSchemaAnalyzer integrates correctly with the rest of
the system.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def complex_biz_db(tmp_path: Path):
    """Build a SQLite db with multiple tables, FKs, UNIQUE, CHECK constraints.

    Returns a connected RawSQLiteAdapter (DatabaseAdapter Protocol-compliant)
    so StructuralFeatureExtractor can consume it directly.

    Schema (mirrors the spec §13 example):
      - categories(id PK, name UNIQUE NOT NULL)
      - products(id PK, name NOT NULL, category_id FK -> categories(id),
                  price REAL CHECK(price > 0), sku UNIQUE)
      - orders(id PK, customer_name, created_at, total REAL CHECK(total >= 0))
      - order_items(id PK, order_id FK -> orders(id), product_id FK -> products(id),
                    quantity INTEGER CHECK(quantity > 0))
    """
    from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

    db_path = tmp_path / "complex_biz.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id),
                price REAL NOT NULL CHECK(price > 0),
                sku TEXT NOT NULL UNIQUE
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                total REAL NOT NULL CHECK(total >= 0)
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL CHECK(quantity > 0)
            );
            CREATE INDEX idx_products_category ON products(category_id);
            CREATE INDEX idx_order_items_order ON order_items(order_id);
        """)
        conn.commit()
    finally:
        conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    return adapter


def test_layer1_extract_features_from_complex_biz(complex_biz_db):
    """E2E: Layer 1 StructuralFeatureExtractor reads all tables / FKs / checks."""
    from sqlseed.core.features import StructuralFeatureExtractor

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()

    # All 4 tables detected
    table_names = {t.name for t in features.tables}
    assert table_names == {"categories", "products", "orders", "order_items"}

    # categories has UNIQUE on name
    categories = next(t for t in features.tables if t.name == "categories")
    assert any("name" in u.columns for u in categories.unique_constraints)

    # products has FK to categories
    products = next(t for t in features.tables if t.name == "products")
    assert any(fk.ref_table == "categories" for fk in products.foreign_keys)

    # products has CHECK on price > 0
    assert any(
        any("price" in c for c in check.columns) for check in products.check_constraints
    )


def test_staged_analyzer_topological_sort_puts_parents_first(complex_biz_db):
    """E2E: topological sort puts FK parents before children."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    from sqlseed.core.features import StructuralFeatureExtractor

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()
    analyzer = StagedSchemaAnalyzer(config=None)
    order = analyzer._topological_sort(features)
    # categories before products (products has FK to categories)
    assert order.index("categories") < order.index("products")
    # orders before order_items
    assert order.index("orders") < order.index("order_items")
    # products before order_items
    assert order.index("products") < order.index("order_items")


def test_staged_analyzer_deterministic_fallback(complex_biz_db):
    """E2E: when LLM stage 1 fails, deterministic fallback produces valid summary."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    from sqlseed.core.features import StructuralFeatureExtractor

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()
    analyzer = StagedSchemaAnalyzer(config=None)
    summary = analyzer._build_deterministic_fallback(features)

    assert hasattr(summary, "tables")
    assert len(summary.tables) == 4
    assert summary.schema_hash == features.schema_hash
    assert set(summary.topological_order) == {
        "categories", "products", "orders", "order_items",
    }
    # Topological order in fallback is also valid
    order = summary.topological_order
    assert order.index("categories") < order.index("products")
    assert order.index("products") < order.index("order_items")


def test_staged_analyzer_full_pipeline_with_mocked_llm(complex_biz_db, monkeypatch):
    """E2E: full Layer 1 -> Layer 2 -> Layer 3 pipeline with mocked LLM."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock all LLM-calling methods so the test runs without a real LLM.
    # Stage 1: deterministic fallback (no LLM, pure Layer 1 derivation).
    # _run_stage1_with_fallback catches the exception and falls back.
    def _raise_stage1(features: Any) -> Any:
        raise RuntimeError("mock: no LLM in unit test")

    monkeypatch.setattr(analyzer, "_call_stage1_llm", _raise_stage1)
    # Stage 2: mock _run_stage2_per_column to return full config dict
    # (Task 8 signature: features, summary, target_tables -> dict[str, Any])
    monkeypatch.setattr(
        analyzer, "_run_stage2_per_column",
        lambda features, summary, target_tables: _mock_stage2_config(features, target_tables),
    )

    # analyze(db) accepts a DatabaseAdapter; complex_biz_db fixture returns one.
    # Stage 3 runs for real (validates + auto-fix rules #1-#16).
    config = analyzer.analyze(complex_biz_db)

    # Sanity-check the final config structure
    assert "tables" in config
    table_names = {t["name"] for t in config["tables"]}
    assert table_names == {"categories", "products", "orders", "order_items"}

    # Each table has at least the auto-fix-added columns
    for table in config["tables"]:
        assert "columns" in table
        assert isinstance(table["columns"], list)
        assert len(table["columns"]) >= 1


def _mock_stage2_config(features: Any, target_tables: list[str]) -> dict[str, Any]:
    """Mock stage 2 LLM output: full config dict with all tables/columns.

    Returns config in the same shape as Task 8 _run_stage2_per_column.
    Skip id columns (autoincrement PKs are skipped per stage 2 skippable logic).
    """
    mocks: dict[str, list[dict[str, Any]]] = {
        "categories": [
            {"name": "name", "generator": "word", "params": {}},
        ],
        "products": [
            {"name": "name", "generator": "word", "params": {}},
            {"name": "category_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "price", "generator": "float",
             "params": {"min_value": 0.01, "max_value": 999.99, "precision": 2}},
            {"name": "sku", "generator": "template",
             "params": {"template": "SKU-{sequence:04d}"}},
        ],
        "orders": [
            {"name": "customer_name", "generator": "name", "params": {}},
            {"name": "created_at", "generator": "datetime", "params": {}},
            {"name": "total", "generator": "float",
             "params": {"min_value": 0.0, "max_value": 10000.0, "precision": 2}},
        ],
        "order_items": [
            {"name": "order_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "product_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "quantity", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
        ],
    }
    tables_config = [
        {"name": name, "columns": mocks.get(name, [])}
        for name in target_tables
    ]
    return {"tables": tables_config}
