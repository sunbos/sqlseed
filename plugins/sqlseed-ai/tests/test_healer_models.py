"""Tests for healer.models module."""

from __future__ import annotations

from sqlseed_ai.healer.models import (
    DegradeReason,
    HealAttempt,
    HealResult,
    SubgraphTask,
)

from tests.assertions import assert_empty


def test_degrade_reason_enum_values():
    assert DegradeReason.LLM_TIMEOUT.value == "llm_timeout"
    assert DegradeReason.LLM_OSCILLATION.value == "llm_oscillation"


def test_subgraph_task_defaults():
    task = SubgraphTask(task_id="t1", tables=["users"])
    assert task.is_scc is False
    assert_empty(task.parent_context, dict)


def test_heal_result_defaults():
    r = HealResult(
        config={"tables": []},
        applied_fixes=[],
        degraded_columns=[],
        degrade_reasons={},
    )
    assert r.total_attempts == 0
    assert r.total_elapsed == 0.0
    assert_empty(r.learned_contracts, list)


def test_heal_attempt_optional_error():
    """HealAttempt.error_message defaults to None; applied_fixes defaults to empty list."""
    attempt = HealAttempt(
        level=1,
        failure_type=None,
        latency_ms=500,
        token_estimate=100,
    )
    assert attempt.error_message is None
    assert_empty(attempt.applied_fixes, list)
    assert attempt.failure_type is None


def test_degrade_reason_cascade_value():
    """CASCADE reason is used by ProgressiveDegrader for downstream columns."""
    assert DegradeReason.CASCADE.value == "cascade"
