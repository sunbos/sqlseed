from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

PREFERRED_FREE_MODELS: list[str] = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "tencent/hy3-preview:free",
    "inclusionai/ling-2.6-1t:free",
    "inclusionai/ling-2.6-flash:free",
    "z-ai/glm-4.5-air:free",
    "minimax/minimax-m2.5:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-20b:free",
    "google/gemma-4-26b-a4b-it:free",
]

_CACHE: dict[str, Any] = {
    "model": None,
    "expires_at": 0.0,
}

_CACHE_TTL = 3600

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def _fetch_available_free_models() -> set[str]:
    try:
        req = urllib.request.Request(_OPENROUTER_MODELS_URL)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to fetch OpenRouter models, using fallback", error=str(e))
        return set()

    available: set[str] = set()
    for model in data.get("data", []):
        pricing = model.get("pricing", {})
        if pricing.get("prompt") != "0" or pricing.get("completion") != "0":
            continue

        arch = model.get("architecture", {})
        if "text" not in arch.get("input_modalities", []):
            continue
        if "text" not in arch.get("output_modalities", []):
            continue

        supported = model.get("supported_parameters", [])
        if "response_format" not in supported:
            continue

        available.add(model["id"])

    return available


def _update_cache(model: str) -> None:
    _CACHE["model"] = model
    _CACHE["expires_at"] = time.time() + _CACHE_TTL


def select_best_free_model() -> str:
    if _CACHE["model"] is not None and time.time() < _CACHE["expires_at"]:
        return _CACHE["model"]

    available = _fetch_available_free_models()

    if available:
        for preferred in PREFERRED_FREE_MODELS:
            if preferred in available:
                _update_cache(preferred)
                logger.info(
                    "Auto-selected free model from OpenRouter",
                    model=preferred,
                    available_count=len(available),
                )
                return preferred

        logger.warning(
            "No preferred free model found in available models, using fallback",
            available_count=len(available),
        )

    fallback = PREFERRED_FREE_MODELS[0]
    _update_cache(fallback)
    logger.info("Using fallback free model", model=fallback)
    return fallback


def select_next_free_model(failed_model: str) -> str | None:
    idx = -1
    for i, m in enumerate(PREFERRED_FREE_MODELS):
        if m == failed_model:
            idx = i
            break

    if idx == -1 or idx + 1 >= len(PREFERRED_FREE_MODELS):
        return None

    next_model = PREFERRED_FREE_MODELS[idx + 1]
    _update_cache(next_model)
    logger.info("Falling back to next free model", from_model=failed_model, to_model=next_model)
    return next_model


def clear_cache() -> None:
    _CACHE["model"] = None
    _CACHE["expires_at"] = 0.0
