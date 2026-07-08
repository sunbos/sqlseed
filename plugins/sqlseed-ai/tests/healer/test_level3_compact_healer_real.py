"""Real-LLM tests for Level3CompactHealer (Spec 6.4 + 6.12).

Skipped when LM Studio is not available at ``http://localhost:1234``.
Exercises both ``compact`` and ``ultra_compact`` modes with real LLM
calls per Spec 6.1 (no mocks).
"""

from __future__ import annotations

from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
from sqlseed_ai.healer.models import SubgraphTask
from sqlseed_ai.validator.models import ConstraintType, ViolationReport


def _make_task() -> SubgraphTask:
    return SubgraphTask(task_id="t1", tables=["products"])


def _make_violation() -> ViolationReport:
    return ViolationReport(
        table="products",
        columns=["price"],
        constraint_type=ConstraintType.CHECK,
        severity="semantic_error",
        message="CHECK constraint failed: price > 0",
    )


def _make_config() -> dict:
    return {
        "tables": [
            {
                "name": "products",
                "columns": [
                    {
                        "name": "price",
                        "generator": "random_float",
                        "params": {"min_value": -10, "max_value": 100},
                    },
                ],
            }
        ]
    }


def test_level3_compact_real(llm_client, llm_model):
    """Level3CompactHealer in compact mode returns a structured Level3Result."""
    healer = Level3CompactHealer(client=llm_client, model=llm_model)
    result = healer.heal_compact(
        _make_task(), [_make_violation()], _make_config(), mode="compact"
    )

    assert result.mode == "compact"
    assert result.success in (True, False)
    assert result.elapsed_seconds >= 0
    assert result.prompt_tokens > 0
    if result.success:
        assert isinstance(result.config_patch, dict)
        assert "tables" in result.config_patch


def test_level3_ultra_compact_real(llm_client, llm_model):
    """Level3CompactHealer in ultra_compact mode returns a structured Level3Result."""
    healer = Level3CompactHealer(client=llm_client, model=llm_model)
    result = healer.heal_compact(
        _make_task(), [_make_violation()], _make_config(), mode="ultra_compact"
    )

    assert result.mode == "ultra_compact"
    assert result.success in (True, False)
    assert result.elapsed_seconds >= 0
    assert result.prompt_tokens > 0
