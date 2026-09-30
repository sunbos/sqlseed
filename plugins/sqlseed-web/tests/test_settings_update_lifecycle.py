"""Update-check requests remain bounded when DNS or headers outlive socket timeouts."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import Counter
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlseed_web import settings_updates as updates


@pytest.fixture(name="isolated_checks")
def fixture_isolated_checks(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(updates, "_CACHE", {})
    monkeypatch.setattr(updates, "_PENDING", {})
    monkeypatch.setattr(updates, "_CHECK_TIMEOUT", 0.2)
    monkeypatch.setattr(updates, "_TIMEOUT", 0.01)
    monkeypatch.setattr(updates.metadata, "version", lambda _: "0.9")
    yield
    assert all(check.task.wait(2) for check in updates._PENDING.values())


def _index(project: str, version: str) -> dict[str, Any]:
    return {"files": [{"filename": f"{project}-{version}.tar.gz"}]}


class _IndexResponse:
    status = 200

    def __init__(self, project: str) -> None:
        self.content = [json.dumps(_index(project, "1.0")).encode()]

    def read1(self, size: int) -> bytes:
        return self.content.pop() if self.content else b""


@pytest.mark.parametrize("boundary", ["dns", "headers"])
def test_stalled_network_returns_before_release_and_late_reads_cannot_publish_cache(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    started, release = threading.Event(), threading.Event()
    entered: list[str] = []
    closed: list[str] = []

    def wait_at_boundary(name: str) -> None:
        entered.append(name)
        started.set()
        if not release.wait(5):
            raise TimeoutError("test failed to release network boundary")

    def resolver(*args: Any, **kwargs: Any) -> Any:
        wait_at_boundary("dns")
        raise socket.gaierror("secret-token and private resolver details")

    class HeaderConnection:
        def __init__(self, host: str, timeout: float) -> None:
            assert host == "pypi.org"
            assert timeout == 0.01
            self.project = ""

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            assert method == "GET"
            self.project = path.split("/")[2]
            assert self.project in {item[2] for item in updates._PROJECTS}

        def getresponse(self) -> Any:
            wait_at_boundary(self.project)
            return _IndexResponse(self.project)

        def close(self) -> None:
            closed.append(self.project)

    if boundary == "dns":
        monkeypatch.setattr(socket, "getaddrinfo", resolver)
    else:
        monkeypatch.setattr(updates.http.client, "HTTPSConnection", HeaderConnection)
    app = FastAPI()
    app.include_router(updates.router)
    responses: list[Any] = []
    checks = []
    with TestClient(app) as client:
        request = threading.Thread(target=lambda: responses.append(client.post("/api/settings/updates")))
        request.start()
        try:
            assert started.wait(2)
            request.join(1)
            assert not request.is_alive(), "HTTP request must finish while the resolver/header read is still blocked"
            assert responses[0].status_code == 200
            first = responses[0].json()
            assert len(first["components"]) == len(updates._PROJECTS)
            assert all(row["status"] == "failed" for row in first["components"])
            assert "secret-token" not in responses[0].text
            assert not updates._LOCK.locked()
            checks = list(updates._PENDING.values())
            assert len(checks) == len(updates._PROJECTS)
            assert all(check.discarded and not check.task.wait(0) for check in checks)
            repeated = client.post("/api/settings/updates").json()
            assert all(row["cached"] for row in repeated["components"])
            updates._CACHE.clear()  # Expired failure cache must not free the still-running slots.
            repeated = client.post("/api/settings/updates").json()
            assert all(row["status"] == "failed" for row in repeated["components"])
            assert list(updates._PENDING.values()) == checks
            snapshot = dict(updates._CACHE)
        finally:
            release.set()
            request.join(2)
            assert all(check.task.wait(2) for check in updates._PENDING.values())
        assert len(entered) == len(updates._PROJECTS)
        assert updates._CACHE == snapshot, "Late successful metadata must not replace the published timeout"
        if boundary == "headers":
            assert sorted(closed) == sorted(project for _, _, project in updates._PROJECTS)
        updates._CACHE.clear()
        monkeypatch.setattr(updates, "_fetch_index", lambda project: _index(project, "2.0"))
        recovered = client.post("/api/settings/updates").json()
        assert all(row["latest"] == "2.0" and row["status"] == "update_available" for row in recovered["components"])
        assert not updates._PENDING


def test_update_worker_start_failure_is_bounded_and_does_not_reserve_slots(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("private interpreter thread error")

    monkeypatch.setattr(updates, "DaemonTask", unavailable)
    result = updates.check_updates()
    assert len(result["components"]) == len(updates._PROJECTS)
    assert all(row["status"] == "failed" for row in result["components"])
    assert not updates._PENDING
    assert "private interpreter" not in json.dumps(result)


def test_concurrent_partial_checks_share_reads_and_preserve_successful_cache(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    calls: Counter[str] = Counter()
    results: list[dict[str, Any]] = []

    def fetch(project: str) -> dict[str, Any]:
        with lock:
            calls[project] += 1
        if project == "faker":
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release Faker response")
        return _index(project, "1.0")

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    workers = [threading.Thread(target=lambda: results.append(updates.check_updates())) for _ in range(2)]
    try:
        workers[0].start()
        assert entered.wait(2)
        workers[1].start()
        for worker in workers:
            worker.join(1)
            assert not worker.is_alive()
        assert len(results) == 2
        expected_calls = Counter({project: 1 for _, _, project in updates._PROJECTS})
        assert calls == expected_calls
        for result in results:
            rows = {row["id"]: row for row in result["components"]}
            assert rows["faker"]["status"] == "failed"
            assert all(row["latest"] == "1.0" for name, row in rows.items() if name != "faker")
        updates._CACHE.pop("faker")
        retry = updates.check_updates()
        assert calls == expected_calls, "A timed-out read continues to own its project slot"
        assert all(row["cached"] for row in retry["components"] if row["id"] != "faker")
    finally:
        release.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(2)
        assert all(check.task.wait(2) for check in updates._PENDING.values())
    updates._CACHE.pop("faker")
    recovered = updates.check_updates()
    expected_calls["faker"] += 1
    assert calls == expected_calls
    assert all(row["latest"] == "1.0" for row in recovered["components"])


def test_successful_read_completed_after_its_deadline_is_discarded(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updates, "_fetch_index", lambda project: _index(project, "9.0"))
    check = updates._version_check("sqlseed", 0)
    assert isinstance(check, updates._VersionCheck)
    assert check.task.wait(2)
    result = updates._version_result("sqlseed", check, 0)
    assert result["latest"] is None
    assert result["error"] is True
    assert updates._CACHE["sqlseed"][1]["latest"] is None
    assert not updates._PENDING


def test_earlier_observer_deadline_does_not_discard_a_newer_shared_check(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def fetch(project: str) -> dict[str, Any]:
        calls.append(project)
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release shared response")
        return _index(project, "2.0")

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    observer_deadline = time.monotonic()
    owner_deadline = observer_deadline + 3
    owner = updates._version_check("sqlseed", owner_deadline)
    assert isinstance(owner, updates._VersionCheck)
    try:
        assert entered.wait(2)
        observer = updates._version_check("sqlseed", observer_deadline)
        assert observer is owner
        result = updates._version_result("sqlseed", observer, observer_deadline)
        assert result["error"] is True
        assert result["latest"] is None
        assert not owner.discarded
        assert "sqlseed" not in updates._CACHE
        assert updates._PENDING["sqlseed"] is owner
    finally:
        release.set()
        assert owner.task.wait(2)
    result = updates._version_result("sqlseed", owner, owner_deadline)
    assert result["latest"] == "2.0"
    assert result["error"] is False
    assert calls == ["sqlseed"]
    cached = updates._remote_version("sqlseed")
    assert cached["latest"] == "2.0"
    assert cached["cached"] is True
    assert not updates._PENDING


def test_unexpected_worker_exception_releases_its_slot_for_a_fresh_read(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fetch(project: str) -> dict[str, Any]:
        calls.append(project)
        if len(calls) == 1:
            raise RuntimeError("unexpected reader failure")
        return _index(project, "2.0")

    monkeypatch.setattr(updates, "_fetch_index", fetch)
    with pytest.raises(RuntimeError, match="unexpected reader failure"):
        updates._remote_version("sqlseed")
    assert not updates._PENDING
    assert not updates._CACHE
    result = updates._remote_version("sqlseed")
    assert result["latest"] == "2.0"
    assert result["error"] is False
    assert calls == ["sqlseed", "sqlseed"]


def test_excessively_nested_index_is_failed_metadata_without_poisoning_retries(
    isolated_checks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"[" * 10_000 + b"0" + b"]" * 10_000
    monkeypatch.setattr(updates, "_fetch_index", lambda project: json.loads(raw))
    result = updates._remote_version("sqlseed")
    assert result["error"] is True
    assert result["latest"] is None
    assert not updates._PENDING
    updates._CACHE.clear()
    monkeypatch.setattr(updates, "_fetch_index", lambda project: _index(project, "2.0"))
    recovered = updates._remote_version("sqlseed")
    assert recovered["error"] is False
    assert recovered["latest"] == "2.0"
    assert not updates._PENDING
