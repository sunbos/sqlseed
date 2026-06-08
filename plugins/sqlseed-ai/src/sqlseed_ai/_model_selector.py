from __future__ import annotations

from sqlseed_ai.config import AIBackend, GemmaModel

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

# ── Gemma 4 model selection priority ────────────────────────────────
# Ordered by capability: 26B MoE (best balance) > 31B Dense > 4B > 2B
_GEMMA_MODEL_PRIORITY: list[GemmaModel] = [
    GemmaModel.GEMMA_4_26B,
    GemmaModel.GEMMA_4_31B,
    GemmaModel.GEMMA_4_4B,
    GemmaModel.GEMMA_4_2B,
]

# Map backend to preferred model size
_BACKEND_DEFAULT_MODEL: dict[AIBackend, GemmaModel] = {
    AIBackend.GOOGLE_AI_STUDIO: GemmaModel.GEMMA_4_26B,
    AIBackend.LM_STUDIO: GemmaModel.GEMMA_4_4B,  # local inference, prefer smaller
    AIBackend.OLLAMA: GemmaModel.GEMMA_4_4B,  # smaller for local inference
    AIBackend.OPENAI_COMPAT: GemmaModel.GEMMA_4_26B,
}


def select_gemma_model(
    backend: AIBackend = AIBackend.GOOGLE_AI_STUDIO,
    prefer_small: bool = False,
) -> str:
    """Select the best Gemma 4 model for the given backend.

    Args:
        backend: The LLM backend provider.
        prefer_small: If True, prefer smaller models (useful for Edge/local).

    Returns:
        The model identifier string.
    """
    if prefer_small or backend in (AIBackend.OLLAMA, AIBackend.LM_STUDIO):
        # For local inference (Ollama/LM Studio), prefer smaller models
        model = GemmaModel.GEMMA_4_4B
        logger.info("Selected compact Gemma 4 model for local inference", model=model.value)
        return model.value

    model = _BACKEND_DEFAULT_MODEL.get(backend, GemmaModel.GEMMA_4_26B)
    logger.info("Selected Gemma 4 model", model=model.value, backend=backend.value)
    return model.value


def select_next_gemma_model(failed_model: str) -> str | None:
    """Select the next smaller Gemma 4 model as fallback.

    Args:
        failed_model: The model that failed.

    Returns:
        The next model in the priority list, or None if all exhausted.
    """
    for i, m in enumerate(_GEMMA_MODEL_PRIORITY):
        if m.value == failed_model and i + 1 < len(_GEMMA_MODEL_PRIORITY):
            next_model = _GEMMA_MODEL_PRIORITY[i + 1]
            logger.info(
                "Falling back to smaller Gemma 4 model",
                from_model=failed_model,
                to_model=next_model.value,
            )
            return next_model.value

    logger.warning("No more Gemma 4 models available for fallback", failed_model=failed_model)
    return None


def get_available_gemma_models() -> list[dict[str, str]]:
    """Return list of available Gemma 4 models with display info."""
    return [{"id": m.value, "display_name": m.display_name} for m in _GEMMA_MODEL_PRIORITY]


# ── Legacy compatibility ─────────────────────────────────────────────
# These functions maintain backward compatibility with code that
# referenced the old OpenRouter-based model selector.


def select_best_free_model() -> str:
    """Legacy compat: returns the default Gemma 4 model."""
    return select_gemma_model()


def select_next_free_model(failed_model: str) -> str | None:
    """Legacy compat: returns the next Gemma 4 model as fallback."""
    return select_next_gemma_model(failed_model)


def clear_cache() -> None:
    """Legacy compat: no-op, Gemma models don't need cache."""
