"""Integration tests for SchemaFallbackGenerator in orchestrator._resolve_specs.

Verifies that L9 type-fallback columns (generator_name == "string") are
enhanced with CHECK constraint and UNIQUE-aware params WITHOUT overriding
L1-L8 name-matched columns or user-configured columns.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def db_with_check_constraint(tmp_path: Path) -> str:
    """Database with VARCHAR column + CHECK length constraint.

    Schema:
      products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code VARCHAR(100) NOT NULL CHECK(length(code) BETWEEN 8 AND 20),  -- L9 + CHECK
        email VARCHAR(255),                                                -- L3 exact match
        misc TEXT NOT NULL                                                 -- L9 + no CHECK
      )

    Note: NOT NULL is required on `code` so it skips L8 nullable-fallback
    (which returns "skip") and reaches L9 type-fallback (which returns
    "string"). `misc` is used instead of `status` because `status` matches
    the L3 exact-match rule (-> "choice"), preventing L9 fallback.
    """
    db_path = str(tmp_path / "check_test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(100) NOT NULL CHECK(length(code) BETWEEN 8 AND 20),
            email VARCHAR(255),
            misc TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestSchemaFallbackIntegration:
    """Test SchemaFallbackGenerator integration in _resolve_specs."""

    def test_l9_string_column_gets_check_length_constraint(self, db_with_check_constraint: str) -> None:
        """L9 'code' column (no name match) enhanced with CHECK length params."""
        with DataOrchestrator(db_with_check_constraint, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="products",
                count=10,
                columns=None,
                column_configs=None,
                enrich=False,
            )
        # 'code' hit L9 type fallback (generator_name == "string")
        code_spec = specs.get("code")
        assert code_spec is not None
        assert code_spec.generator_name == "string"
        # SchemaFallbackGenerator should have applied CHECK(length BETWEEN 8 AND 20)
        assert code_spec.params.get("min_length") == 8
        assert code_spec.params.get("max_length") == 20

    def test_l3_name_matched_column_not_overridden(self, db_with_check_constraint: str) -> None:
        """L3 'email' exact-match column must NOT be overridden by schema_fallback."""
        with DataOrchestrator(db_with_check_constraint, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="products",
                count=10,
                columns=None,
                column_configs=None,
                enrich=False,
            )
        email_spec = specs.get("email")
        assert email_spec is not None
        # L3 exact match produces "email" generator, NOT "string"
        assert email_spec.generator_name == "email"

    def test_user_configured_column_not_overridden(self, db_with_check_constraint: str) -> None:
        """User-supplied column config must NOT be overridden by schema_fallback."""
        from sqlseed.config.models import ColumnConfig

        user_config = ColumnConfig(name="code", generator="uuid")
        with DataOrchestrator(db_with_check_constraint, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="products",
                count=10,
                columns=None,
                column_configs=[user_config],
                enrich=False,
            )
        code_spec = specs.get("code")
        assert code_spec is not None
        # User config "uuid" must win, not schema_fallback "string"
        assert code_spec.generator_name == "uuid"

    def test_l9_string_column_without_check_gets_type_length(self, db_with_check_constraint: str) -> None:
        """L9 'misc' column (no CHECK) gets type-parsed max_length only."""
        with DataOrchestrator(db_with_check_constraint, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="products",
                count=10,
                columns=None,
                column_configs=None,
                enrich=False,
            )
        misc_spec = specs.get("misc")
        assert misc_spec is not None
        assert misc_spec.generator_name == "string"
        # TEXT type has no length, so no max_length param
        # (SchemaFallbackGenerator returns "string" with empty params for bare TEXT)

    def test_generated_data_satisfies_check_constraint(self, db_with_check_constraint: str) -> None:
        """End-to-end: generated rows must pass CHECK(length(code) BETWEEN 8 AND 20)."""
        with DataOrchestrator(db_with_check_constraint, provider_name="base") as orch:
            result = orch.fill_table("products", count=20)
            assert result.count == 20

        # Verify all generated code values satisfy CHECK
        conn = sqlite3.connect(db_with_check_constraint)
        rows = conn.execute("SELECT code FROM products").fetchall()
        conn.close()
        assert len(rows) == 20
        for (code,) in rows:
            assert 8 <= len(code) <= 20, f"CHECK violation: code={code!r} len={len(code)}"
