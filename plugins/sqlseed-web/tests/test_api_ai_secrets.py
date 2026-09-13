"""Legacy AI configuration remains compatible without returning stored secrets."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.assertions import assert_empty

from sqlseed_web import api
from sqlseed_web.state import UIState


def test_legacy_settings_redact_secret_and_preserve_blank_password_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    for key in ("SQLSEED_AI_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        payload: dict[str, Any] = {
            "backend": "openai_compat",
            "model": "demo",
            "base_url": "https://example.test/v1",
            "api_key": "secret-value-for-test",
        }
        response = client.post("/api/ai/config", json=payload)
        assert response.status_code == 200
        assert "secret-value-for-test" not in response.text
        assert "api_key" not in response.json()["override"]
        response = client.get("/api/ai/config")
        assert response.json()["effective"]["api_key_present"] is True
        assert "secret-value-for-test" not in response.text
        # The retained legacy form intentionally sends an empty password after
        # loading settings. Editing another field must not discard its key.
        response = client.post("/api/ai/config", json={**payload, "model": "next-model", "api_key": None})
        assert response.json()["effective"]["api_key_present"] is True
        assert registry.get_ai_override()["api_key"] == "secret-value-for-test"
        assert "secret-value-for-test" not in response.text
        client.post("/api/ai/config", json={})
        assert_empty(registry.get_ai_override(), dict)
