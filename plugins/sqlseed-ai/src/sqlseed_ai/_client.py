from __future__ import annotations

from typing import Any

import httpx
from openai import OpenAI
from sqlseed_ai.config import AIBackend, AIConfig

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


def get_openai_client(config: AIConfig | None = None) -> Any:
    if config is None:
        config = AIConfig.from_env()

    kwargs = config.to_openai_kwargs()
    # For local backends, use a shorter connection timeout but longer read timeout.
    # This prevents hanging on connection while allowing slow inference.
    if config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
        kwargs["timeout"] = httpx_timeout(config.resolve_timeout())
    logger.info("Creating OpenAI client", **{"backend": config.backend.value, "base_url": kwargs["base_url"]})
    return OpenAI(**kwargs)


def httpx_timeout(total: float) -> Any:
    """Build an httpx.Timeout with separate connect/read timeouts.

    For local inference: fast connect (5s) but long read (total) to
    accommodate slow GPU inference without hanging on dead connections.
    """
    return httpx.Timeout(connect=10.0, read=total, write=30.0, pool=10.0)
