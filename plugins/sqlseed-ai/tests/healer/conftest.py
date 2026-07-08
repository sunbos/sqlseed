"""Shared fixtures for healer tests — LLM-dependent and pure-logic.

Spec reference: Section 6.4 — LLM-dependent tests controlled by the
``llm_available`` fixture checking ``http://localhost:1234/v1/models``.
The ``llm_client`` fixture auto-skips tests when LM Studio is not
available, satisfying Spec 6.1 ("no mock LLM — use real environment
or skip").
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def llm_available() -> bool:
    """Check if local LM Studio is available (Spec 6.4)."""
    try:
        import httpx

        resp = httpx.get("http://localhost:1234/v1/models", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def llm_model() -> str:
    """Model name for LM Studio (env-overridable)."""
    return os.environ.get("SQLSEED_TEST_LLM_MODEL", "google/gemma-4-e2b")


@pytest.fixture(scope="session")
def llm_client(llm_available: bool):
    """Build a real LLM client for LM Studio.

    Skips the test if LM Studio is not available (Spec 6.1 + 6.4:
    no mock LLM — use real environment or skip).
    """
    if not llm_available:
        pytest.skip("LM Studio not available at http://localhost:1234")
    from openai import OpenAI
    from sqlseed_ai.healer._client import OpenAICompatAdapter

    raw = OpenAI(
        api_key="lm-studio",
        base_url="http://localhost:1234/v1",
        timeout=60,
    )
    return OpenAICompatAdapter(raw)
