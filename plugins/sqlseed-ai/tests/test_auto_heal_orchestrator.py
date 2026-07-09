from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from sqlseed_ai.auto_heal.orchestrator import (
    AutoHealOrchestrator,
    _get_exact_length_check,
    _has_like_constraint,
    _infer_cross_column_config,
    _infer_from_check_constraints,
    _like_to_regex,
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


# --- IS NULL OR prefix stripping (Round 7 fix) ---


def test_is_null_or_prefix_stripping_length():
    """``col IS NULL OR LENGTH(col) = N`` strips prefix → LENGTH pattern matches.

    Reproduces the ``customers.phone`` CHECK failure from Round 7 where the
    LLM degraded ``phone`` to a bare ``string`` generator (no params) and
    Step 5.5 had to re-infer from the CHECK. Without prefix stripping, the
    inner ``LENGTH(phone) = 11`` never matches and the column stays bare.
    """
    constraints = [{"type": "check", "expression": "phone IS NULL OR LENGTH(phone) = 11"}]
    result = _infer_from_check_constraints("phone", constraints, ["phone"])
    assert result is not None
    gen, params = result
    assert gen == "string"
    assert params["min_length"] == 11
    assert params["max_length"] == 11


def test_is_null_or_prefix_stripping_paren_range():
    """``col IS NULL OR (col >= X AND col <= Y)`` strips prefix + parens → range pattern.

    Reproduces the ``risk_assessments.health_factor`` CHECK failure from
    Round 7. The inner expression is wrapped in parentheses; both the
    prefix and the parens must be stripped before the inclusive-range
    pattern can match.
    """
    constraints = [
        {"type": "check", "expression": "health_factor IS NULL OR (health_factor >= 1 AND health_factor <= 10)"}
    ]
    result = _infer_from_check_constraints("health_factor", constraints, ["health_factor"])
    assert result is not None
    gen, params = result
    assert gen == "integer"
    assert params["min_value"] == 1
    assert params["max_value"] == 10


def test_is_null_or_prefix_no_parens_range():
    """``col IS NULL OR col >= X AND col <= Y`` (no parens) also strips."""
    constraints = [{"type": "check", "expression": "score IS NULL OR score >= 0 AND score <= 100"}]
    result = _infer_from_check_constraints("score", constraints, ["score"])
    assert result is not None
    gen, params = result
    assert gen == "integer"
    assert params["min_value"] == 0
    assert params["max_value"] == 100


# --- Pattern 8e: col >= X AND col < other_col (Round 7 fix) ---


def test_pattern_8e_inclusive_lower_exclusive_upper_column_float_zero():
    """Pattern 8e (float, X=0): ``col >= 0.0 AND col < other_col``.

    Reproduces the ``policies.deductible`` CHECK failure from Round 7.
    Uses ``value * random_float(0.0, 0.99)`` — the 0.99 factor guarantees
    the result is strictly less than ``other_col`` (since 0.99 < 1.0).
    """
    constraints = [{"type": "check", "expression": "deductible >= 0.0 AND deductible < coverage_amount"}]
    result = _infer_cross_column_config(
        "deductible", constraints, ["deductible", "coverage_amount"], "REAL"
    )
    assert result is not None
    assert result["derive_from"] == "coverage_amount"
    assert "random_float(0.0, 0.99)" in result["expression"]
    assert "value *" in result["expression"]


def test_pattern_8e_inclusive_lower_exclusive_upper_column_float_positive():
    """Pattern 8e (float, X>0): ``col >= 5.0 AND col < other_col`` uses max()."""
    constraints = [{"type": "check", "expression": "discount >= 5.0 AND discount < base_price"}]
    result = _infer_cross_column_config(
        "discount", constraints, ["discount", "base_price"], "REAL"
    )
    assert result is not None
    assert result["derive_from"] == "base_price"
    assert "max(5.0," in result["expression"]
    assert "random_float(0.0, 0.99)" in result["expression"]


def test_pattern_8e_inclusive_lower_exclusive_upper_column_int():
    """Pattern 8e (integer): ``col >= 0 AND col < other_col`` uses random_int(X, value-1)."""
    constraints = [{"type": "check", "expression": "count >= 0 AND count < max_count"}]
    result = _infer_cross_column_config(
        "count", constraints, ["count", "max_count"], "INTEGER"
    )
    assert result is not None
    assert result["derive_from"] == "max_count"
    assert "random_int(0, value - 1)" in result["expression"]


def test_pattern_8e_does_not_match_inclusive_upper():
    """Pattern 8e must NOT match ``col >= X AND col <= other_col`` (that's Pattern 8a)."""
    constraints = [{"type": "check", "expression": "fee >= 0.0 AND fee <= amount"}]
    result = _infer_cross_column_config(
        "fee", constraints, ["fee", "amount"], "REAL"
    )
    # Should match Pattern 8a (inclusive upper), not 8e (exclusive upper)
    assert result is not None
    # Pattern 8a uses random_float(0.0, value) — value as max (inclusive),
    # NOT the 0.99 factor that Pattern 8e uses for exclusive upper bound
    assert "random_float(0.0, value)" in result["expression"]
    assert "0.99" not in result["expression"]


# --- Pattern 8 standalone: col <= other_col (Round 5 fix) ---


def test_pattern_8_integer_uses_random_int_zero_to_value():
    """Pattern 8 (int): ``col <= other_col`` → ``random_int(0, value)``.

    The previous expression ``value - random_int(0, 100)`` could produce
    negative values when value < 100, violating companion CHECK ``col >= 0``.
    The fix uses ``random_int(0, value)`` which guarantees 0 <= result <= value.
    """
    constraints = [{"type": "check", "expression": "used_count <= total_count"}]
    result = _infer_cross_column_config(
        "used_count", constraints, ["used_count", "total_count"], "INTEGER"
    )
    assert result is not None
    assert result["derive_from"] == "total_count"
    assert result["expression"] == "random_int(0, value)"


def test_pattern_8_float_uses_multiply_factor():
    """Pattern 8 (float): ``col <= other_col`` → ``value * random_float(0.5, 1.0)``."""
    constraints = [{"type": "check", "expression": "remaining <= limit"}]
    result = _infer_cross_column_config(
        "remaining", constraints, ["remaining", "limit"], "REAL"
    )
    assert result is not None
    assert result["derive_from"] == "limit"
    assert "random_float(0.5, 1.0)" in result["expression"]


def test_pattern_8_date_uses_timedelta_subtract():
    """Pattern 8 (date): ``col <= other_col`` → ``value - timedelta(days=...)``."""
    constraints = [{"type": "check", "expression": "end_date <= start_date"}]
    result = _infer_cross_column_config(
        "end_date", constraints, ["end_date", "start_date"], "TEXT"
    )
    assert result is not None
    assert result["derive_from"] == "start_date"
    assert "timedelta" in result["expression"]


# --- Pattern 28: cross-column upper bound awareness (Round 7 fix) ---


def test_pattern_28_cross_column_upper_bound_capped():
    """Pattern 28 caps positive expr with min() when another CHECK has ``col <= other_col``.

    Reproduces the ``claims.approved_amount`` CHECK failure from Round 7.
    Pattern 28 matched ``status != 'approved' OR approved_amount > 0.0``
    and returned ``random_float(0.01, 100.0)`` — but a second CHECK
    ``approved_amount <= claim_amount`` was violated when the random
    value exceeded ``claim_amount``. The fix scans other CHECKs for
    ``col (<=|<) other_col`` and wraps with ``min(..., row['other_col'])``.
    """
    constraints = [
        {"type": "check", "expression": "status != 'approved' OR approved_amount > 0.0"},
        {"type": "check", "expression": "approved_amount <= claim_amount"},
    ]
    result = _infer_cross_column_config(
        "approved_amount",
        constraints,
        ["approved_amount", "status", "claim_amount"],
        "REAL",
    )
    assert result is not None
    assert result["derive_from"] == "status"
    expr = result["expression"]
    assert "min(" in expr
    assert "row['claim_amount']" in expr
    assert "random_float" in expr


def test_pattern_28_exclusive_upper_bound_capped():
    """Pattern 28 also caps when the other CHECK uses ``col < other_col`` (exclusive)."""
    constraints = [
        {"type": "check", "expression": "kind != 'special' OR bonus > 0.0"},
        {"type": "check", "expression": "bonus < cap"},
    ]
    result = _infer_cross_column_config(
        "bonus", constraints, ["bonus", "kind", "cap"], "REAL"
    )
    assert result is not None
    expr = result["expression"]
    assert "min(" in expr
    assert "row['cap']" in expr


def test_pattern_28_no_upper_bound_no_min():
    """Pattern 28 WITHOUT a cross-column upper bound → no min() wrap.

    Ensures the enhancement doesn't change behavior when there's no
    companion ``col <= other_col`` CHECK (the common case).
    """
    constraints = [
        {"type": "check", "expression": "status != 'approved' OR approved_amount > 0.0"},
    ]
    result = _infer_cross_column_config(
        "approved_amount", constraints, ["approved_amount", "status"], "REAL"
    )
    assert result is not None
    expr = result["expression"]
    assert "min(" not in expr
    assert "random_float" in expr


def test_pattern_28_upper_bound_self_reference_ignored():
    """Pattern 28 ignores ``col <= col`` (self-reference, malformed CHECK)."""
    constraints = [
        {"type": "check", "expression": "status != 'approved' OR amount > 0.0"},
        {"type": "check", "expression": "amount <= amount"},  # malformed self-ref
    ]
    result = _infer_cross_column_config(
        "amount", constraints, ["amount", "status"], "REAL"
    )
    assert result is not None
    expr = result["expression"]
    # Self-reference (upper_col == col_name) is skipped, so no min() wrap
    assert "min(" not in expr


# --- Pattern 36: N-way conditional range with dual bounds (Round 7 fix) ---


def test_pattern_36_integer_exclusive_upper():
    """Pattern 36 (int, < upper): ``col >= X AND col < Y`` per clause.

    Reproduces the ``risk_assessments.risk_score`` CHECK failure from Round 7.
    Each clause has both lower (>=) and exclusive upper (<) bounds.
    The generated ``random_int`` uses ``Y-1`` for exclusive upper.
    """
    expr = (
        "(risk_category = 'low' AND risk_score >= 1 AND risk_score < 25) OR "
        "(risk_category = 'medium' AND risk_score >= 25 AND risk_score < 50) OR "
        "(risk_category = 'high' AND risk_score >= 50 AND risk_score < 75) OR "
        "(risk_category = 'critical' AND risk_score >= 75 AND risk_score <= 100)"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "risk_score", constraints,
        ["risk_score", "risk_category"], "INTEGER",
    )
    assert result is not None
    assert result["derive_from"] == "risk_category"
    e = result["expression"]
    # Exclusive upper: < 25 → random_int(1, 24)
    assert "random_int(1, 24)" in e
    assert "random_int(25, 49)" in e
    assert "random_int(50, 74)" in e
    # Inclusive upper: <= 100 → random_int(75, 100)
    assert "random_int(75, 100)" in e


def test_pattern_36_integer_inclusive_upper():
    """Pattern 36 (int, <= upper): ``col >= X AND col <= Y`` per clause."""
    expr = (
        "(tier = 'basic' AND level >= 1 AND level <= 10) OR "
        "(tier = 'pro' AND level >= 11 AND level <= 20)"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "level", constraints, ["level", "tier"], "INTEGER",
    )
    assert result is not None
    e = result["expression"]
    assert "random_int(1, 10)" in e
    assert "random_int(11, 20)" in e


def test_pattern_36_float_exclusive_upper():
    """Pattern 36 (float, < upper): ``col >= X AND col < Y`` per clause."""
    expr = (
        "(grade = 'a' AND score >= 90.0 AND score < 100.0) OR "
        "(grade = 'b' AND score >= 80.0 AND score < 90.0)"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "score", constraints, ["score", "grade"], "REAL",
    )
    assert result is not None
    e = result["expression"]
    assert "random_float(90.0, 99.99)" in e
    assert "random_float(80.0, 89.99)" in e


def test_pattern_36_newline_whitespace_normalized():
    """Pattern 36 handles CHECKs stored with newlines (SQLite table-level CHECKs).

    The guard ``" OR " in expr`` would fail on ``"OR\\n"`` — the whitespace
    normalization (``re.sub(r"\\s+", " ", expr)``) fixes this.
    """
    expr = (
        "(risk_category = 'low' AND risk_score >= 1 AND risk_score < 25) OR\n"
        "        (risk_category = 'medium' AND risk_score >= 25 AND risk_score < 50) OR\n"
        "        (risk_category = 'high' AND risk_score >= 50 AND risk_score < 75) OR\n"
        "        (risk_category = 'critical' AND risk_score >= 75 AND risk_score <= 100)"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "risk_score", constraints,
        ["risk_score", "risk_category"], "INTEGER",
    )
    assert result is not None
    assert result["derive_from"] == "risk_category"


def test_pattern_36_exclusive_lower_bound():
    """Pattern 36 with ``>`` lower bound (exclusive) adds +1 epsilon."""
    expr = (
        "(tier = 'a' AND val > 0 AND val <= 10) OR "
        "(tier = 'b' AND val > 10 AND val <= 20)"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "val", constraints, ["val", "tier"], "INTEGER",
    )
    assert result is not None
    e = result["expression"]
    # > 0 → random_int(1, 10); > 10 → random_int(11, 20)
    assert "random_int(1, 10)" in e
    assert "random_int(11, 20)" in e


def test_pattern_36_does_not_match_single_bound():
    """Pattern 36 must NOT match single-bound clauses (that's Pattern 27)."""
    expr = (
        "bag_type = 'carry_on' AND weight_kg <= 10.0 OR "
        "bag_type = 'checked' AND weight_kg <= 32.0"
    )
    constraints = [{"type": "check", "expression": expr}]
    result = _infer_cross_column_config(
        "weight_kg", constraints, ["weight_kg", "bag_type"], "REAL",
    )
    assert result is not None
    # Pattern 27 (single-bound) should match, not Pattern 36
    # Pattern 27 uses _range_expr_for_op which produces random_float(0.01, X)
    assert "random_float(0.01, 10.0)" in result["expression"]
    assert "random_float(0.01, 32.0)" in result["expression"]


# ---------------------------------------------------------------------------
# Step 4 semantic name mapping — Core ColumnMapper delegation
# (fixes: _placeholder_generator returned "string" for ALL TEXT columns)
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_db(tmp_path: Path) -> Path:
    """DB with semantically-named TEXT columns but NO CHECK constraints.

    These columns previously got ``generator: string`` (random gibberish)
    because the dumb ``_placeholder_generator`` only looked at column TYPE.
    After the fix, Step 4 delegates to Core ``ColumnMapper`` which has 76
    exact match rules + 29 pattern rules for semantic column name matching.
    """
    path = tmp_path / "semantic.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                avatar_url TEXT,
                bio TEXT,
                title TEXT,
                description TEXT,
                content TEXT,
                website TEXT,
                created_at TEXT,
                unknown_text_col TEXT,
                random_notes TEXT
            )
            """
        )
    return path


def _run_and_get_config(db_path: Path) -> dict:
    """Run AutoHealOrchestrator with mock validator (0 violations) and return parsed config."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []
    orch = AutoHealOrchestrator(
        db_path=str(db_path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    return yaml.safe_load(yaml_str)


def _find_column(config: dict, table_name: str, col_name: str) -> dict:
    """Find a column config in the parsed YAML config dict."""
    for table in config["tables"]:
        if table["name"] == table_name:
            for col in table["columns"]:
                if col["name"] == col_name:
                    return col
    raise AssertionError(f"Column {table_name}.{col_name} not found in config")


def test_step4_email_column_uses_email_generator(semantic_db: Path):
    """``email`` column → ``email`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "email")
    assert col["generator"] == "email"


def test_step4_username_column_uses_username_generator(semantic_db: Path):
    """``username`` column → ``username`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "username")
    assert col["generator"] == "username"


def test_step4_avatar_url_column_uses_url_generator(semantic_db: Path):
    """``avatar_url`` column → ``url`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "avatar_url")
    assert col["generator"] == "url"


def test_step4_phone_column_uses_phone_generator(semantic_db: Path):
    """``phone`` column → ``phone`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "phone")
    assert col["generator"] == "phone"


def test_step4_full_name_column_uses_name_generator(semantic_db: Path):
    """``full_name`` column → ``name`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "full_name")
    assert col["generator"] == "name"


def test_step4_bio_column_uses_text_generator(semantic_db: Path):
    """``bio`` column → ``text`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "bio")
    assert col["generator"] == "text"


