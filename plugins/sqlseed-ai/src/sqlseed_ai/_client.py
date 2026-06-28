"""OpenAI-compatible client factory for the sqlseed-ai plugin.

Provides a single helper, :func:`get_openai_client`, that builds an
:class:`openai.OpenAI` client configured from :class:`AIConfig` with
unified httpx timeouts suitable for both cloud and local (GPU) inference.
"""

from __future__ import annotations

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI
from sqlseed_ai.config import AIConfig

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "get_openai_client",
    "httpx_timeout",
]


def get_openai_client(config: AIConfig | None = None) -> OpenAI:
    """Build an OpenAI-compatible client from the given (or env) config.

    All backends share the same httpx timeout profile (see
    :func:`httpx_timeout`) so that slow local GPU inference does not trip
    fast connect timeouts.

    Args:
        config: Optional :class:`AIConfig`. When None, the config is
            loaded from environment variables via :meth:`AIConfig.from_env`.

    Returns:
        A configured :class:`openai.OpenAI` client instance.
    """
    if config is None:
        config = AIConfig.from_env()

    kwargs = config.to_openai_kwargs()
    # Unified httpx timeout configuration for all backends:
    # - connect=10s: quickly detect dead connections
    # - read=total: allow slow inference (local GPU)
    # - write=30s: timeout for uploading the prompt
    # - pool=10s: connection-pool acquisition timeout
    kwargs["timeout"] = httpx_timeout(config.resolve_timeout())
    logger.info("Creating OpenAI client", **{"backend": config.backend.value, "base_url": kwargs["base_url"]})
    return OpenAI(**kwargs)


def httpx_timeout(total: float) -> httpx.Timeout:
    """Build an httpx.Timeout with separate connect/read timeouts.

    For local inference: fast connect (10s) but long read (total) to
    accommodate slow GPU inference without hanging on dead connections.
    """
    return httpx.Timeout(connect=10.0, read=total, write=30.0, pool=10.0)
