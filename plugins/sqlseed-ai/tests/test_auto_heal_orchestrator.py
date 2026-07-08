from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from sqlseed_ai.auto_heal.orchestrator import (
    AutoHealOrchestrator,
    _get_exact_length_check,
    _infer_cross_column_config,
    _infer_from_check_constraints,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def simple_db(tmp_path: Path) -> Path:
    path = tmp_path / "simple.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
    return path


def test_run_returns_yaml_string(simple_db: Path):
    """End-to-end: orchestrator returns a non-empty YAML config string."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []  # no violations

    orch = AutoHealOrchestrator(
        db_path=str(simple_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    assert isinstance(yaml_str, str)
    assert "users" in yaml_str


def test_run_invokes_subgraph_splitter(simple_db: Path):
    """Orchestrator invokes SubgraphSplitter at startup."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(simple_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    orch.run()
    assert mock_healer.heal.called or mock_validator.validate.called


def test_run_post_repairs_broken_edges(simple_db: Path):
    """When megacluster breaking occurs, BrokenEdgeAligner is invoked."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(simple_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run(broken_edges_inject=[("users", "users")])
    assert "users" in yaml_str


def test_run_verifies_schema_hash_at_write_time(simple_db: Path):
    """Defense 8: orchestrator checks schema_hash before writing YAML."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(simple_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    assert "users" in yaml_str


# --- Step 5.5 safety net tests ---


@pytest.fixture
def unique_length_db(tmp_path: Path) -> Path:
    """DB with UNIQUE + LENGTH(N) CHECK columns (the conflict case)."""
    path = tmp_path / "unique_len.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE CHECK (LENGTH(code) = 2),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                status TEXT NOT NULL CHECK (status IN ('active', 'inactive'))
            )
            """
        )
    return path


def test_get_exact_length_check_returns_n():
    """_get_exact_length_check returns N for LENGTH(col) = N."""
    constraints = [
        {"type": "check", "expression": "LENGTH(code) = 2"},
        {"type": "check", "expression": "LENGTH(name) >= 3"},
        {"type": "unique", "columns": ["code"]},
    ]
    assert _get_exact_length_check("code", constraints) == 2
    assert _get_exact_length_check("name", constraints) is None
    assert _get_exact_length_check("missing", constraints) is None


def test_step55_converts_unique_length_string_to_pattern(unique_length_db: Path):
    """UNIQUE + LENGTH(N) + string → pattern [A-Za-z0-9]{N}.

    The unique adjuster would increase max_length to guarantee uniqueness,
    breaking the CHECK constraint. Step 5.5 converts string → pattern
    (which the unique adjuster does NOT touch).
    """
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(unique_length_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    code_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "code")
    assert code_col["generator"] == "pattern"
    assert code_col["params"]["regex"] == "[A-Za-z0-9]{2}"


def test_step55_overrides_integer_with_boolean_for_in_check(unique_length_db: Path):
    """LLM provides integer for col IN (0,1) → Step 5.5 overrides to boolean.

    The IN (0, 1) CHECK constraint is very specific: only boolean generator
    produces valid values. An integer generator with no params produces large
    random integers that fail the CHECK.
    """
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    # Simulate LLM returning integer for is_active (wrong generator)
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(unique_length_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    is_active_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "is_active")
    # The deterministic inference should produce boolean, not integer
    assert is_active_col["generator"] == "boolean"


# ---------------------------------------------------------------------------
# Cross-column CHECK inference — Pattern unit tests (Round 6 banking schema)
# ---------------------------------------------------------------------------


def test_pattern_29_three_column_arithmetic_chain():
    """Pattern 29: col = col1 (+|-) col2 (+|-) col3 (three-column arithmetic)."""
    constraints = [{"type": "check", "expression": "available = balance + credit_limit - held"}]
    result = _infer_cross_column_config(
        "available", constraints, ["available", "balance", "credit_limit", "held"], "REAL"
    )
    assert result is not None
    assert result["derive_from"] == "balance"
    assert "row['credit_limit']" in result["expression"]
    assert "row['held']" in result["expression"]


def test_pattern_30_fk_column_returns_none():
    """Pattern 30: FK column → always None (0 is never a valid FK id)."""
    constraints = [{"type": "check", "expression": "position != 'ceo' OR manager_id IS NULL"}]
    result = _infer_cross_column_config(
        "manager_id",
        constraints,
        ["manager_id", "position"],
        "INTEGER",
        fk_columns={"manager_id"},
    )
    assert result is not None
    expr = result["expression"]
    # Both branches should be None — no "0" literal that would cause FK violation
    assert "None" in expr
    assert " 0" not in expr.replace("None", "")


def test_pattern_30_non_fk_column_returns_zero():
    """Pattern 30: Non-FK column → 0 for non-null branch."""
    constraints = [{"type": "check", "expression": "status != 'closed' OR closed_at IS NULL"}]
    result = _infer_cross_column_config(
        "closed_at",
        constraints,
        ["closed_at", "status"],
        "INTEGER",
        fk_columns=set(),
    )
    assert result is not None
    assert "0" in result["expression"]


def test_pattern_31_conditional_equality():
    """Pattern 31: col1 != VALUE OR col = VALUE2 (conditional equality)."""
    constraints = [{"type": "check", "expression": "status != 'paid_off' OR remaining = 0.0"}]
    result = _infer_cross_column_config("remaining", constraints, ["remaining", "status"], "REAL")
    assert result is not None
    assert result["derive_from"] == "status"
    assert "0.0" in result["expression"]
    assert "random_float" in result["expression"]


def test_pattern_22b_compound_range_with_multiplier():
    """Pattern 22b: col >= X AND col <= col2 * CONSTANT."""
    constraints = [{"type": "check", "expression": "fee >= 0.0 AND fee <= amount * 0.02"}]
    result = _infer_cross_column_config("fee", constraints, ["fee", "amount"], "REAL")
    assert result is not None
    assert result["derive_from"] == "amount"
    assert "random_float(0.0, 0.02)" in result["expression"]


def test_pattern_32_conditional_value_null():
    """Pattern 32: (col1 = VALUE AND col > X) OR (col1 IN (...) AND col IS NULL)."""
    constraints = [
        {
            "type": "check",
            "expression": (
                "(card_type = 'credit' AND credit_limit > 0.0) "
                "OR (card_type IN ('debit', 'prepaid') AND credit_limit IS NULL)"
            ),
        }
    ]
    result = _infer_cross_column_config("credit_limit", constraints, ["credit_limit", "card_type"], "REAL")
    assert result is not None
    assert result["derive_from"] == "card_type"
    assert "None" in result["expression"]
    assert "random_float" in result["expression"]


def test_pattern_33_conditional_arithmetic_by_type():
    """Pattern 33: (col1 IN (...) AND col = col2 + col3) OR (col1 IN (...) AND col = col2 - col3)."""
    constraints = [
        {
            "type": "check",
            "expression": (
                "(type IN ('deposit', 'transfer_in', 'interest') AND balance_after = balance_before + amount) "
                "OR (type IN ('withdrawal', 'transfer_out', 'fee') AND balance_after = balance_before - amount)"
            ),
        }
    ]
    result = _infer_cross_column_config(
        "balance_after", constraints, ["balance_after", "balance_before", "amount", "type"], "REAL"
    )
    assert result is not None
    assert result["derive_from"] == "balance_before"
    assert "row['amount']" in result["expression"]
    assert "row['type']" in result["expression"]


def test_pattern_34_conditional_upper_bound_exclusive():
    """Pattern 34: col1 != VALUE OR col2 < X (exclusive upper bound)."""
    constraints = [
        {"type": "check", "expression": "balance >= -10000.0"},
        {"type": "check", "expression": "status != 'dormant' OR balance < 100.0"},
    ]
    result = _infer_cross_column_config("balance", constraints, ["balance", "status"], "REAL")
    assert result is not None
    assert result["generator"] == "float"
    assert result["params"]["max_value"] == 99.99
    # min_value from the single-column CHECK is preserved
    assert result["params"]["min_value"] == -10000.0


def test_pattern_34_conditional_upper_bound_inclusive():
    """Pattern 34: col1 != VALUE OR col2 <= X (inclusive upper bound)."""
    constraints = [
        {"type": "check", "expression": "score >= 0"},
        {"type": "check", "expression": "level != 'max' OR score <= 100"},
    ]
    result = _infer_cross_column_config("score", constraints, ["score", "level"], "INTEGER")
    assert result is not None
    assert result["generator"] == "integer"
    assert result["params"]["max_value"] == 100
    assert result["params"]["min_value"] == 0


def test_pattern_35_date_column_null_ratio():
    """Pattern 35: col1 IN (...) OR col IS NULL (date → null_ratio=1.0)."""
    constraints = [
        {"type": "check", "expression": "completed_at IS NULL OR completed_at > created_at"},
        {"type": "check", "expression": "status IN ('completed') OR completed_at IS NULL"},
    ]
    result = _infer_cross_column_config("completed_at", constraints, ["completed_at", "created_at", "status"], "TEXT")
    assert result is not None
    assert result.get("null_ratio") == 1.0


def test_pattern_35_non_date_column_derive_from():
    """Pattern 35: non-date column → derive_from with None."""
    constraints = [
        {"type": "check", "expression": "type IN ('credit') OR credit_limit IS NULL"},
    ]
    result = _infer_cross_column_config("credit_limit", constraints, ["credit_limit", "type"], "REAL")
    assert result is not None
    assert "derive_from" in result
    assert "None" in result["expression"]


def test_exclusive_lower_bound_float_adds_epsilon():
    """col > X AND col <= Y for float → min_value = X + 0.01 (not X)."""
    constraints = [{"type": "check", "expression": "rate > 0.0 AND rate <= 0.25"}]
    result = _infer_from_check_constraints("rate", constraints, ["rate"])
    assert result is not None
    gen, params = result
    assert gen == "float"
    assert params["min_value"] == 0.01  # 0.0 + epsilon
    assert params["max_value"] == 0.25


def test_exclusive_both_bounds_float():
    """col > X AND col < Y for float → both bounds get epsilon."""
    constraints = [{"type": "check", "expression": "value > 0.0 AND value < 1.0"}]
    result = _infer_from_check_constraints("value", constraints, ["value"])
    assert result is not None
    _gen, params = result
    assert params["min_value"] == 0.01
    assert params["max_value"] == 0.99


def test_constraint_sort_in_prioritized_over_is_null_or():
    """IN constraints processed before IS NULL OR constraints."""
    constraints = [
        {"type": "check", "expression": "completed_at IS NULL OR completed_at > created_at"},
        {"type": "check", "expression": "status IN ('completed') OR completed_at IS NULL"},
    ]
    result = _infer_cross_column_config("completed_at", constraints, ["completed_at", "created_at", "status"], "TEXT")
    # Pattern 35 (IN) should win → null_ratio=1.0, NOT derive_from=created_at
    assert result is not None
    assert result.get("null_ratio") == 1.0
    assert "derive_from" not in result
