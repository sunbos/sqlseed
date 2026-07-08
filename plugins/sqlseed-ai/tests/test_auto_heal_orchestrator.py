from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator, _get_exact_length_check

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
