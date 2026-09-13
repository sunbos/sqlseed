"""Real-LLM tests for Level1SubgraphHealer (Spec 6.4 + 6.12).

Skipped when LM Studio is not available at ``http://localhost:1234``.
No mocks — exercises the real LLM call path per Spec 6.1.
"""

from __future__ import annotations

from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
from sqlseed_ai.healer.models import SubgraphTask

from .scenario_helpers import product_price_config, product_price_violation


def _make_task() -> SubgraphTask:
    return SubgraphTask(task_id="t1", tables=["products"], is_scc=False)


def test_level1_heal_real(llm_client, llm_model):
    """Level1SubgraphHealer.heal() returns a structured Level1Result.

    LLM output is non-deterministic — assert on structure, not content.
    """
    healer = Level1SubgraphHealer(client=llm_client, model=llm_model)
    result = healer.heal(_make_task(), [product_price_violation()], product_price_config())

    assert isinstance(result.success, bool)
    assert result.elapsed_seconds >= 0
    assert result.prompt_tokens > 0
    if result.success:
        assert isinstance(result.config_patch, dict)
        assert "tables" in result.config_patch
    else:
        # Failure must carry an error or a (possibly empty) raw response.
        assert result.error is not None or result.raw_response is not None


def test_level1_build_prompt_no_llm():
    """build_prompt() produces non-empty prompts (pure logic, no LLM needed).

    Included here per Spec 6.12 file layout — verifies prompt construction
    without requiring LM Studio.
    """
    healer = Level1SubgraphHealer(client=None, model="any")  # type: ignore[arg-type]
    prompt = healer.build_prompt(_make_task(), [product_price_violation()], product_price_config())
    assert "products" in prompt.user_prompt
    assert "price" in prompt.user_prompt
    assert prompt.estimated_tokens > 0
