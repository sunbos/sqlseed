from __future__ import annotations

from typing import Any

from openai import OpenAI
from sqlseed_ai.config import AIConfig

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


def get_openai_client(config: Any | None = None) -> Any:
    if config is None:
        config = AIConfig.from_env()

    # Use the new to_openai_kwargs() for unified resolution
    if isinstance(config, AIConfig):
        kwargs = config.to_openai_kwargs()
        logger.info("Creating OpenAI client", **{"backend": config.backend.value, "base_url": kwargs["base_url"]})
        return OpenAI(**kwargs)

    # Legacy fallback for non-AIConfig objects
    api_key = config.api_key if hasattr(config, "api_key") else None
    base_url = config.base_url if hasattr(config, "base_url") else None
    timeout = config.timeout if hasattr(config, "timeout") else 60.0

    if not api_key:
        raise ValueError(
            "AI API key not configured. "
            "Set GOOGLE_API_KEY, SQLSEED_AI_API_KEY, or OPENAI_API_KEY environment variable. "
            "For Ollama, set SQLSEED_AI_BACKEND=ollama."
        )

    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
