from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

_CACHE: dict[str, Any] = {
    "model": None,
    "expires_at": 0.0,
    "available_models": [],
}

_CACHE_TTL = 3600

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def _fetch_available_free_models() -> list[str]:
    try:
        req = urllib.request.Request(_OPENROUTER_MODELS_URL)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to fetch OpenRouter models, using fallback", error=str(e))
        return []

    models_info = []
    for model in data.get("data", []):
        pricing = model.get("pricing", {})
        if pricing.get("prompt") != "0" or pricing.get("completion") != "0":
            continue

        if model.get("expiration_date") is not None:
            continue

        arch = model.get("architecture", {})
        if "text" not in arch.get("input_modalities", []):
            continue
        if "text" not in arch.get("output_modalities", []):
            continue

        supported = model.get("supported_parameters", [])
        if "response_format" not in supported:
            continue

        models_info.append({"id": model["id"], "created": model.get("created", 0)})

    models_info.sort(key=lambda x: x["created"], reverse=True)
    return [m["id"] for m in models_info]


def _update_cache(model: str) -> None:
    _CACHE["model"] = model
    _CACHE["expires_at"] = time.time() + _CACHE_TTL


def select_best_free_model() -> str:
    if _CACHE["model"] is not None and time.time() < _CACHE["expires_at"]:
        return str(_CACHE["model"])

    available = _fetch_available_free_models()
    _CACHE["available_models"] = available

    if available:
        best = available[0]
        _update_cache(best)
        logger.info(
            "Auto-selected newest free model from OpenRouter",
            model=best,
            available_count=len(available),
        )
        return best

    fallback = "openrouter/free"
    logger.warning("No free models without expiration could be fetched, using hardcoded fallback", model=fallback)
    _update_cache(fallback)
    logger.info("Using fallback free model", model=fallback)
    return fallback


def select_next_free_model(failed_model: str) -> str | None:
    available: list[str] = _CACHE.get("available_models", [])
    if not available:
        available = _fetch_available_free_models()
        _CACHE["available_models"] = available

    idx = -1
    for i, m in enumerate(available):
        if m == failed_model:
            idx = i
            break

    if idx == -1 or idx + 1 >= len(available):
        return None

    next_model = available[idx + 1]
    _update_cache(next_model)
    logger.info("Falling back to next free model", from_model=failed_model, to_model=next_model)
    return next_model


def clear_cache() -> None:
    _CACHE["model"] = None
    _CACHE["expires_at"] = 0.0
    _CACHE["available_models"] = []
