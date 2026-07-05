"""Tests for healer.models module."""
from __future__ import annotations

from sqlseed_ai.healer.models import (
    DegradeReason,
    HealAttempt,
    HealResult,
    SubgraphTask,
)


def test_degrade_reason_enum_values():
    assert DegradeReason.LLM_TIMEOUT.value == "llm_timeout"
    assert DegradeReason.LLM_OSCILLATION.value == "llm_oscillation"


def test_subgraph_task_defaults():
    task = SubgraphTask(task_id="t1", tables=["users"])
    assert task.is_scc is False
    assert task.parent_context == {}


def test_heal_result_defaults():
    r = HealResult(
        config={"tables": []},
        applied_fixes=[],
        degraded_columns=[],
        degrade_reasons={},
    )
    assert r.total_attempts == 0
    assert r.total_elapsed == 0.0
    assert r.learned_contracts == []


def test_heal_attempt_optional_error():
    """HealAttempt.error defaults to None; applied_fixes defaults to empty list."""
    attempt = HealAttempt(
        attempt_num=1,
        prompt_tokens=100,
        elapsed_seconds=0.5,
        success=True,
    )
    assert attempt.error is None
    assert attempt.applied_fixes == []


def test_degrade_reason_cascade_value():
    """CASCADE reason is used by ProgressiveDegrader for downstream columns."""
    assert DegradeReason.CASCADE.value == "cascade"