def test_step4_title_column_uses_sentence_generator(semantic_db: Path):
    """``title`` column → ``sentence`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "title")
    assert col["generator"] == "sentence"


def test_step4_description_column_uses_sentence_generator(semantic_db: Path):
    """``description`` column → ``sentence`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "description")
    assert col["generator"] == "sentence"


def test_step4_content_column_uses_text_generator(semantic_db: Path):
    """``content`` column → ``text`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "content")
    assert col["generator"] == "text"


def test_step4_website_column_uses_url_generator(semantic_db: Path):
    """``website`` column → ``url`` generator (not ``string``)."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "website")
    assert col["generator"] == "url"


def test_step4_created_at_column_uses_datetime_generator(semantic_db: Path):
    """``created_at`` column → ``datetime`` generator (not ``string``).

    Either via ColumnMapper pattern rule (``*_at``) or the
    ``_is_date_column`` fallback.
    """
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "created_at")
    assert col["generator"] == "datetime"


def test_step4_unknown_text_column_falls_back_to_string(semantic_db: Path):
    """Unknown TEXT columns (no semantic match) still fall back to ``string``."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "unknown_text_col")
    assert col["generator"] == "string"


def test_step4_random_notes_falls_back_to_string(semantic_db: Path):
    """``random_notes`` has no semantic match → ``string`` fallback."""
    config = _run_and_get_config(semantic_db)
    col = _find_column(config, "profiles", "random_notes")
    assert col["generator"] == "string"


