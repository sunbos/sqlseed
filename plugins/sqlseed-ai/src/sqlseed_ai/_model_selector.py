from __future__ import annotations

import re

from sqlseed_ai.config import AIBackend, GemmaModel

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_model_id(model_id: str) -> str:
    """Normalize a model ID for comparison.

    Strips platform-specific formatting so that model IDs from
    different sources can be compared:

      "google/gemma-4-e4b"    → "gemma-4-e4b"   (LM Studio)
      "gemma-4-e4b-it"        → "gemma-4-e4b"   (Google AI Studio)
      "gemma4:e4b"            → "gemma-4-e4b"   (Ollama)
      "google/gemma-4-e4b-it" → "gemma-4-e4b"   (OpenRouter)
      "google/gemma-4-26b-a4b-it:free" → "gemma-4-26b-a4b" (OpenRouter free)
    """
    result = model_id.lower().strip()

    # Strip OpenRouter free tier suffix (e.g., ":free")
    result = re.sub(r":free$", "", result)

    # Convert Ollama format: "gemma4:xxb" → "gemma-4-xxb"
    # e.g., "gemma4:e4b" → "gemma-4-e4b", "gemma4:26b" → "gemma-4-26b"
    ollama_match = re.match(r"^gemma4:(.+)$", result)
    if ollama_match:
        result = f"gemma-4-{ollama_match.group(1)}"

    # Strip provider prefix (e.g., "google/" from LM Studio/OpenRouter IDs)
    result = re.sub(r"^[a-z]+/", "", result)

    # Strip "-it" suffix (instruction-tuned variant indicator)
    return re.sub(r"-it$", "", result)


# ── Gemma 4 model selection priority ────────────────────────────────
# Ordered by capability: 26B A4B MoE (best balance) > 31B Dense > 12B Unified > E4B > E2B
_GEMMA_MODEL_PRIORITY: tuple[GemmaModel, ...] = (
    GemmaModel.GEMMA_4_26B_A4B,
    GemmaModel.GEMMA_4_31B,
    GemmaModel.GEMMA_4_12B,
    GemmaModel.GEMMA_4_E4B,
    GemmaModel.GEMMA_4_E2B,
)

# Map backend to preferred model size
_BACKEND_DEFAULT_MODEL: dict[AIBackend, GemmaModel] = {
    AIBackend.GOOGLE_AI_STUDIO: GemmaModel.GEMMA_4_26B_A4B,
    AIBackend.LM_STUDIO: GemmaModel.GEMMA_4_E4B,  # local inference, prefer smaller
    AIBackend.OLLAMA: GemmaModel.GEMMA_4_E4B,  # smaller for local inference
    AIBackend.OPENAI_COMPAT: GemmaModel.GEMMA_4_26B_A4B,
}


def select_gemma_model(
    backend: AIBackend = AIBackend.GOOGLE_AI_STUDIO,
    prefer_small: bool = False,
) -> str:
    """Select the best Gemma 4 model for the given backend.

    Returns the platform-specific model ID for the selected backend.

    Args:
        backend: The LLM backend provider.
        prefer_small: If True, prefer smaller models (useful for Edge/local).

    Returns:
        The model identifier string in the backend's format.
    """
    if prefer_small or backend in (AIBackend.OLLAMA, AIBackend.LM_STUDIO):
        # For local inference (Ollama/LM Studio), prefer smaller models
        model = GemmaModel.GEMMA_4_E4B
        logger.info("Selected compact Gemma 4 model for local inference", model=model.to_backend_id(backend))
        return model.to_backend_id(backend)

    model = _BACKEND_DEFAULT_MODEL.get(backend, GemmaModel.GEMMA_4_26B_A4B)
    logger.info("Selected Gemma 4 model", model=model.to_backend_id(backend), backend=backend.value)
    return model.to_backend_id(backend)


def select_next_gemma_model(failed_model: str, backend: AIBackend | None = None) -> str | None:
    """Select the next smaller Gemma 4 model as fallback.

    Skips models that are not available on the given backend
    (e.g., 12B is local-only and not available on Google AI Studio/OpenRouter).

    Args:
        failed_model: The model that failed.
        backend: The current backend (used to skip unavailable models).
            If None, all models are considered available.

    Returns:
        The next model in the priority list (in backend-specific format), or None if all exhausted.
    """
    failed_norm = _normalize_model_id(failed_model)
    for i, m in enumerate(_GEMMA_MODEL_PRIORITY):
        if _normalize_model_id(m.value) == failed_norm:
            # Walk down the priority list to find the next available model
            for j in range(i + 1, len(_GEMMA_MODEL_PRIORITY)):
                next_model = _GEMMA_MODEL_PRIORITY[j]
                # Skip local-only models for cloud backends
                if next_model.is_local_only and backend not in (
                    AIBackend.LM_STUDIO,
                    AIBackend.OLLAMA,
                    None,  # None means "don't filter"
                ):
                    continue
                logger.info(
                    "Falling back to smaller Gemma 4 model",
                    from_model=failed_model,
                    to_model=next_model.to_backend_id(backend) if backend else next_model.value,
                )
                return next_model.to_backend_id(backend) if backend else next_model.value

    logger.warning("No more Gemma 4 models available for fallback", failed_model=failed_model)
    return None


def get_available_gemma_models() -> list[dict[str, str]]:
    """Return list of available Gemma 4 models with display info."""
    return [{"id": m.value, "display_name": m.display_name} for m in _GEMMA_MODEL_PRIORITY]
