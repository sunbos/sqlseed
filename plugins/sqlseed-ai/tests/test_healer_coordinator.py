"""Tests for healer.coordinator module."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlseed_ai.healer.coordinator import Layer4Coordinator
from sqlseed_ai.healer.llm_healer import LLMHealer
from sqlseed_ai.healer.models import SubgraphTask
from sqlseed_ai.validator.models import ConstraintType, ViolationReport

if TYPE_CHECKING:
    from pathlib import Path

    pass


@pytest.fixture
def fake_validator():
    """Validator stub: always returns no violations (success)."""
    v = MagicMock()
    v.validate.return_value = []
    return v


@pytest.fixture
def fake_llm_client_success():
    """LLM client that always returns a valid JSON patch."""
    client = MagicMock()
    client.chat_completions_create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=('{"tables": [{"name": "users", "columns": [{"name": "email", "generator": "email"}]}]}')
                )
            )
        ]
    )
    return client


def test_heal_success_first_attempt(fake_validator, fake_llm_client_success, tmp_path: Path):
    """Successful heal on first attempt returns HealResult with no degrades."""
    with sqlite3.connect(str(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    snapshot = SchemaSnapshot(db_path=str(tmp_path / "t.db"))

    healer = LLMHealer(client=fake_llm_client_success, model="gemma-4-e4b-it")
    coord = Layer4Coordinator(
        healer=healer,
        validator=fake_validator,
        snapshot=snapshot,
        max_attempts=3,
        schema_hash="abc",
    )
    task = SubgraphTask(task_id="t1", tables=["users"])
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "integer"},  # wrong, will be patched
                ],
            }
        ]
    }
    violations = [
        ViolationReport(
            table="users",
            columns=["email"],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            message="type mismatch",
        )
    ]

    result = coord.reconcile(task, config, violations)
    assert result.degraded_columns == []
    assert result.total_attempts == 1


def test_heal_oscillation_triggers_degrade(tmp_path: Path):
    """Oscillation (same violations twice) triggers ProgressiveDegrader."""
    with sqlite3.connect(str(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    snapshot = SchemaSnapshot(db_path=str(tmp_path / "t.db"))

    # Validator always returns the same violation (oscillation)
    validator = MagicMock()
    violation = ViolationReport(
        table="users",
        columns=["email"],
        constraint_type=ConstraintType.CHECK,
        severity="crash",
        message="fail",
    )
    validator.validate.return_value = [violation]

    # LLM always returns a (useless) patch
    client = MagicMock()
    client.chat_completions_create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=('{"tables": [{"name": "users", "columns": [{"name": "email", "generator": "string"}]}]}')
                )
            )
        ]
    )
    healer = LLMHealer(client=client, model="gemma-4-e4b-it")

    coord = Layer4Coordinator(
        healer=healer,
        validator=validator,
        snapshot=snapshot,
        max_attempts=5,
        schema_hash="abc",
    )
    task = SubgraphTask(task_id="t1", tables=["users"])
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "integer"},
                ],
            }
        ]
    }

    result = coord.reconcile(task, config, [violation])
    # After oscillation detected, email should be degraded.
    # AI-H4 fix: _collect_failed_columns now returns "table:column" format
    # to avoid cross-table name collisions in multi-table SCC scenarios.
    assert "users:email" in result.degraded_columns
    assert result.degrade_reasons["users:email"].value == "llm_oscillation"


def test_heal_max_attempts_triggers_degrade(tmp_path: Path):
    """Reaching max_attempts triggers degrade (without oscillation).

    The validator returns DIFFERENT violations each call (different severity
    so the oscillation signature changes), so oscillation never triggers.
    The loop exhausts max_attempts and degrades with MAX_RETRIES_EXCEEDED.
    """
    with sqlite3.connect(str(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    snapshot = SchemaSnapshot(db_path=str(tmp_path / "t.db"))

    validator = MagicMock()
    violations_cycle = [
        [
            ViolationReport(
                table="users",
                columns=["email"],
                constraint_type=ConstraintType.CHECK,
                severity="crash",
                message="fail1",
            )
        ],
        [
            ViolationReport(
                table="users",
                columns=["email"],
                constraint_type=ConstraintType.UNIQUE,
                severity="unique_unsatisfiable",
                message="fail2",
            )
        ],
        [
            ViolationReport(
                table="users",
                columns=["email"],
                constraint_type=ConstraintType.NOT_NULL,
                severity="semantic_error",
                message="fail3",
            )
        ],
    ]
    validator.validate.side_effect = violations_cycle

    client = MagicMock()
    client.chat_completions_create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content=('{"tables": [{"name": "users", "columns": [{"name": "email", "generator": "string"}]}]}')
                )
            )
        ]
    )
    healer = LLMHealer(client=client, model="gemma-4-e4b-it")

    coord = Layer4Coordinator(
        healer=healer,
        validator=validator,
        snapshot=snapshot,
        max_attempts=2,
        schema_hash="abc",
    )
    task = SubgraphTask(task_id="t1", tables=["users"])
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "integer"},
                ],
            }
        ]
    }
    # Use a DIFFERENT initial violation (FK, semantic_error) so oscillation
    # does NOT trigger on the second iteration.
    initial_violation = ViolationReport(
        table="users",
        columns=["email"],
        constraint_type=ConstraintType.FK,
        severity="semantic_error",
        message="initial fail",
    )

    result = coord.reconcile(task, config, [initial_violation])
    # AI-H4 fix: _collect_failed_columns returns "table:column" format
    assert "users:email" in result.degraded_columns
    assert result.degrade_reasons["users:email"].value == "max_retries_exceeded"


def test_diff_learning_collects_candidates(fake_validator, fake_llm_client_success, tmp_path: Path):
    """Successful fixes are passed to DiffLearner and collected."""
    with sqlite3.connect(str(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    snapshot = SchemaSnapshot(db_path=str(tmp_path / "t.db"))

    healer = LLMHealer(client=fake_llm_client_success, model="gemma-4-e4b-it")
    coord = Layer4Coordinator(
        healer=healer,
        validator=fake_validator,
        snapshot=snapshot,
        max_attempts=3,
        schema_hash="abc",
    )
    task = SubgraphTask(task_id="t1", tables=["users"])
    config = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "generator": "integer"},
                    {"name": "email", "generator": "integer"},
                ],
            }
        ]
    }
    violations = [
        ViolationReport(
            table="users",
            columns=["email"],
            constraint_type=ConstraintType.CHECK,
            severity="crash",
            message="type mismatch",
        )
    ]

    result = coord.reconcile(task, config, violations)
    # DiffLearner is invoked; may or may not produce a contract depending on Defense 7
    # but the candidate list is at least populated/empty (not None)
    assert result.learned_contracts is not None
