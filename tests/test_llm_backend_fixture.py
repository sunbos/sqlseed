"""Backend discovery keeps service model IDs intact and honors family priority."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest


def _fixtures() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sqlseed_root_fixture_regression", Path(__file__).parents[1] / "conftest.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ollama_fixtures(monkeypatch: pytest.MonkeyPatch, models: list[Any]) -> Any:
    """Supply the discovery response while exercising the real selector."""
    fixtures = _fixtures()
    monkeypatch.setattr(
        fixtures.urllib.request.OpenerDirector,
        "open",
        lambda *args, **kwargs: io.BytesIO(json.dumps({"models": [{"name": name} for name in models]}).encode()),
    )
    return fixtures


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
        (["gemma4:e2b"], "gemma4:e2b"),
    ],
)
def test_ollama_fixture_selects_an_actual_model_id(models: Any, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep advertised model tags intact while applying the supported-family preference order."""
    fixtures = _ollama_fixtures(monkeypatch, models)
    result = fixtures._detect_llm_backend()
    assert result == {"backend": "ollama", "model": expected}
    assert result["model"] in models


@pytest.mark.parametrize("name", ["gemma4:31billion", "gemma4:26b2", "other/gemma4:26b", "gemma3:26b"])
def test_ollama_fixture_does_not_match_unrelated_prefixes(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject similar prefixes that do not identify a supported Gemma 4 model."""
    fixtures = _ollama_fixtures(monkeypatch, [name])
    with pytest.raises(pytest.fail.Exception, match="no Gemma 4 model"):
        fixtures._detect_llm_backend()


def test_backend_fallback_keeps_existing_lm_studio_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep LM Studio model preference ordering when Ollama is unreachable."""
    fixtures = _fixtures()

    def respond(_opener: object, url: str, **kwargs: Any) -> Any:
        """Make only Ollama unreachable and advertise two valid LM Studio candidates."""
        if "11434" in url:
            raise OSError("Ollama unavailable in this fixture regression")
        return io.BytesIO(json.dumps({"data": [{"id": "google/gemma-4-e4b"}, {"id": "google/gemma-4-31b"}]}).encode())

    monkeypatch.setattr(fixtures.urllib.request.OpenerDirector, "open", respond)
    assert fixtures._detect_llm_backend() == {"backend": "lm_studio", "model": "google/gemma-4-31b"}


@pytest.mark.parametrize("service", ["ollama", "lm_studio"])
@pytest.mark.parametrize("payload", [None, [], {}, {"models": None, "data": None}, {"models": [None], "data": [None]}])
def test_invalid_model_lists_fail_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch, service: str, payload: object
) -> None:
    """Fail discovery on malformed reachable-service payloads instead of falling through."""
    fixtures = _fixtures()

    def respond(_opener: object, url: str, **kwargs: Any) -> Any:
        """Route discovery to the chosen service before returning its malformed model list."""
        if service == "lm_studio" and "11434" in url:
            raise OSError("Ollama unavailable")
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(fixtures.urllib.request.OpenerDirector, "open", respond)
    with pytest.raises(ValueError, match="LLM model"):
        fixtures._detect_llm_backend()


@pytest.mark.parametrize("model_id", [None, 31])
def test_invalid_model_ids_fail_setup(monkeypatch: pytest.MonkeyPatch, model_id: object) -> None:
    """Reject non-string model IDs even when another advertised model would be usable."""
    fixtures = _ollama_fixtures(monkeypatch, [model_id, "gemma4:31b-cloud"])
    with pytest.raises(ValueError, match="string name"):
        fixtures._detect_llm_backend()


def test_invalid_json_fails_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve JSON decoding failures from the service availability probe."""
    fixtures = _fixtures()
    monkeypatch.setattr(fixtures.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: io.BytesIO(b"not json"))
    with pytest.raises(json.JSONDecodeError):
        fixtures._detect_llm_backend()


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_http_errors_fail_instead_of_trying_another_backend(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """Do not hide a reachable service's HTTP error by selecting a different backend."""
    fixtures = _fixtures()

    def respond(_opener: object, url: str, **kwargs: Any) -> Any:
        """Raise the requested HTTP failure before any alternate service can be selected."""
        raise urllib.error.HTTPError(url, status, "LLM service rejected model listing", {}, None)

    monkeypatch.setattr(fixtures.urllib.request.OpenerDirector, "open", respond)
    with pytest.raises(urllib.error.HTTPError) as failure:
        fixtures._detect_llm_backend()
    assert failure.value.code == status


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("model_list_available", [False, True])
def test_missing_prerequisites_only_skip_optional_runs(
    monkeypatch: pytest.MonkeyPatch, required: bool, model_list_available: bool
) -> None:
    """Distinguish optional skips from required acceptance failures for absent prerequisites."""
    fixtures = _fixtures()
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def respond(_opener: object, url: str, **kwargs: Any) -> Any:
        """Represent an offline service or a reachable LM Studio without the required model."""
        if model_list_available and "1234" in url:
            return io.BytesIO(b'{"data": []}')
        raise OSError("service unavailable")

    monkeypatch.setattr(fixtures.urllib.request.OpenerDirector, "open", respond)
    expected = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(expected, match=r"LLM backend|no Gemma 4 model"):
        fixtures._detect_llm_backend(require_llm=required)