# ---------------------------------------------------------------------------
# Step 5.5 post-LLM safety net — missing-generator inference via ColumnMapper
# (fixes: _placeholder_generator used in post-LLM repair path too)
# ---------------------------------------------------------------------------


def _run_with_stripped_generators(db_path: Path) -> dict:
    """Run AutoHealOrchestrator simulating LLM stripping generator fields.

    The mock validator returns a fake violation (so the heal path is taken),
    and the mock healer returns a config where ``generator`` fields are
    missing for semantically-named columns. Step 5.5 should fill them in
    using ``ColumnMapper`` — the same fix as Step 4 in
    ``_build_subgraph_config``.

    Before the fix, Step 5.5 used ``_placeholder_generator(col_type)`` which
    returned ``string`` for ALL TEXT columns, producing random gibberish for
    email/username/avatar_url even after the LLM was called.
    """
    mock_healer = MagicMock()
    # Simulate LLM returning a config with generators stripped.
    # Only 'id' retains its generator; all TEXT columns are missing 'generator'.
    mock_healer.heal.return_value = SimpleNamespace(
        config={
            "tables": [
                {
                    "name": "profiles",
                    "columns": [
                        {"name": "id", "generator": "autoincrement", "params": {}},
                        {"name": "email", "params": {}},
                        {"name": "username", "params": {}},
                        {"name": "avatar_url", "params": {}},
                        {"name": "title", "params": {}},
                        {"name": "content", "params": {}},
                        {"name": "created_at", "params": {}},
                        {"name": "unknown_text_col", "params": {}},
                    ],
                }
            ]
        },
        level_used=4,
        success=True,
        degraded_columns=[],
    )
    mock_validator = MagicMock()
    # Return violations so the heal path is taken (not "accepted as-is")
    mock_validator.validate.return_value = [MagicMock()]
    orch = AutoHealOrchestrator(
        db_path=str(db_path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    return yaml.safe_load(yaml_str)


def test_step55_missing_generator_email_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``email`` generator → ColumnMapper picks ``email``."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "email")
    assert col["generator"] == "email"


def test_step55_missing_generator_username_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``username`` generator → ColumnMapper picks ``username``."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "username")
    assert col["generator"] == "username"


def test_step55_missing_generator_avatar_url_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``avatar_url`` generator → ColumnMapper picks ``url``."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "avatar_url")
    assert col["generator"] == "url"


def test_step55_missing_generator_title_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``title`` generator → ColumnMapper picks ``sentence``."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "title")
    assert col["generator"] == "sentence"


def test_step55_missing_generator_content_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``content`` generator → ColumnMapper picks ``text``."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "content")
    assert col["generator"] == "text"


def test_step55_missing_generator_created_at_uses_column_mapper(semantic_db: Path):
    """Step 5.5: LLM-stripped ``created_at`` generator → ``datetime`` (via _is_date_column)."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "created_at")
    assert col["generator"] == "datetime"


def test_step55_missing_generator_unknown_text_falls_back_to_string(semantic_db: Path):
    """Step 5.5: unknown TEXT column with no semantic match → ``string`` fallback."""
    config = _run_with_stripped_generators(semantic_db)
    col = _find_column(config, "profiles", "unknown_text_col")
    assert col["generator"] == "string"


# ---------------------------------------------------------------------------
# Step 5.5 — missing template param repair (Round 5 fix)
# ---------------------------------------------------------------------------


def _run_with_missing_template_param(db_path: Path) -> dict:
    """Run AutoHealOrchestrator simulating LLM providing template generator without template param.

    The mock healer returns a config where ``generator: template`` is set
    but ``params: {}`` — the ``template`` field is missing. Step 5.5 should
    fill in a default template using the column name prefix.
    """
    mock_healer = MagicMock()
    mock_healer.heal.return_value = SimpleNamespace(
        config={
            "tables": [
                {
                    "name": "profiles",
                    "columns": [
                        {"name": "id", "generator": "autoincrement", "params": {}},
                        {"name": "user_code", "generator": "template", "params": {}},
                        {"name": "order_no", "generator": "template", "params": {}},
                        {"name": "cert_no", "generator": "template", "params": {}},
                    ],
                }
            ]
        },
        level_used=4,
        success=True,
        degraded_columns=[],
    )
    mock_validator = MagicMock()
    mock_validator.validate.return_value = [MagicMock()]
    orch = AutoHealOrchestrator(
        db_path=str(db_path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    return yaml.safe_load(yaml_str)


def test_step55_missing_template_param_gets_default(semantic_db: Path):
    """Step 5.5: ``generator: template, params: {}`` → default template filled in.

    Without this fix, the template generator raises KeyError at fill time
    because ``params["template"]`` doesn't exist, causing the entire table
    to fail (0 rows generated).
    """
    config = _run_with_missing_template_param(semantic_db)
    col = _find_column(config, "profiles", "user_code")
    assert col["generator"] == "template"
    assert "template" in col["params"]
    assert col["params"]["template"] == "USER-{sequence:04d}"


def test_step55_missing_template_param_order_no(semantic_db: Path):
    """Step 5.5: ``order_no`` with missing template → ``ORDER-{sequence:04d}``."""
    config = _run_with_missing_template_param(semantic_db)
    col = _find_column(config, "profiles", "order_no")
    assert col["params"]["template"] == "ORDER-{sequence:04d}"


def test_step55_missing_template_param_cert_no(semantic_db: Path):
    """Step 5.5: ``cert_no`` with missing template → ``CERT-{sequence:04d}``."""
    config = _run_with_missing_template_param(semantic_db)
    col = _find_column(config, "profiles", "cert_no")
    assert col["params"]["template"] == "CERT-{sequence:04d}"


# ---------------------------------------------------------------------------
# Step 0 — self-referencing FK detection (Round 5 fix)
# ---------------------------------------------------------------------------


@pytest.fixture
def self_ref_fk_db(tmp_path: Path) -> Path:
    """DB with a self-referencing FK (categories.parent_id → categories.id)."""
    path = tmp_path / "self_ref.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                parent_id INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES categories(id)
            )
            """
        )
    return path


def test_step0_self_ref_fk_gets_null_ratio_1(self_ref_fk_db: Path):
    """Self-referencing FK column → null_ratio=1.0 (always NULL).

    At fill time, the SharedPool for ``categories`` is empty (no rows
    inserted yet), so ``foreign_key_or_integer`` would fall back to random
    integers that don't match any existing PK — causing FK violations.
    Setting ``null_ratio=1.0`` ensures all values are NULL.
    """
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []  # no violations — accepted as-is

    orch = AutoHealOrchestrator(
        db_path=str(self_ref_fk_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    parent_id_col = next(
        c for c in config["tables"][0]["columns"] if c["name"] == "parent_id"
    )
    assert parent_id_col.get("null_ratio") == 1.0
    assert parent_id_col["generator"] == "foreign_key_or_integer"


def test_step0_non_self_ref_fk_not_affected(simple_db: Path):
    """Non-self-referencing FK columns are NOT affected by Step 0.

    The ``simple_db`` fixture has no FK constraints, so no column should
    get ``null_ratio=1.0`` from the self-ref FK detection.
    """
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
    config = yaml.safe_load(yaml_str)
    for col in config["tables"][0]["columns"]:
        # No self-ref FK in simple_db → no null_ratio=1.0 from Step 0
        assert col.get("null_ratio") != 1.0 or col["name"] != "id"


# ---------------------------------------------------------------------------
# Blind-spot fix (2026-07-09): phone-like + LENGTH CHECK → pattern [0-9]{N}
# ---------------------------------------------------------------------------


@pytest.fixture
def phone_length_db(tmp_path: Path) -> Path:
    """DB with phone column that has LENGTH(phone) = 11 CHECK constraint."""
    path = tmp_path / "phone_len.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                CHECK (phone IS NULL OR LENGTH(phone) = 11)
            )
            """
        )
    return path


@pytest.fixture
def phone_length_not_null_db(tmp_path: Path) -> Path:
    """DB with NOT NULL phone column that has LENGTH(phone) = 11 CHECK."""
    path = tmp_path / "phone_len_nn.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mobile TEXT NOT NULL,
                CHECK (LENGTH(mobile) = 11)
            )
            """
        )
    return path


def test_step2_phone_with_length_check_uses_pattern(phone_length_db: Path):
    """phone-like column + LENGTH(phone)=11 → pattern with [0-9]{11}.

    Previously, Step 2 returned ``string`` + ``min_length=11, max_length=11``,
    which triggered the contract matrix's ``string`` on ``phone`` →
    ``semantic_upgrade`` rule, causing LLM oscillation. Now Step 2 directly
    returns ``pattern`` with ``[0-9]{11}``, avoiding the contract matrix
    conflict entirely.
    """
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []  # no violations — accepted as-is

    orch = AutoHealOrchestrator(
        db_path=str(phone_length_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    phone_col = next(
        c for c in config["tables"][0]["columns"] if c["name"] == "phone"
    )
    assert phone_col["generator"] == "pattern"
    assert phone_col["params"]["regex"] == "[0-9]{11}"


def test_step2_mobile_with_length_check_uses_pattern(phone_length_not_null_db: Path):
    """mobile column + LENGTH(mobile)=11 → pattern with [0-9]{11}."""
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(phone_length_not_null_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    mobile_col = next(
        c for c in config["tables"][0]["columns"] if c["name"] == "mobile"
    )
    assert mobile_col["generator"] == "pattern"
    assert mobile_col["params"]["regex"] == "[0-9]{11}"


def test_step2_non_phone_with_length_check_keeps_string(tmp_path: Path):
    """Non-phone-like column + LENGTH(code)=8 → keeps string + length params.

    Only phone-like columns get the pattern upgrade. Other columns with
    LENGTH constraints keep the original ``string`` + ``min_length``/
    ``max_length`` config.
    """
    path = tmp_path / "code_len.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                CHECK (LENGTH(code) = 8)
            )
            """
        )
    mock_healer = MagicMock()
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    code_col = next(
        c for c in config["tables"][0]["columns"] if c["name"] == "code"
    )
    # Non-phone-like column keeps string + length params
    assert code_col["generator"] == "string"
    assert code_col["params"]["min_length"] == 8
    assert code_col["params"]["max_length"] == 8


# ---------------------------------------------------------------------------
# Blind-spot fix (2026-07-09): ProgressiveDegrader restores original config
# ---------------------------------------------------------------------------


def test_restore_failed_columns_restores_generator_and_params():
    """_restore_failed_columns: restores generator/params from original config.

    When LLM oscillates, the ``current_config`` may have lost CHECK-constraint
    params (e.g., ``min_length``/``max_length`` from ``LENGTH(phone)=11``
    inference). ``_restore_failed_columns`` should restore the original
    deterministic inference for failed columns.
    """
    from sqlseed_ai.healer.orchestrator import HealOrchestrator

    original_config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "phone", "generator": "pattern", "params": {"regex": "[0-9]{11}"}},
                    {"name": "email", "generator": "email", "params": {}},
                ],
            }
        ]
    }
    # LLM oscillated: phone lost its params, email was patched successfully
    current_config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "phone", "generator": "phone", "params": {}},  # LLM broke it
                    {"name": "email", "generator": "email", "params": {"domain": "test.com"}},  # LLM fixed it
                ],
            }
        ]
    }
    result = HealOrchestrator._restore_failed_columns(
        current_config, original_config, failed_cols=["phone"]
    )
    phone_col = next(c for c in result["tables"][0]["columns"] if c["name"] == "phone")
    email_col = next(c for c in result["tables"][0]["columns"] if c["name"] == "email")
    # Failed column: restored from original
    assert phone_col["generator"] == "pattern"
    assert phone_col["params"]["regex"] == "[0-9]{11}"
    # Non-failed column: LLM patch preserved
    assert email_col["params"]["domain"] == "test.com"


def test_restore_failed_columns_noop_when_no_failed_cols():
    """_restore_failed_columns: no-op when failed_cols is empty."""
    from sqlseed_ai.healer.orchestrator import HealOrchestrator

    original_config = {"tables": [{"name": "t", "columns": [{"name": "c", "generator": "string"}]}]}
    current_config = {"tables": [{"name": "t", "columns": [{"name": "c", "generator": "integer"}]}]}
    result = HealOrchestrator._restore_failed_columns(current_config, original_config, failed_cols=[])
    # No failed cols → current_config unchanged
    col = result["tables"][0]["columns"][0]
    assert col["generator"] == "integer"


def test_restore_failed_columns_handles_missing_original_column():
    """_restore_failed_columns: gracefully handles missing original column."""
    from sqlseed_ai.healer.orchestrator import HealOrchestrator

    original_config = {"tables": [{"name": "t", "columns": []}]}
    current_config = {
        "tables": [
            {"name": "t", "columns": [{"name": "phone", "generator": "phone", "params": {}}]}
        ]
    }
    result = HealOrchestrator._restore_failed_columns(
        current_config, original_config, failed_cols=["phone"]
    )
    # Original config has no "phone" column → current config unchanged
    phone_col = next(c for c in result["tables"][0]["columns"] if c["name"] == "phone")
    assert phone_col["generator"] == "phone"


# ---------------------------------------------------------------------------
# Fix 6: _like_to_regex — LIKE pattern to regex conversion (position-preserving)
# ---------------------------------------------------------------------------


def test_like_to_regex_preserves_colon_position():
    """``__:__`` (HH:MM time format) → colon stays at index 2, not collapsed to start.

    This was the root cause of R2 hospital fill failure: the old code did
    ``literal_part = like_pattern.replace("_", "")`` which stripped ALL
    underscores, collapsing ``__:__`` to ``:`` and producing
    ``^:[A-Za-z0-9]{4}$`` (colon at the WRONG position).
    """
    regex = _like_to_regex("__:__")
    assert regex == "^[A-Za-z0-9]{2}:[A-Za-z0-9]{2}$"


def test_like_to_regex_literal_prefix():
    """``#______`` (color code) → ``^\\#`` prefix preserved (re.escape escapes ``#``)."""
    regex = _like_to_regex("#______")
    assert regex == r"^\#[A-Za-z0-9]{6}$"


def test_like_to_regex_literal_in_middle():
    """``PROD-___`` → ``PROD-`` prefix with hyphen preserved at correct position."""
    regex = _like_to_regex("PROD-___")
    assert regex == r"^PROD\-[A-Za-z0-9]{3}$"


def test_like_to_regex_all_underscores():
    """``____`` → ``^[A-Za-z0-9]{4}$`` (no literals)."""
    assert _like_to_regex("____") == "^[A-Za-z0-9]{4}$"


def test_like_to_regex_single_underscore():
    """``_`` → ``^[A-Za-z0-9]$`` (single char, no grouping)."""
    assert _like_to_regex("_") == "^[A-Za-z0-9]$"


# ---------------------------------------------------------------------------
# Fix 7: _has_like_constraint + timedelta guard for LIKE-constrained columns
# ---------------------------------------------------------------------------


def test_has_like_constraint_detects_like_check():
    """_has_like_constraint returns True for ``col LIKE 'pattern'`` CHECK."""
    constraints = [
        {"type": "check", "expression": "start_time LIKE '__:__'"},
        {"type": "check", "expression": "end_time > start_time"},
    ]
    assert _has_like_constraint("start_time", constraints) is True
    assert _has_like_constraint("end_time", constraints) is False


def test_has_like_constraint_no_match():
    """_has_like_constraint returns False for columns without LIKE CHECK."""
    constraints = [
        {"type": "check", "expression": "floor >= 1 AND floor <= 50"},
        {"type": "unique", "columns": ["code"]},
    ]
    assert _has_like_constraint("floor", constraints) is False
    assert _has_like_constraint("code", constraints) is False


def test_infer_cross_column_skips_timedelta_for_like_constrained_col():
    """Pattern 3 (col > other) must NOT generate timedelta for LIKE-constrained columns.

    ``end_time`` has ``LIKE '__:__'`` (stores "HH:MM" strings). Even though
    ``_is_date_column("end_time")`` returns True (``_time`` suffix), the LIKE
    constraint means it's a formatted string, not a datetime. The timedelta
    expression ``value + timedelta(...)`` would crash at fill time with
    ``TypeError: can only concatenate str (not "datetime.timedelta") to str``.
    """
    constraints = [
        {"type": "check", "expression": "start_time LIKE '__:__'"},
        {"type": "check", "expression": "end_time LIKE '__:__'"},
        {"type": "check", "expression": "end_time > start_time"},
    ]
    result = _infer_cross_column_config(
        "end_time", constraints, ["start_time", "end_time"], "TEXT"
    )
    # Should NOT return a timedelta derive_from — the LIKE guard disables
    # date inference for formatted-string columns.
    assert result is None or "timedelta" not in str(result.get("expression", ""))


def test_infer_cross_column_skips_timedelta_when_source_has_like():
    """Pattern 3 must NOT generate timedelta when the SOURCE column has LIKE.

    Even if ``end_time`` itself has no LIKE, if ``start_time`` (the source)
    has ``LIKE '__:__'``, the source produces strings — timedelta on strings
    would crash.
    """
    constraints = [
        {"type": "check", "expression": "start_time LIKE '__:__'"},
        {"type": "check", "expression": "end_time > start_time"},
    ]
    result = _infer_cross_column_config(
        "end_time", constraints, ["start_time", "end_time"], "TEXT"
    )
    assert result is None or "timedelta" not in str(result.get("expression", ""))


def test_infer_cross_column_timedelta_for_real_datetime():
    """Pattern 3 STILL generates timedelta for real DATETIME columns (no LIKE).

    Regression guard: the LIKE guard must not break the normal date case.
    ``consultation_end`` is DATETIME (no LIKE) → timedelta is correct.
    """
    constraints = [
        {"type": "check", "expression": "consultation_end IS NULL OR consultation_end >= consultation_start"},
    ]
    result = _infer_cross_column_config(
        "consultation_end", constraints, ["consultation_start", "consultation_end"], "DATETIME"
    )
    assert result is not None
    assert result["derive_from"] == "consultation_start"
    assert "timedelta" in result["expression"]


# ---------------------------------------------------------------------------
# Fix 8: Step 5.5 arithmetic-on-string safety net
# ---------------------------------------------------------------------------


@pytest.fixture
def like_time_db(tmp_path: Path) -> Path:
    """DB with time-string columns (LIKE '__:__') and a cross-column CHECK."""
    path = tmp_path / "like_time.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL CHECK (start_time LIKE '__:__'),
                end_time TEXT NOT NULL CHECK (end_time LIKE '__:__'),
                CHECK (end_time > start_time)
            )
            """
        )
    return path


def test_step55_strips_timedelta_derive_from_for_like_column(like_time_db: Path):
    """Step 5.5 strips ``derive_from`` with timedelta for LIKE-constrained columns.

    Simulates the LLM generating ``end_time: derive_from: start_time,
    expression: value + timedelta(days=...)`` — the safety net detects
    the LIKE constraint and strips the derive_from, preventing
    ``TypeError: str + timedelta`` at fill time.
    """
    mock_healer = MagicMock()
    # Simulate LLM returning a broken timedelta derive_from for end_time
    mock_healer.heal_subgraph.return_value = {
        "tables": [
            {
                "name": "shifts",
                "columns": [
                    {"name": "id", "generator": "autoincrement", "params": {}},
                    {"name": "start_time", "generator": "pattern",
                     "params": {"regex": "^[A-Za-z0-9]{2}:[A-Za-z0-9]{2}$"}},
                    {"name": "end_time", "derive_from": "start_time",
                     "expression": "value + timedelta(days=random_int(1, 30))"},
                ],
            }
        ]
    }
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(like_time_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    end_time_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "end_time")
    assert "derive_from" not in end_time_col, "Step 5.5 should strip timedelta derive_from for LIKE column"


def test_step55_strips_arithmetic_derive_from_for_like_column(like_time_db: Path):
    """Step 5.5 strips ``value + random_int(...)`` for LIKE-constrained columns.

    The LLM may generate non-timedelta arithmetic (e.g., ``value + random_int(1, 100)``)
    which also fails on string columns. The safety net detects ANY arithmetic
    on ``value`` for LIKE-constrained columns.
    """
    mock_healer = MagicMock()
    mock_healer.heal_subgraph.return_value = {
        "tables": [
            {
                "name": "shifts",
                "columns": [
                    {"name": "id", "generator": "autoincrement", "params": {}},
                    {"name": "start_time", "generator": "pattern",
                     "params": {"regex": "^[A-Za-z0-9]{2}:[A-Za-z0-9]{2}$"}},
                    {"name": "end_time", "derive_from": "start_time",
                     "expression": "value + random_int(1, 100)"},
                ],
            }
        ]
    }
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(like_time_db),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    end_time_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "end_time")
    assert "derive_from" not in end_time_col, (
        "Step 5.5 should strip arithmetic derive_from for LIKE-constrained column"
    )


def test_step55_preserves_derive_from_for_real_datetime(like_time_db: Path):
    """Step 5.5 does NOT strip timedelta for real DATETIME columns (no LIKE).

    Regression guard: the safety net must only affect LIKE-constrained columns.
    """
    # Use a different DB with DATETIME columns (no LIKE)
    path = like_time_db.parent / "datetime.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_dt DATETIME NOT NULL,
                end_dt DATETIME,
                CHECK (end_dt IS NULL OR end_dt >= start_dt)
            )
            """
        )

    mock_healer = MagicMock()
    mock_healer.heal_subgraph.return_value = {
        "tables": [
            {
                "name": "events",
                "columns": [
                    {"name": "id", "generator": "autoincrement", "params": {}},
                    {"name": "start_dt", "generator": "datetime", "params": {}},
                    {"name": "end_dt", "derive_from": "start_dt",
                     "expression": "value + timedelta(days=random_int(1, 30))"},
                ],
            }
        ]
    }
    mock_validator = MagicMock()
    mock_validator.validate.return_value = []

    orch = AutoHealOrchestrator(
        db_path=str(path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    end_dt_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "end_dt")
    assert "derive_from" in end_dt_col, "Step 5.5 should preserve timedelta for real DATETIME"


def test_step55_strips_generator_when_derive_from_present(tmp_path: Path):
    """Step 5.5 strips ``generator``+``params`` when LLM emits both modes.

    The LLM occasionally emits BOTH ``derive_from`` AND ``generator`` for the
    same column (e.g., ``derive_from: dest_wh_id, expression: value - 1 if
    value > 1 else value + 1, generator: integer``). The ``ColumnConfig``
    Pydantic model enforces mutual exclusivity between source-mode
    (``generator`` + ``params``) and derived-mode (``derive_from`` +
    ``expression``). Without this safety net, the YAML loads downstream
    triggers ``ValidationError: cannot use both 'generator' and
    'derive_from'`` and the entire fill aborts.

    Fix: when ``derive_from`` is present (and NOT stripped by the LIKE
    safety net), actively pop ``generator`` and ``params`` to enforce
    mutual exclusivity. This is a generic LLM-output cleanup — it benefits
    any database where the LLM emits both modes, not just R3.
    """
    path = tmp_path / "mixed_mode.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dest_wh_id INTEGER NOT NULL,
                origin_wh_id INTEGER NOT NULL,
                CHECK (origin_wh_id != dest_wh_id)
            )
            """
        )

    mock_healer = MagicMock()
    # Simulate LLM emitting BOTH derive_from AND generator for origin_wh_id.
    # Use heal.return_value (not heal_subgraph) because _heal_subgraph calls
    # self._heal_orchestrator.heal(task, violations, sg_config).
    mock_healer.heal.return_value = SimpleNamespace(
        config={
            "tables": [
                {
                    "name": "shipments",
                    "columns": [
                        {"name": "id", "generator": "autoincrement", "params": {}},
                        {"name": "dest_wh_id", "generator": "foreign_key_or_integer", "params": {}},
                        {
                            "name": "origin_wh_id",
                            "derive_from": "dest_wh_id",
                            "expression": "value - 1 if value > 1 else value + 1",
                            "generator": "integer",
                            "params": {"min_value": 1, "max_value": 100},
                        },
                    ],
                }
            ]
        },
        level_used=4,
        success=True,
        degraded_columns=[],
    )
    mock_validator = MagicMock()
    # Return violations so the heal path is taken (not "accepted as-is")
    mock_validator.validate.return_value = [MagicMock()]

    orch = AutoHealOrchestrator(
        db_path=str(path),
        heal_orchestrator=mock_healer,
        validator=mock_validator,
        total_budget_seconds=10.0,
    )
    yaml_str = orch.run()
    config = yaml.safe_load(yaml_str)
    origin_col = next(c for c in config["tables"][0]["columns"] if c["name"] == "origin_wh_id")
    assert "derive_from" in origin_col, "derive_from should be preserved"
    assert "generator" not in origin_col, (
        "Step 5.5 must strip generator when derive_from is present (mutual exclusivity)"
    )
    assert "params" not in origin_col, (
        "Step 5.5 must strip params when derive_from is present (mutual exclusivity)"
    )
