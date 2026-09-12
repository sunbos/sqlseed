"""Availability probes distinguish an offline service from a broken test setup."""

from __future__ import annotations

import importlib

import pytest

from .conftest import fixture_llm_available

pytest.importorskip("sqlseed_ai")
httpx = importlib.import_module("httpx")


@pytest.mark.parametrize(("status", "available"), [(200, True), (503, False)])
def test_availability_uses_http_status(monkeypatch: pytest.MonkeyPatch, status: int, available: bool) -> None:
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(status))

    assert fixture_llm_available.__wrapped__() is available


def test_unreachable_service_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", unreachable)

    assert fixture_llm_available.__wrapped__() is False


@pytest.mark.parametrize("error", [ValueError("invalid request setup"), RuntimeError("broken probe")])
def test_probe_errors_do_not_skip_real_llm_tests(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken_probe(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(httpx, "get", broken_probe)

    with pytest.raises(type(error)) as caught:
        fixture_llm_available.__wrapped__()
    assert caught.value is error
