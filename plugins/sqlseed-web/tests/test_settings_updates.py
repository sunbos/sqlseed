from __future__ import annotations

import json
from importlib import metadata
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sqlseed_web import settings_updates as updates
from sqlseed_web.app import create_app

from .component_test_support import HTTPExchange


@pytest.fixture(autouse=True)
def clean_cache() -> Any:
    updates._CACHE.clear()
    yield
    updates._CACHE.clear()


def index(*versions: str) -> dict[str, Any]:
    return {"files": [{"filename": f"sqlseed-{version}.tar.gz", "yanked": False} for version in versions]}


def test_latest_stable_uses_pep440_and_excludes_yanked_and_prerelease() -> None:
    payload = index("1.9", "1.10", "2.0rc1", "3.0.dev1", "4.0+local", "1.10.post1")
    payload["files"] += [
        {"filename": "sqlseed-9.0.tar.gz", "yanked": ""},
        {"filename": "other-20.0.tar.gz", "yanked": False},
        {"filename": "invalid", "yanked": False},
    ]
    assert updates._latest_stable("sqlseed", payload) == "1.10.post1"
    assert updates._latest_stable("faker", {"files": [{"filename": "Faker-40.0-py3-none-any.whl"}]}) == "40.0"


@pytest.mark.parametrize(
    ("current", "latest", "status"),
    [
        ("1.9", "1.10", "update_available"),
        ("2.0rc1", "2.0", "update_available"),
        ("2.1.dev3", "2.0", "ahead"),
        ("2.0+editable", "2.0", "ahead"),
        ("2.0", "2.0", "current"),
        (None, "2.0", "not_installed"),
        ("unknown", "2.0", "unknown"),
        ("2.0", None, "failed"),
    ],
)
def test_comparison(current: str | None, latest: str | None, status: str) -> None:
    assert updates._compare(current, latest) == status


def test_explicit_endpoint_caches_remote_metadata_but_rereads_local_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fetch(project: str) -> dict[str, Any]:
        calls.append(project)
        return {"files": [{"filename": f"{project}-1.10.tar.gz", "yanked": False}]}

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    monkeypatch.setattr(updates.metadata, "version", lambda _: "1.9")
    with TestClient(create_app()) as client:
        assert not calls
        assert client.get("/api/settings/updates").status_code == 405
        first = client.post("/api/settings/updates").json()
        assert len(first["components"]) == 7
        assert all(row["status"] == "update_available" for row in first["components"])
        monkeypatch.setattr(updates.metadata, "version", lambda _: "1.10")
        second = client.post("/api/settings/updates").json()
        assert len(calls) == 7
        assert all(row["status"] == "current" and row["cached"] for row in second["components"])


def test_partial_failure_is_sanitized_and_short_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch(project: str) -> dict[str, Any]:
        if project == "faker":
            raise OSError("secret-api-key C:/private/path")
        return {"files": [{"filename": f"{project}-1.0.tar.gz"}]}

    def local(project: str) -> str:
        if project == "mimesis":
            raise metadata.PackageNotFoundError(project)
        return "0.9"

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    monkeypatch.setattr(updates.metadata, "version", local)
    data = updates.check_updates()
    rows = {row["id"]: row for row in data["components"]}
    assert rows["faker"]["status"] == "failed"
    assert rows["mimesis"]["status"] == "not_installed"
    assert rows["core"]["latest"] == "1.0"
    assert "secret" not in json.dumps(data)
    assert updates._CACHE["faker"][0] < updates._CACHE["sqlseed"][0]


def test_http_boundary_is_fixed_metadata_only_and_rejects_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    exchange = HTTPExchange(status=302)
    monkeypatch.setattr(updates.http.client, "HTTPSConnection", exchange.connection)
    with pytest.raises(ValueError):
        updates._fetch_index("sqlseed")
    assert exchange.calls == [
        ("pypi.org", 5),
        (
            "GET",
            "/simple/sqlseed/",
            {"Accept": "application/vnd.pypi.simple.v1+json", "User-Agent": "sqlseed-update-check"},
        ),
    ]
    assert exchange.closed == [True]
    with pytest.raises(ValueError):
        updates._fetch_index("https://attacker.test/")
    assert len(exchange.calls) == 2


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"files": []}', b"x" * 33])
def test_invalid_or_oversized_metadata_fails_without_raw_output(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    exchange = HTTPExchange(status=200, body=body)
    monkeypatch.setattr(updates, "_MAX_BYTES", 32)
    monkeypatch.setattr(updates.http.client, "HTTPSConnection", exchange.connection)
    result = updates._remote_version("sqlseed")
    assert result["error"] is True
    assert result["latest"] is None
