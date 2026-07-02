"""PostgreSQL E2E tests for the staged pipeline (requires Docker).

These tests run the Layer 1 extractor against a real PostgreSQL instance
launched via testcontainers, verifying that the dialect-aware feature
extraction correctly handles PostgreSQL-specific types (SERIAL, TIMESTAMP,
REAL, TEXT) and constraints (FK, UNIQUE, CHECK).

Marked as ``@pytest.mark.integration`` — skipped unless Docker is available.
The ``pg_url`` fixture is session-scoped and defined in the rootdir
``conftest.py``; it is auto-discovered by pytest (no ``pytest_plugins``
declaration needed here).

API notes (verified against actual source):
    - ``StructuralFeatureExtractor`` has NO ``from_url`` classmethod; it must
      be constructed with a ``DatabaseAdapter``. We use ``SQLAlchemyAdapter``
      + ``.connect(pg_url)``.
    - ``StructuralFeatures.dialect`` holds a ``Dialect`` OBJECT (e.g.
      ``PostgresDialect``), not a string. The dialect name string is
      available via ``features.dialect.name``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _init_pg_schema(pg_url: str) -> None:
    """Create the complex_biz schema on PostgreSQL.

    Idempotent: drops existing tables (with CASCADE) before creating, so the
    schema can be initialized once per session even if the fixture is invoked
    again. Schema mirrors ``test_staged_e2e_sqlite.py`` but uses PG-flavored
    types (SERIAL for autoincrement PK, TIMESTAMP for created_at).
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            # Drop in reverse dependency order (children first).
            for drop_stmt in (
                "DROP TABLE IF EXISTS order_items CASCADE",
                "DROP TABLE IF EXISTS orders CASCADE",
                "DROP TABLE IF EXISTS products CASCADE",
                "DROP TABLE IF EXISTS categories CASCADE",
            ):
                conn.execute(text(drop_stmt))

            conn.execute(text("CREATE TABLE categories ( id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE)"))
            conn.execute(
                text(
                    "CREATE TABLE products ("
                    " id SERIAL PRIMARY KEY,"
                    " name TEXT NOT NULL,"
                    " category_id INTEGER NOT NULL REFERENCES categories(id),"
                    " price REAL NOT NULL CHECK(price > 0),"
                    " sku TEXT NOT NULL UNIQUE"
                    ")"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE orders ("
                    " id SERIAL PRIMARY KEY,"
                    " customer_name TEXT NOT NULL,"
                    " created_at TIMESTAMP NOT NULL,"
                    " total REAL NOT NULL CHECK(total >= 0)"
                    ")"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE order_items ("
                    " id SERIAL PRIMARY KEY,"
                    " order_id INTEGER NOT NULL REFERENCES orders(id),"
                    " product_id INTEGER NOT NULL REFERENCES products(id),"
                    " quantity INTEGER NOT NULL CHECK(quantity > 0)"
                    ")"
                )
            )
            conn.execute(text("CREATE INDEX idx_products_category ON products(category_id)"))
            conn.execute(text("CREATE INDEX idx_order_items_order ON order_items(order_id)"))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pg_complex_biz_url(pg_url: str) -> str:
    """Initialize the complex_biz schema on the PG container once per session.

    Depends on the session-scoped ``pg_url`` fixture from the rootdir conftest.
    If ``pg_url`` skips (Docker/testcontainers unavailable), this fixture
    skips too — the skip propagates automatically.
    """
    _init_pg_schema(pg_url)
    return pg_url


def test_pg_layer1_extraction(pg_complex_biz_url: str) -> None:
    """E2E PG: Layer 1 extracts the same shape as SQLite (4 tables, FKs, checks)."""
    from sqlseed.core.features import StructuralFeatureExtractor
    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    adapter = SQLAlchemyAdapter()
    adapter.connect(pg_complex_biz_url)
    try:
        extractor = StructuralFeatureExtractor(adapter)
        features = extractor.extract()
    finally:
        adapter.close()

    # All 4 complex_biz tables detected (container may have other tests' tables)
    table_names = {t.name for t in features.tables}
    assert {"categories", "products", "orders", "order_items"}.issubset(table_names)

    # PostgreSQL dialect detected. features.dialect is a Dialect OBJECT
    # (PostgresDialect) when the adapter is SQLAlchemyAdapter; the name string
    # lives in .name. Use getattr for safety in case dialect is a bare string.
    dialect_name = getattr(features.dialect, "name", features.dialect)
    assert dialect_name == "postgresql"

    # FK detection works (products -> categories)
    products = next(t for t in features.tables if t.name == "products")
    assert any(fk.ref_table == "categories" for fk in products.foreign_keys)

    # CHECK constraint detection works (products.price > 0)
    assert any(any("price" in c for c in check.columns) for check in products.check_constraints)

    # UNIQUE constraint detection works (products.sku via unique index)
    assert any("sku" in u.columns for u in products.unique_constraints)


def test_pg_staged_analyzer_deterministic_fallback(pg_complex_biz_url: str) -> None:
    """E2E PG: deterministic fallback produces valid summary on PostgreSQL features."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    from sqlseed.core.features import StructuralFeatureExtractor
    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    adapter = SQLAlchemyAdapter()
    adapter.connect(pg_complex_biz_url)
    try:
        extractor = StructuralFeatureExtractor(adapter)
        features = extractor.extract()
    finally:
        adapter.close()

    analyzer = StagedSchemaAnalyzer(config=None)
    summary = analyzer._build_deterministic_fallback(features)

    # All 4 complex_biz tables present in the summary (container may have others)
    summary_names = {t.name for t in summary.tables}
    assert {"categories", "products", "orders", "order_items"}.issubset(summary_names)

    # schema_hash propagated from features
    assert summary.schema_hash == features.schema_hash

    # Topological order respects FK dependencies
    order = summary.topological_order
    assert order.index("categories") < order.index("products")
    assert order.index("products") < order.index("order_items")
    assert order.index("orders") < order.index("order_items")
