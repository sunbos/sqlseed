"""Real LLM clients for lifecycle tests that must never make network requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from openai import OpenAI


def no_network_openai_client() -> tuple[httpx.Client, OpenAI]:
    """Return a real transport and SDK client whose closure stays with the caller."""
    from openai import OpenAI

    def no_network(_request: httpx.Request) -> httpx.Response:
        pytest.fail("unexpected LLM request")

    transport_client = httpx.Client(transport=httpx.MockTransport(no_network), trust_env=False)
    sdk_client = OpenAI(api_key="test-key", base_url="https://example.invalid/v1", http_client=transport_client)
    return transport_client, sdk_client
