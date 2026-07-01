"""Tests for :class:`AiConfigRefiner` config validation.

Focuses on the dry-run insert validation path and the computed-column
pre-check, which cannot be covered by mock-based tests because the
detection relies on real SQLAlchemy schema reflection.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db_with_generated_column(tmp_path: Path) -> Path:
    """Create a SQLite DB with a ``GENERATED ALWAYS AS (...) STORED`` column.

    Mirrors the ``order_items`` schema used in complex_biz.db so the test
    exercises the same code path that failed in production.
    """
    db_path = tmp_path / "gen.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER CHECK(quantity > 0 AND quantity <= 5),
            price_per_unit REAL CHECK(price_per_unit > 0),
            discount REAL DEFAULT 0.00 CHECK(discount >= 0 AND discount <= price_per_unit),
            item_total REAL GENERATED ALWAYS AS (
                ROUND(quantity * (price_per_unit - discount), 2)
            ) STORED,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _make_refiner(db_path: Path) -> AiConfigRefiner:
    """Build a refiner with a minimal analyzer (no real LLM calls)."""
    ai_config = AIConfig(backend=AIBackend.LM_STUDIO, model="google/gemma-4-e2b")
    analyzer = SchemaAnalyzer(config=ai_config)
    return AiConfigRefiner(analyzer, str(db_path))


class TestComputedColumnValidation:
    """Verify ``_validate_config`` detects generators assigned to GENERATED columns.

    The mapper silently skips computed columns (via ``is_computed``), so
    ``preview_data`` never contains their values. The dry-run insert alone
    cannot detect this misconfiguration — the explicit pre-check in
    ``_check_computed_column_assignments`` is required.
    """

    def test_rejects_generator_on_generated_column(self, db_with_generated_column: Path) -> None:
        """A config that assigns a float generator to the GENERATED ``item_total`` column must fail."""
        refiner = _make_refiner(db_with_generated_column)
        bad_config = {
            "name": "order_items",
            "count": 10,
            "columns": [
                {"name": "quantity", "generator": "integer", "params": {"min_value": 1, "max_value": 5}},
                {
                    "name": "price_per_unit",
                    "generator": "float",
                    "params": {"min_value": 0.01, "max_value": 100.0, "precision": 2},
                },
                {
                    "name": "discount",
                    "generator": "float",
                    "params": {"min_value": 0.0, "max_value": 10.0, "precision": 2},
                },
                # BUG: assigning a generator to a GENERATED column
                {
                    "name": "item_total",
                    "generator": "float",
                    "params": {"min_value": 0.0, "max_value": 1000.0, "precision": 2},
                },
            ],
        }
        with DataOrchestrator(str(db_with_generated_column)) as orch:
            error = refiner._validate_config(orch, "order_items", bad_config)

        assert error is not None
        assert error.error_type == "computed_column_assignment"
        assert error.column == "item_total"
        assert error.retryable is True
        assert "GENERATED" in error.message or "computed" in error.message.lower()

    def test_accepts_config_that_skips_generated_column(self, db_with_generated_column: Path) -> None:
        """A config that omits the GENERATED column must pass validation.

        Note: ``discount`` max (5.0) must be <= ``price_per_unit`` min (10.0)
        to satisfy the CHECK constraint ``discount <= price_per_unit``.
        """
        refiner = _make_refiner(db_with_generated_column)
        good_config = {
            "name": "order_items",
            "count": 10,
            "columns": [
                {"name": "quantity", "generator": "integer", "params": {"min_value": 1, "max_value": 5}},
                {
                    "name": "price_per_unit",
                    "generator": "float",
                    "params": {"min_value": 10.0, "max_value": 100.0, "precision": 2},
                },
                {
                    "name": "discount",
                    "generator": "float",
                    "params": {"min_value": 0.0, "max_value": 5.0, "precision": 2},
                },
            ],
        }
        with DataOrchestrator(str(db_with_generated_column)) as orch:
            error = refiner._validate_config(orch, "order_items", good_config)

        assert error is None


class TestVarCharLengthValidation:
    """Verify ``_validate_config`` detects VARCHAR length violations via dry-run insert.

    Uses VARCHAR(5) so the base provider's default ``str_NNN`` placeholder
    (7 chars) exceeds the limit — this avoids depending on faker/mimesis
    being installed.
    """

    @pytest.fixture
    def db_with_varchar(self, tmp_path: Path) -> Path:
        """Create a SQLite DB with a VARCHAR(5) column."""
        db_path = tmp_path / "varchar.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, code VARCHAR(5) NOT NULL)")
        conn.commit()
        conn.close()
        return db_path

    def test_rejects_oversized_varchar_value(self, db_with_varchar: Path) -> None:
        """A config producing values longer than VARCHAR(5) must fail validation.

        The base provider's ``string`` generator emits ``str_NNN`` placeholders
        (7 chars), which exceed VARCHAR(5) and trigger the length check.
        """
        refiner = _make_refiner(db_with_varchar)
        bad_config = {
            "name": "items",
            "count": 5,
            "columns": [
                {"name": "code", "generator": "string", "params": {}},
            ],
        }
        with DataOrchestrator(str(db_with_varchar)) as orch:
            error = refiner._validate_config(orch, "items", bad_config)

        assert error is not None
        assert error.column == "code"
        assert "too long" in error.message.lower() or "varying" in error.message.lower()

    def test_accepts_within_limit_varchar_value(self, tmp_path: Path) -> None:
        """A config producing values within VARCHAR(20) must pass validation."""
        db_path = tmp_path / "wide.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, code VARCHAR(20) NOT NULL)")
        conn.commit()
        conn.close()

        refiner = _make_refiner(db_path)
        good_config = {
            "name": "items",
            "count": 5,
            "columns": [
                {"name": "code", "generator": "string", "params": {}},
            ],
        }
        with DataOrchestrator(str(db_path)) as orch:
            error = refiner._validate_config(orch, "items", good_config)

        assert error is None
