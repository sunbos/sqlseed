"""Exercise an owner timed wait returning before its clock reaches the deadline."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlseed_web import settings_updates as updates


def test_owner_timeout_is_discarded_even_when_clock_has_not_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    entered = threading.Event()
    calls: list[str] = []
    clock = SimpleNamespace(monotonic=lambda: 100.0, time=time.time)
    monkeypatch.setattr(updates, "time", clock)
    monkeypatch.setattr(updates, "_CACHE", {})
    monkeypatch.setattr(updates, "_PENDING", {})
    monkeypatch.setattr(updates, "_CHECK_TIMEOUT", 0.001)
    monkeypatch.setattr(updates.metadata, "version", lambda _: "0.9")

    # Only the external network and module-local clock are controlled. The
    # actual DaemonTask threads, timed joins, router and HTTP client stay real.
    def fetch(project: str) -> dict[str, Any]:
        calls.append(project)
        entered.set()
        if not release.wait(2):
            raise TimeoutError("fixture was not released")
        return {"files": [{"filename": f"{project}-1.0.tar.gz"}]}

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    app = FastAPI()
    app.include_router(updates.router)
    checks = []
    with TestClient(app) as client:
        try:
            response = client.post("/api/settings/updates")
            assert entered.is_set()
            assert not release.is_set()
            assert response.status_code == 200
            assert all(row["status"] == "failed" for row in response.json()["components"])
            checks = list(updates._PENDING.values())
            assert len(checks) == len(updates._PROJECTS)
            assert all(not check.task.wait(0) for check in checks)
            assert all(check.discarded for check in checks)
            snapshot = dict(updates._CACHE)
            assert len(snapshot) == len(updates._PROJECTS)
            assert all(row["cached"] for row in client.post("/api/settings/updates").json()["components"])
            updates._CACHE.clear()
            client.post("/api/settings/updates")
            assert list(updates._PENDING.values()) == checks
            assert len(calls) == len(updates._PROJECTS)
            snapshot = dict(updates._CACHE)
        finally:
            release.set()
            assert all(check.task.wait(2) for check in updates._PENDING.values())
        assert updates._CACHE == snapshot
        updates._CACHE.clear()
        monkeypatch.setattr(updates, "time", time)
        monkeypatch.setattr(updates, "_CHECK_TIMEOUT", 1)
        monkeypatch.setattr(updates, "_fetch_index", lambda project: {"files": [{"filename": f"{project}-2.0.tar.gz"}]})
        response = client.post("/api/settings/updates")
        assert all(row["latest"] == "2.0" for row in response.json()["components"])
        assert not updates._PENDING
