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


@pytest.fixture
def db_with_title_enum(tmp_path: Path) -> str:
    """Database where an EXACT-rule column carries a CHECK IN enum.

    Schema mirrors the live defect found via sqlseed-ui on
    ``employees.title``: EXACT_MATCH_RULES maps ``title`` -> ``sentence``,
    yet the column has ``CHECK (title IN ('engineer','manager',...))``.
    The name-rule guess deterministically violates the constraint (any
    random sentence fails IN) — the DB constraint is the hard truth.
    """
    db_path = str(tmp_path / "title_enum.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL CHECK (title IN ('engineer','manager','director','vp')),
            note TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestNameRuleEnumCheckHardTruth:
    """A name-rule hit whose output CANNOT satisfy a CHECK enum must be overridden.

    Extends the existing ``gender`` reconciliation (choice-vs-CHECK): there
    the spec was already ``choice`` and only the values were wrong. Here
    the name rule produces a non-enum generator (``sentence``), which is
    guaranteed to violate the constraint — same principle, earlier stage.
    """

    def test_exact_rule_sentence_overridden_by_check_enum(self, db_with_title_enum: str) -> None:
        """``title`` -> sentence is deterministic-IN violation; CHECK enum wins."""
        with DataOrchestrator(db_with_title_enum, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="employees",
                count=10,
                columns=None,
                column_configs=None,
                enrich=False,
            )
        title_spec = specs.get("title")
        assert title_spec is not None
        assert title_spec.generator_name == "choice"
        assert title_spec.params.get("choices") == ["engineer", "manager", "director", "vp"]

    def test_fill_table_satisfies_enum_check(self, db_with_title_enum: str) -> None:
        """End-to-end: zero-config fill succeeds and every row satisfies the enum."""
        with DataOrchestrator(db_with_title_enum, provider_name="base") as orch:
            result = orch.fill_table("employees", count=20)
        assert result.count == 20
        assert result.errors == []

        conn = sqlite3.connect(db_with_title_enum)
        rows = conn.execute("SELECT title FROM employees").fetchall()
        conn.close()
        allowed = {"engineer", "manager", "director", "vp"}
        assert all((t,) and t[0] in allowed for t in rows)

    def test_unrelated_column_untouched(self, db_with_title_enum: str) -> None:
        """``note`` also hits the ``sentence`` EXACT rule but has NO CHECK — must stay untouched."""
        with DataOrchestrator(db_with_title_enum, provider_name="base") as orch:
            specs, _, _, _ = orch._resolve_specs(
                table_name="employees",
                count=10,
                columns=None,
                column_configs=None,
                enrich=False,
            )
        note_spec = specs.get("note")
        assert note_spec is not None
        # No CHECK constraint on note → name rule keeps its original output.
        assert note_spec.generator_name == "sentence"
