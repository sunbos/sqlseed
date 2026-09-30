"""Availability probes distinguish an offline service from a broken test setup."""

from __future__ import annotations

import importlib

import pytest

from .conftest import fixture_llm_available

pytest.importorskip("sqlseed_ai")
httpx = importlib.import_module("httpx")
MODEL = "google/gemma-4-e2b"


@pytest.mark.parametrize(("status", "available"), [(200, True), (503, False)])
def test_availability_uses_http_status(monkeypatch: pytest.MonkeyPatch, status: int, available: bool) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(status, json={"data": [{"id": MODEL}]}))

    assert fixture_llm_available.__wrapped__(MODEL) is available


@pytest.mark.parametrize(
    ("models", "available"),
    [([], False), ([{"id": "another-model"}], False), ([{"id": "another-model"}, {"id": MODEL}], True)],
)
def test_availability_requires_requested_model(
    monkeypatch: pytest.MonkeyPatch, models: list[dict[str, str]], available: bool
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, json={"data": models}))

    assert fixture_llm_available.__wrapped__(MODEL) is available


@pytest.mark.parametrize("payload", [[], {}, {"data": None}, {"data": [None]}, {"data": [{}]}, {"data": [{"id": 1}]}])
def test_malformed_model_list_fails_setup(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, json=payload))

    with pytest.raises(ValueError, match="LM Studio model"):
        fixture_llm_available.__wrapped__(MODEL)


def test_invalid_model_list_json_fails_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, content=b"not json"))

    with pytest.raises(ValueError):
        fixture_llm_available.__wrapped__(MODEL)


def test_unreachable_service_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", unreachable)

    assert fixture_llm_available.__wrapped__(MODEL) is False


@pytest.mark.parametrize("error", [ValueError("invalid request setup"), RuntimeError("broken probe")])
def test_probe_errors_do_not_skip_real_llm_tests(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken_probe(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(httpx, "get", broken_probe)

    with pytest.raises(type(error)) as caught:
        fixture_llm_available.__wrapped__(MODEL)
    assert caught.value is error
