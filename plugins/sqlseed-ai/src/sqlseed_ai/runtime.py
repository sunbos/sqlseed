"""Non-interactive AI factories shared by CLI and application entry points.

Factories raise ordinary exceptions; callers own presentation and job state.
The caller closes the client returned by ``build_llm_client``. Healers only
borrow their supplied client, snapshot and validator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlseed_ai.config import AIConfig

if TYPE_CHECKING:
    from sqlseed_ai.healer._client import LLMClient, OpenAICompatAdapter
    from sqlseed_ai.healer.orchestrator import HealOrchestrator
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


def build_ai_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 0.0,
    log_llm: bool = False,
) -> AIConfig:
    """Load environment defaults and apply the entry point's explicit options."""
    config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)
    config.timeout = timeout
    config.log_llm_interactions = log_llm
    return config


def build_llm_client(ai_config: AIConfig) -> OpenAICompatAdapter:
    """Create an owned heal client, retaining the existing auto-heal timeouts.

    Missing credentials raise ``ValueError``; missing SDK dependencies raise
    ``ImportError``. No console output or process exit belongs to this layer.
    """
    from openai import OpenAI
    from sqlseed_ai.healer._client import OpenAICompatAdapter

    if not (resolved_key := ai_config.resolve_api_key()):
        raise ValueError("AI API key not configured. Set SQLSEED_AI_API_KEY or OPENAI_API_KEY.")
    base = ai_config.resolve_base_url() or "https://api.openai.com/v1"
    raw_client = OpenAI(api_key=resolved_key, base_url=base, timeout=ai_config.timeout or None)
    return OpenAICompatAdapter(raw_client)


def build_heal_orchestrator(
    ai_config: AIConfig,
    client: LLMClient,
    snapshot: SchemaSnapshot,
    validator: FastValidator,
    *,
    schema_hash: str = "",
    max_retries: int = 3,
) -> HealOrchestrator:
    """Wire the existing four healing levels, borrowing all supplied resources."""
    from sqlseed_ai.healer.context_detector import ContextWindowDetector
    from sqlseed_ai.healer.degrader import ProgressiveDegrader
    from sqlseed_ai.healer.failure_classifier import FailureClassifier
    from sqlseed_ai.healer.level1_subgraph_healer import Level1SubgraphHealer
    from sqlseed_ai.healer.level2_column_healer import Level2ColumnHealer
    from sqlseed_ai.healer.level3_compact_healer import Level3CompactHealer
    from sqlseed_ai.healer.orchestrator import HealOrchestrator

    model = ai_config.model or ""
    return HealOrchestrator(
        snapshot=snapshot,
        context_detector=ContextWindowDetector(ai_config, model=model),
        failure_classifier=FailureClassifier(),
        level1=Level1SubgraphHealer(client=client, model=model),
        level2=Level2ColumnHealer(client=client, model=model),
        level3=Level3CompactHealer(client=client, model=model),
        degrader=ProgressiveDegrader(snapshot=snapshot),
        validator=validator,
        schema_hash=schema_hash,
        max_rounds=max_retries,
    )
