"""Browser-origin boundaries protect local APIs without changing database state."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sqlseed_web import api
from sqlseed_web.app import create_app
from sqlseed_web.state import UIState


@pytest.fixture()
def local_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, UIState, Path]:
    database = tmp_path / "private.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('unchanged')")
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    # No lifespan: this fixture must not acquire the user's live environment lock.
    client = TestClient(create_app(), base_url="http://127.0.0.1:8630")
    yield client, registry, database
    client.close()
    for connection in registry.list_connections():
        registry.close_connection(connection["conn_id"])


def test_cross_origin_reads_preflights_and_simple_posts_cannot_access_local_connections(local_api: tuple) -> None:
    client, registry, database = local_api
    origin = "https://untrusted.example"
    created = client.post("/api/connections", json={"db_path": str(database), "provider": "base"})
    assert created.status_code == 200
    before = registry.list_connections()
    for response in (
        client.get("/api/connections", headers={"Origin": origin}),
        client.options(
            "/api/connections",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        ),
        client.post(
            "/api/connections",
            headers={"Origin": origin},
            content=json.dumps({"db_path": str(database), "provider": "base"}),
        ),
        client.get("/api/connections", headers={"Sec-Fetch-Site": "cross-site"}),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "cross_origin_forbidden"
        assert "access-control-allow-origin" not in response.headers
        assert str(database) not in response.text
    assert registry.list_connections() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM records").fetchall() == [("unchanged",)]


@pytest.mark.parametrize("origin", [None, "http://127.0.0.1:8630"])
def test_same_origin_and_non_browser_clients_can_read_and_connect(local_api: tuple, origin: str | None) -> None:
    client, registry, database = local_api
    headers = {"Origin": origin} if origin else {}
    response = client.post("/api/connections", headers=headers, json={"db_path": str(database), "provider": "base"})
    assert response.status_code == 200
    assert len(registry.list_connections()) == 1
    assert client.get("/api/connections", headers=headers).status_code == 200


def test_external_same_origin_deployment_uses_asgi_scheme_and_keeps_ordinary_api_available() -> None:
    client = TestClient(create_app(), base_url="https://workbench.example")
    try:
        assert client.get("/api/health", headers={"Origin": "https://workbench.example"}).status_code == 200
        assert client.get("/api/health", headers={"Origin": "http://workbench.example"}).status_code == 403
    finally:
        client.close()


def test_supervised_local_listener_rejects_rebound_host_even_without_origin() -> None:
    client = TestClient(create_app(supervised_worker=True), base_url="http://127.0.0.1:8630")
    try:
        response = client.get("/api/health", headers={"Host": "untrusted.example:8630"})
        assert response.status_code == 403
        assert client.get("/api/health").status_code == 200
    finally:
        client.close()


def test_workbench_page_cannot_be_embedded_for_clickjacking() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
