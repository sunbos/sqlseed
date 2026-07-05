"""Tests for healer.llm_healer module."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.healer.llm_healer import LLMHealer
from sqlseed_ai.healer.models import SubgraphTask
from sqlseed_ai.validator.models import ConstraintType, ViolationReport


def _violation(col: str, kind: ConstraintType = ConstraintType.CHECK) -> ViolationReport:
    return ViolationReport(
        table="users",
        columns=[col],
        constraint_type=kind,
        severity="crash",
        message=f"CHECK constraint failed on {col}",
    )


def test_build_prompt_includes_failure_reasons():
    healer = LLMHealer(client=MagicMock(), model="gemma-4-e4b-it")
    task = SubgraphTask(task_id="t1", tables=["users"])
    violations = [_violation("email"), _violation("age")]
    prompt = healer.build_prompt(task, violations, parent_config={"tables": []})
    assert "users" in prompt.user_prompt
    assert "email" in prompt.user_prompt
    assert "age" in prompt.user_prompt
    assert "CHECK" in prompt.user_prompt


def test_build_prompt_respects_token_budget():
    """Subgraph prompt must stay under 2K tokens (Section 6.4)."""
    healer = LLMHealer(client=MagicMock(), model="gemma-4-e4b-it", max_prompt_tokens=2000)
    task = SubgraphTask(task_id="t1", tables=["users"])
    violations = [_violation(f"col_{i}") for i in range(50)]
    prompt = healer.build_prompt(task, violations, parent_config={"tables": []})
    # Rough estimate: 4 chars per token
    assert len(prompt.user_prompt) < 2000 * 4


def test_heal_success_returns_config_patch():
    """A well-formed LLM response produces a config patch dict."""
    fake_client = MagicMock()
    fake_client.chat_completions_create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content='{"tables": [{"name": "users", "columns": [{"name": "email", "generator": "email"}]}]}'
                )
            )
        ]
    )
    healer = LLMHealer(client=fake_client, model="gemma-4-e4b-it")
    task = SubgraphTask(task_id="t1", tables=["users"])
    violations = [_violation("email")]
    result = healer.heal(task, violations, parent_config={"tables": []})
    assert result.success is True
    assert "tables" in result.config_patch
    assert result.error is None


def test_heal_failure_on_malformed_json():
    """Malformed JSON response is reported as failure, not crash."""
    fake_client = MagicMock()
    fake_client.chat_completions_create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="not valid json {{{"))]
    )
    healer = LLMHealer(client=fake_client, model="gemma-4-e4b-it")
    task = SubgraphTask(task_id="t1", tables=["users"])
    violations = [_violation("email")]
    result = healer.heal(task, violations, parent_config={"tables": []})
    assert result.success is False
    assert "json" in (result.error or "").lower()


def test_heal_failure_propagates_api_error():
    """API errors (timeout, connection) are wrapped as failure, not raised."""
    fake_client = MagicMock()
    fake_client.chat_completions_create.side_effect = RuntimeError("connection refused")
    healer = LLMHealer(client=fake_client, model="gemma-4-e4b-it")
    task = SubgraphTask(task_id="t1", tables=["users"])
    violations = [_violation("email")]
    result = healer.heal(task, violations, parent_config={"tables": []})
    assert result.success is False
    assert "connection" in (result.error or "").lower()
