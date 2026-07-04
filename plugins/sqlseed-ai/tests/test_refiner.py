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
                # max_length=20 ensures generated strings fit VARCHAR(20).
                # Without max_length, the string generator defaults to 50 chars
                # which would violate the column constraint.
                {"name": "code", "generator": "string", "params": {"min_length": 1, "max_length": 20}},
            ],
        }
        with DataOrchestrator(str(db_path)) as orch:
            error = refiner._validate_config(orch, "items", good_config)

        assert error is None


class TestRule14ParamStripping:
    """Verify ``_apply_rule_14_param_stripping`` strips invalid generator params.

    The refiner path (``AiConfigRefiner._try_prompt_levels``) calls this
    helper after the LLM returns a config dict, before ``_validate_config``.
    Without it, LLM-hallucinated params like email's ``min_length``/``example``
    cause ``ConfigurationError`` at validation time (the failure observed in
    ``test_generate_and_refine_streaming_invokes_no_state_mutation``).
    """

    def test_strips_invalid_params_for_email_generator(self, tmp_path: Path) -> None:
        """email generator does not accept min_length/example — must be stripped."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {
            "name": "users",
            "count": 5,
            "columns": [
                {
                    "name": "email",
                    "generator": "email",
                    "params": {"min_length": 5, "example": "user@example.com"},
                },
            ],
        }
        refiner._apply_rule_14_param_stripping(config)
        params = config["columns"][0]["params"]
        assert params == {}, f"Expected empty params, got {params}"

    def test_keeps_valid_params_for_string_generator(self, tmp_path: Path) -> None:
        """string generator accepts min_length/max_length — must be kept."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {
            "name": "users",
            "count": 5,
            "columns": [
                {
                    "name": "code",
                    "generator": "string",
                    "params": {"min_length": 1, "max_length": 20},
                },
            ],
        }
        refiner._apply_rule_14_param_stripping(config)
        params = config["columns"][0]["params"]
        assert params == {"min_length": 1, "max_length": 20}

    def test_corrects_singular_choice_to_choices(self, tmp_path: Path) -> None:
        """choice generator: ``choice`` (singular) typo -> ``choices`` (plural)."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {
            "name": "users",
            "count": 5,
            "columns": [
                {
                    "name": "status",
                    "generator": "choice",
                    "params": {"choice": ["active", "inactive"]},
                },
            ],
        }
        refiner._apply_rule_14_param_stripping(config)
        params = config["columns"][0]["params"]
        assert params == {"choices": ["active", "inactive"]}

    def test_handles_multi_table_config(self, tmp_path: Path) -> None:
        """Multi-table ``{"tables": [...]}`` shape must be handled."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {
            "tables": [
                {
                    "name": "users",
                    "count": 5,
                    "columns": [
                        {
                            "name": "email",
                            "generator": "email",
                            "params": {"min_length": 5},
                        },
                    ],
                },
                {
                    "name": "orders",
                    "count": 5,
                    "columns": [
                        {
                            "name": "code",
                            "generator": "string",
                            "params": {"min_length": 1, "max_length": 10, "example": "X"},
                        },
                    ],
                },
            ]
        }
        refiner._apply_rule_14_param_stripping(config)
        assert config["tables"][0]["columns"][0]["params"] == {}
        assert config["tables"][1]["columns"][0]["params"] == {"min_length": 1, "max_length": 10}

    def test_no_op_for_unknown_shape(self, tmp_path: Path) -> None:
        """Config without ``tables`` or ``name`` key is a no-op (no crash)."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {"some_other_key": "value"}
        refiner._apply_rule_14_param_stripping(config)
        assert config == {"some_other_key": "value"}

    def test_no_op_for_columns_without_generator(self, tmp_path: Path) -> None:
        """Columns without a ``generator`` key are skipped (no crash)."""
        refiner = _make_refiner(tmp_path / "scratch.db")
        config = {
            "name": "users",
            "count": 5,
            "columns": [
                {"name": "id"},  # no generator (e.g., autoincrement PK)
            ],
        }
        refiner._apply_rule_14_param_stripping(config)
        assert config["columns"][0] == {"name": "id"}
