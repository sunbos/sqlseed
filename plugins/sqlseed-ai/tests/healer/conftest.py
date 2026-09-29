"""Shared fixtures for healer tests — LLM-dependent and pure-logic.

Spec reference: Section 6.4 — LLM-dependent tests controlled by the
``llm_available`` fixture checking ``http://localhost:1234/v1/models``.
The ``llm_client`` fixture auto-skips tests when LM Studio is not
available or does not advertise the requested model, satisfying Spec
6.1 ("no mock LLM — use real environment or skip").
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", name="llm_available")
def fixture_llm_available(llm_model: str) -> bool:
    """Require an online LM Studio advertising the requested model."""
    try:
        import httpx
    except ModuleNotFoundError as exc:
        if exc.name != "httpx":
            raise
        return False

    try:
        resp = httpx.get("http://localhost:1234/v1/models", timeout=2)
    except httpx.RequestError:
        return False
    if resp.status_code != 200:
        return False
    payload = resp.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("LM Studio model list must contain a data array")
    models = payload["data"]
    if any(not isinstance(model, dict) or not isinstance(model.get("id"), str) for model in models):
        raise ValueError("LM Studio model entries must contain string ids")
    return any(model["id"] == llm_model for model in models)


@pytest.fixture(scope="session", name="llm_model")
def fixture_llm_model() -> str:
    """Model name for LM Studio (env-overridable)."""
    return os.environ.get("SQLSEED_TEST_LLM_MODEL", "google/gemma-4-e2b")


@pytest.fixture(scope="session")
def llm_client(llm_available: bool, llm_model: str):
    """Build a real LLM client for LM Studio.

    Skips if the service or requested model is unavailable (Spec 6.1 +
    6.4). Listing a model is a prerequisite, not proof of inference;
    completion errors still fail the real tests.
    """
    if not llm_available:
        pytest.skip(f"LM Studio unavailable or model {llm_model!r} not listed at http://localhost:1234/v1/models")
    from openai import OpenAI
    from sqlseed_ai.healer._client import OpenAICompatAdapter

    raw = OpenAI(
        api_key="lm-studio",
        base_url="http://localhost:1234/v1",
        timeout=60,
    )
    return OpenAICompatAdapter(raw)
