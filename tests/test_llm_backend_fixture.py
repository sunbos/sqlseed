"""Backend discovery keeps service model IDs intact and honors family priority."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest


def _fixtures() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sqlseed_root_fixture_regression", Path(__file__).parents[1] / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("models", "expected"),
    [
        (["gemma4:31b-cloud"], "gemma4:31b-cloud"),
        (["gemma4:26b-a4b-q4_K_M"], "gemma4:26b-a4b-q4_K_M"),
        (["gemma4:31b-cloud", "gemma4:31b"], "gemma4:31b"),
        (["gemma4:31b", "gemma4:26b-cloud"], "gemma4:26b-cloud"),
        (["gemma4:12b", "gemma4:e4b-q8_0"], "gemma4:e4b-q8_0"),
        (["gemma4:26b-q8_0", "gemma4:26b-q4_K_M"], "gemma4:26b-q4_K_M"),
        (["gemma4:26b-q4_K_M", "gemma4:26b-q8_0"], "gemma4:26b-q4_K_M"),
        (["gemma4:31billion", "gemma4:e4b"], "gemma4:e4b"),
        ([None, 31, "gemma4:31b-cloud"], "gemma4:31b-cloud"),
    ],
)
def test_ollama_fixture_selects_an_actual_model_id(models: Any, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = _fixtures()
    monkeypatch.setattr(
        fixtures.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps({"models": [{"name": name} for name in models]}).encode()),
    )
    result = fixtures.available_llm_backend.__wrapped__()
    assert result == {"backend": "ollama", "model": expected}
    assert result["model"] in models


@pytest.mark.parametrize("name", ["gemma4:31billion", "gemma4:26b2", "other/gemma4:26b", "gemma3:26b"])
def test_ollama_fixture_does_not_match_unrelated_prefixes(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = _fixtures()
    monkeypatch.setattr(
        fixtures.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps({"models": [{"name": name}]}).encode()),
    )
    with pytest.raises(pytest.fail.Exception, match="no Gemma 4 model"):
        fixtures.available_llm_backend.__wrapped__()


def test_backend_fallback_keeps_existing_lm_studio_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = _fixtures()

    def respond(url: str, **kwargs: Any) -> Any:
        if "11434" in url:
            raise OSError("Ollama unavailable in this fixture regression")
        return io.BytesIO(json.dumps({"data": [{"id": "google/gemma-4-e4b"}, {"id": "google/gemma-4-31b"}]}).encode())

    monkeypatch.setattr(fixtures.urllib.request, "urlopen", respond)
    assert fixtures.available_llm_backend.__wrapped__() == {"backend": "lm_studio", "model": "google/gemma-4-31b"}
