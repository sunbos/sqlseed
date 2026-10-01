"""OpenAI-compatible client factory for the sqlseed-ai plugin.

Provides a single helper, :func:`get_openai_client`, that builds an
:class:`openai.OpenAI` client configured from :class:`AIConfig` with
unified httpx timeouts suitable for both cloud and local (GPU) inference.
"""

from __future__ import annotations

from ipaddress import ip_address
from typing import TYPE_CHECKING

import httpx
from openai import APIConnectionError, APIError, APITimeoutError
from sqlseed_ai.config import AIConfig

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from openai import OpenAI

logger = get_logger(__name__)

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "build_openai_client",
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
    return build_openai_client(**kwargs)


def build_openai_client(*, api_key: str, base_url: str, timeout: float | httpx.Timeout | None) -> OpenAI:
    """Create a client with direct loopback routing and SDK transport defaults.

    Exact loopback hosts bypass environment proxies. TLS certificate settings,
    remote proxy routes, timeouts, redirects, and pool limits remain unchanged.
    The returned SDK client owns its optional HTTP client.
    """
    from openai import DefaultHttpxClient, OpenAI, Timeout

    resolved_timeout = Timeout(**timeout.as_dict()) if isinstance(timeout, httpx.Timeout) else timeout
    host = httpx.URL(base_url).host
    if host != "localhost":
        try:
            is_loopback = ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
    else:
        is_loopback = True
    if not is_loopback:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=resolved_timeout)

    authority = f"[{host}]" if ":" in host else host
    transport = DefaultHttpxClient(mounts={f"all://{authority}": None})
    try:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=resolved_timeout, http_client=transport)
    except BaseException:
        transport.close()
        raise


def httpx_timeout(total: float) -> httpx.Timeout:
    """Build an httpx.Timeout with separate connect/read timeouts.

    For local inference: fast connect (10s) but long read (total) to
    accommodate slow GPU inference without hanging on dead connections.
    """
    return httpx.Timeout(connect=10.0, read=total, write=30.0, pool=10.0)
