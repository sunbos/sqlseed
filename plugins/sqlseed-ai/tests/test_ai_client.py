"""Tests for the OpenAI client wrapper in sqlseed_ai._client.

Covers httpx_timeout() default/override behavior and get_openai_client()
client construction and kwargs forwarding. The OpenAI constructor is mocked
so no network or real client is created.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

try:
    from sqlseed_ai._client import get_openai_client, httpx_timeout
    from sqlseed_ai.config import AIConfig
except ImportError:
    pytest.skip("sqlseed-ai not installed", allow_module_level=True)


class TestHttpxTimeout:
    def test_httpx_timeout_returns_object(self) -> None:
        """Verify httpx_timeout(total=60) returns an httpx.Timeout with correct read value."""
        timeout = httpx_timeout(total=60)
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read == pytest.approx(60.0)

    def test_httpx_timeout_defaults(self) -> None:
        """Verify httpx_timeout default values: connect=10, write=30, pool=10."""
        timeout = httpx_timeout(total=60)
        assert timeout.connect == pytest.approx(10.0)
        assert timeout.write == pytest.approx(30.0)
        assert timeout.pool == pytest.approx(10.0)


class TestGetOpenaiClient:
    def test_get_openai_client_creates_client(self) -> None:
        """Verify get_openai_client(config) creates and returns an OpenAI client."""
        config = AIConfig(api_key="sk-test", model="test-model", base_url="https://api.test.com/v1")
        with patch("sqlseed_ai._client.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            client = get_openai_client(config)
        mock_openai_cls.assert_called_once()
        assert client is mock_client

    def test_get_openai_client_passes_correct_kwargs(self) -> None:
        """Verify the OpenAI client receives api_key, base_url, and timeout kwargs."""
        config = AIConfig(api_key="sk-test", model="test-model", base_url="https://api.test.com/v1")
        with patch("sqlseed_ai._client.OpenAI") as mock_openai_cls:
            get_openai_client(config)
        call_kwargs: dict[str, Any] = mock_openai_cls.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-test"
        assert call_kwargs["base_url"] == "https://api.test.com/v1"
        assert isinstance(call_kwargs["timeout"], httpx.Timeout)
