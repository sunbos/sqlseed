"""Admission boundaries reject duplicate work while real SQLite operations run."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, runtime_lifecycle, workbench, workbench_runtime
from sqlseed_web.state import Connection, ConnectionBusyError, UIState
from sqlseed_web.workbench_runtime import check_document, normalize_document
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import RevisionConflict, WorkspaceStore


def _pause_worker(
    monkeypatch: pytest.MonkeyPatch, conn_id: str | None = None
) -> tuple[threading.Event, threading.Event]:
    entered, release = threading.Event(), threading.Event()
    original = workbench_runtime.execute_run

    def delayed(*args: Any, **kwargs: Any) -> Any:
        if conn_id is None or args[1] == conn_id:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("worker test gate timed out")
        return original(*args, **kwargs)

    monkeypatch.setattr(workbench_runtime, "execute_run", delayed)
    return entered, release


def _assert_marker_write_lock(registry: UIState, one: Connection, two: Connection) -> None:
    assert one.orchestrator.get_row_count("marker") == two.orchestrator.get_row_count("marker") == 1
    job = registry.create_job(one.conn_id, "workbench", "first")
    try:
        with pytest.raises(ConnectionBusyError, match="此数据库"):
            registry.create_job(two.conn_id, "workbench", "second")
    finally:
        registry.complete_job(job.job_id)
        registry.close_connection(one.conn_id)
        registry.close_connection(two.conn_id)


@pytest.fixture(name="workspace")
def fixture_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    path = tmp_path / "target.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY AUTOINCREMENT, value INTEGER NOT NULL)")
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    store = WorkspaceStore(tmp_path / "workspace.db")
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setattr(workbench, "get_store", lambda: store)
    schema = inspect_connection(conn)
    document = normalize_document(
        conn,
        {
            "provider": "base",
            "tables": [
                {
                    "name": "items",
                    "count": 2,
                    "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
                }
            ],
        },
    )
    draft = store.save_draft(
        {
            "name": "concurrency",
            "document": document,
            "schema_hash": schema["schema_hash"],
            "target_key": schema["target_key"],
            "target_label": schema["target_label"],
            "view_state": {},
        }
    )
    checked = check_document(conn, document, schema["schema_hash"])
    assert checked["ok"], checked
    body = {"conn_id": conn.conn_id, "document": document, "schema_hash": schema["schema_hash"]}
    run_body = {
        "conn_id": conn.conn_id,
        "draft_id": draft["id"],
        "revision": draft["revision"],
        "schema_hash": schema["schema_hash"],
        "config_hash": checked["config_hash"],
    }
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(workbench.router)
    with TestClient(app) as client:
        yield client, registry, store, conn, body, run_body
    for connection in registry.list_connections():
        registry.close_connection(connection["conn_id"])


def wait_jobs(registry: UIState) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(job.status != "running" for job in registry.recent_jobs()):
            return
        time.sleep(0.01)
    pytest.fail("accepted workers did not finish")


@pytest.mark.parametrize("next_action", ["preview", "check", "schema"])
def test_repeated_interactive_requests_fail_fast_without_waiting_for_preview(
    workspace: Any,
    monkeypatch: pytest.MonkeyPatch,
    next_action: str,
) -> None:
    client, registry, _, conn, body, _ = workspace
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    original = workbench.check_document

    def delayed(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("preview test gate timed out")
        return original(*args, **kwargs)

    monkeypatch.setattr(workbench, "check_document", delayed)

    def repeat() -> Any:
        try:
            if next_action == "schema":
                return client.get(f"/api/workbench/connections/{conn.conn_id}/schema")
            return client.post(f"/api/workbench/{next_action}", json=body)
        finally:
            returned.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(client.post, "/api/workbench/preview", json=body)
        try:
            assert entered.wait(3)
            repeated = workers.submit(repeat)
            assert returned.wait(1), "duplicate request queued behind the active preview"
            result = repeated.result()
            assert result.status_code == 409, result.text
            assert result.json()["detail"]["code"] == "connection_busy"
            assert client.delete(f"/api/connections/{conn.conn_id}").status_code == 409
        finally:
            release.set()
        assert first.result().status_code == 200
    assert registry.get_connection(conn.conn_id).orchestrator.get_row_count("items") == 0
    assert client.delete(f"/api/connections/{conn.conn_id}").status_code == 200


@pytest.mark.parametrize("second_connection", [False, True])
def test_only_one_write_is_reserved_for_the_same_physical_target(
    workspace: Any,
    monkeypatch: pytest.MonkeyPatch,
    second_connection: bool,
) -> None:
    client, registry, store, conn, _, body = workspace
    entered, release = _pause_worker(monkeypatch)
    first = client.post("/api/workbench/runs", json=body)
    assert first.status_code == 202, first.text
    try:
        assert entered.wait(3)
        if second_connection:
            parallel = registry.add_connection(f"sqlite:///{conn.target}", provider="base")
            body = {**body, "conn_id": parallel.conn_id}
        second = client.post("/api/workbench/runs", json=body)
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["code"] == "connection_busy"
        assert len(store.list_runs()) == 1, "rejected request must not create an orphan queued run"
        assert len(registry.recent_jobs()) == 1
    finally:
        release.set()
        wait_jobs(registry)
    assert store.get_run(first.json()["id"])["status"] == "done"
    with sqlite_connection(conn.target) as db:
        assert db.execute("SELECT id,value FROM items ORDER BY id").fetchall() == [(1, 7), (2, 7)]


def test_other_sessions_can_read_and_other_targets_can_generate(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, store, conn, check_body, body = workspace
    entered, release = _pause_worker(monkeypatch, conn.conn_id)
    first = client.post("/api/workbench/runs", json=body)
    assert first.status_code == 202, first.text
    try:
        assert entered.wait(3)
        saved_configs = client.get(f"/api/workbench/drafts?conn_id={conn.conn_id}")
        assert saved_configs.status_code == 200, saved_configs.text
        assert saved_configs.json()[0]["id"] == body["draft_id"]
        parallel = registry.add_connection(f"sqlite:///{conn.target}", provider="faker", locale="zh_CN")
        preview = client.post("/api/workbench/preview", json={**check_body, "conn_id": parallel.conn_id})
        assert preview.status_code == 200, preview.text
        assert preview.json()["ok"], preview.text
        assert registry.get_connection(parallel.conn_id).provider == "faker"
        assert registry.get_connection(conn.conn_id).provider == "base"
        other_path = Path(conn.target).with_name("independent.db")
        with sqlite_connection(other_path) as db:
            db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY AUTOINCREMENT, value INTEGER NOT NULL)")
        other = registry.add_connection(str(other_path), provider="base")
        other_schema = inspect_connection(other)
        draft = store.save_draft(
            {
                "name": "other target",
                "document": check_body["document"],
                "schema_hash": other_schema["schema_hash"],
                "target_key": other_schema["target_key"],
                "target_label": other_schema["target_label"],
                "view_state": {},
            }
        )
        second = client.post("/api/workbench/runs", json={**body, "conn_id": other.conn_id, "draft_id": draft["id"]})
        assert second.status_code == 202, second.text
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and store.get_run(second.json()["id"])["status"] not in {"done", "error"}:
            time.sleep(0.01)
        assert store.get_run(second.json()["id"])["status"] == "done"
        assert store.get_run(first.json()["id"])["status"] == "queued"
        with sqlite_connection(other_path) as db:
            assert db.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]
    finally:
        release.set()
        wait_jobs(registry)


def test_reentry_fails_immediately_and_outer_operation_remains_valid(workspace: Any) -> None:
    _, registry, _, conn, _, _ = workspace
    with registry.connection_operation(conn.conn_id):
        with pytest.raises(ConnectionBusyError, match="处理请求"), registry.connection_operation(conn.conn_id):
            pytest.fail("non-reentrant orchestrator must not admit a nested operation")
        assert conn.orchestrator.get_row_count("items") == 0
    with registry.connection_operation(conn.conn_id):
        assert conn.orchestrator.get_row_count("items") == 0


def test_snapshot_conflict_releases_write_reservation(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, registry, store, conn, _, body = workspace
    original = store.create_run

    def conflicted(*args: Any, **kwargs: Any) -> Any:
        raise RevisionConflict("草稿在检查时发生变化")

    monkeypatch.setattr(store, "create_run", conflicted)
    failed = client.post("/api/workbench/runs", json=body)
    assert failed.status_code == 409, failed.text
    assert store.list_runs() == []
    assert all(job.status != "running" for job in registry.recent_jobs())
    monkeypatch.setattr(store, "create_run", original)
    retry = client.post("/api/workbench/runs", json=body)
    assert retry.status_code == 202, retry.text
    wait_jobs(registry)
    assert store.get_run(retry.json()["id"])["status"] == "done"
    assert conn.orchestrator.get_row_count("items") == 2


@pytest.mark.parametrize("endpoint", ["fill", "heal/auto"])
def test_legacy_job_requests_return_busy_instead_of_queuing(workspace: Any, endpoint: str) -> None:
    if endpoint == "heal/auto":
        pytest.importorskip("sqlseed_ai")
    client, registry, _, conn, _, _ = workspace
    job = registry.create_job(conn.conn_id, "workbench", "reserved")
    try:
        result = client.post(f"/api/connections/{conn.conn_id}/{endpoint}", json={"table": "items", "count": 2})
        assert result.status_code == 409, result.text
        assert "任务" in result.json()["detail"]
        assert len(registry.recent_jobs()) == 1
    finally:
        registry.complete_job(job.job_id, result={})


@pytest.mark.parametrize("fail_publication", [False, True])
def test_worker_start_failure_releases_reserved_connection(
    workspace: Any, monkeypatch: pytest.MonkeyPatch, fail_publication: bool
) -> None:
    _, registry, store, conn, _, body = workspace

    class UnavailableWorker:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("worker unavailable")

    monkeypatch.setattr(runtime_lifecycle.threading, "Thread", UnavailableWorker)
    if fail_publication:

        def unavailable_store(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("workspace unavailable")

        monkeypatch.setattr(store, "update_run", unavailable_store)
    with pytest.raises(RuntimeError, match="worker unavailable"):
        workbench_runtime.start_run(**body, registry=registry, store=store)
    if not fail_publication:
        assert store.list_runs()[0]["status"] == "error"
    assert all(job.status == "error" for job in registry.recent_jobs())
    assert conn.orchestrator.get_row_count("items") == 0
    registry.close_connection(conn.conn_id)


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("postgresql://a:p@SERVER/data", "postgresql+psycopg://b:q@server:5432/data?sslmode=require", True),
        ("postgresql://a@ignored/data?host=SERVER&port=5433", "postgresql://b@server:5433/data", True),
        ("postgresql://a@ignored/data?host=SERVER:5433", "postgresql://b@server:5433/data", True),
        ("postgresql://a@ignored/old?dbname=data&host=SERVER", "postgresql://b@server/data", True),
        ("postgresql://a@ignored/data?host=server:5432&host=backup:5433", "postgresql://b@backup:5433/data", True),
        ("postgresql://a@server/data", "postgresql://b@server/other", False),
        ("postgresql://a@server/data", "postgresql://b@server:5433/data", False),
    ],
)
def test_postgres_url_admission_uses_effective_endpoints_without_connecting(
    first: str, second: str, same: bool
) -> None:
    registry = UIState()
    one = registry.add_connection(first, provider="base")
    two = registry.add_connection(second, provider="base")
    jobs = [registry.create_job(one.conn_id, "workbench", "first")]
    try:
        if same:
            with pytest.raises(ConnectionBusyError, match="此数据库"):
                registry.create_job(two.conn_id, "workbench", "second")
        else:
            jobs.append(registry.create_job(two.conn_id, "workbench", "second"))
    finally:
        for job in jobs:
            registry.complete_job(job.job_id)
        registry.close_connection(one.conn_id)
        registry.close_connection(two.conn_id)


@pytest.mark.parametrize("alias", ["uri", "symlink"])
def test_sqlite_file_aliases_share_write_admission(tmp_path: Path, alias: str) -> None:
    from urllib.parse import quote

    path = tmp_path / "database with spaces.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE marker(value TEXT)")
        db.execute("INSERT INTO marker VALUES ('same physical database')")
    if alias == "uri":
        target = f"sqlite:///file:{quote(str(path))}?uri=true&mode=rw"
    else:
        link = tmp_path / "alias.db"
        link.symlink_to(path)
        target = f"sqlite:///{link}"
    registry = UIState()
    one = registry.add_connection(str(path), provider="base")
    two = registry.add_connection(target, provider="base")
    _assert_marker_write_lock(registry, one, two)


@pytest.mark.parametrize("database", ["shared-admission", ":memory:"])
def test_real_shared_memory_uri_cannot_reserve_two_writers(database: str) -> None:
    uri = f"file:{database}?mode=memory&cache=shared"
    with sqlite_connection(uri, uri=True) as anchor:
        anchor.execute("CREATE TABLE marker(value TEXT)")
        anchor.execute("INSERT INTO marker VALUES ('shared')")
        anchor.commit()
        registry = UIState()
        one = registry.add_connection(f"sqlite:///{uri}&uri=true", provider="base")
        two = registry.add_connection(f"sqlite:///{uri}&uri=true&timeout=10", provider="base")
        _assert_marker_write_lock(registry, one, two)


def test_private_memory_sessions_keep_independent_write_admission() -> None:
    registry = UIState()
    one = registry.add_connection(":memory:", provider="base")
    two = registry.add_connection("sqlite:///:memory:", provider="base")
    jobs = [registry.create_job(conn.conn_id, "workbench", "independent") for conn in (one, two)]
    for job in jobs:
        registry.complete_job(job.job_id)
    for conn in (one, two):
        registry.close_connection(conn.conn_id)


def test_worker_snapshot_read_failure_releases_reserved_connection(workspace: Any) -> None:
    _, registry, store, conn, _, _ = workspace
    job = registry.create_job(conn.conn_id, "workbench", "missing snapshot")
    workbench_runtime.execute_run("missing-snapshot", conn.conn_id, job.job_id, registry=registry, store=store)
    assert registry.job_snapshot(job.job_id).status == "error"
    assert conn.orchestrator.get_row_count("items") == 0
    registry.close_connection(conn.conn_id)
