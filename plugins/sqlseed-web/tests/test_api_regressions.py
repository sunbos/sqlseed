"""Regression coverage for config fidelity, database errors, and job lifecycle."""

from __future__ import annotations

import builtins
import importlib
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlseed.config.models import GeneratorConfig
from tests.llm_helpers import no_network_openai_client
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api
from sqlseed_web.app import create_app
from sqlseed_web.state import Job, UIState


@pytest.fixture(name="client")
def fixture_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client
    for conn in registry.list_connections():
        registry.close_connection(conn["conn_id"])


@pytest.fixture(name="db_path")
def fixture_db_path(tmp_path: Path) -> str:
    path = tmp_path / "regressions.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, value INTEGER NOT NULL)")
        db.execute("CREATE TABLE evens (id INTEGER PRIMARY KEY AUTOINCREMENT, value INTEGER CHECK(value % 2 = 0))")
    return str(path)


def connect(client: TestClient, db_path: str, *, as_url: bool = False) -> str:
    target = {"url": f"sqlite+pysqlite:///{db_path}"} if as_url else {"db_path": db_path}
    response = client.post("/api/connections", json={**target, "provider": "base"})
    assert response.status_code == 200, response.text
    return response.json()["conn_id"]


def poll_job(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job_id}").json()
        if result["status"] != "running":
            return result
        time.sleep(0.01)
    return pytest.fail("background job never finished")


def test_failed_insert_reports_error_and_actual_count(client: TestClient, db_path: str) -> None:
    cid = connect(client, db_path)
    response = client.post(
        f"/api/connections/{cid}/fill",
        json={
            "table": "evens",
            "count": 3,
            "columns": {"value": {"generator": "integer", "min_value": 1, "max_value": 1}},
        },
    )
    result = poll_job(client, response.json()["job_id"])
    assert result["status"] == "error", result
    assert "CHECK constraint failed" in result["error"]
    assert result["rows_inserted"] == result["result"]["rows_inserted"] == 0
    assert result["result"]["errors"]
    assert result["result"]["row_count_after"] == 0
    assert api.state.get_job(response.json()["job_id"]).finished_at > 0
    with sqlite_connection(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM evens").fetchone()[0] == 0


def test_config_roundtrip_preserves_every_validated_field(client: TestClient, db_path: str) -> None:
    original = GeneratorConfig.model_validate(
        {
            "db_path": db_path,
            "provider": "base",
            "locale": "zh_CN",
            "optimize_pragma": False,
            "snapshot_dir": "snapshots",
            "associations": [{"column_name": "value", "source_table": "items", "target_tables": ["evens"]}],
            "custom_column_mappings": {
                "exact": {"value": {"generator": "integer", "params": {"min_value": 10}}},
                "pattern": [{"pattern": "^value$", "generator": "integer"}],
            },
            "tables": [
                {
                    "name": "items",
                    "count": 3,
                    "seed": 0,
                    "batch_size": 2,
                    "clear_before": True,
                    "enrich": True,
                    "transform": "transform.py",
                    "columns": [
                        {
                            "name": "value",
                            "generator": "integer",
                            "null_ratio": 0.5,
                            "constraints": {"regex": "^1", "max_retries": 0},
                            "faker_method": "random_int",
                            "mimesis_method": "numeric.integer",
                            "native_params": {"min": 1},
                        },
                        {"name": "derived", "derive_from": ["id", "value"], "expression": "id + value"},
                        {
                            "name": "category",
                            "generator": "choice",
                            "params": {"weighted_choices": {"a:b": 80, "yes": 20}},
                        },
                    ],
                }
            ],
        }
    )
    response = client.post("/api/config/parse", json={"yaml": original.model_dump_json()}).json()
    assert response["valid"], response
    serialized = client.post("/api/config/serialize", json={"yaml": json.dumps(response["config"])}).json()["yaml"]
    restored = api.load_config_from_text(serialized)
    assert restored.model_dump() == original.model_dump()


@pytest.mark.parametrize(
    ("method", "path", "body", "detail"),
    [
        ("post", "query", {"sql": "SELECT missing FROM items"}, "no such column"),
        ("post", "query", {"sql": "SELECT * FROM missing"}, "no such table"),
        ("get", "tables/missing/rows", None, "missing"),
        ("get", "tables/missing/schema", None, "missing"),
        (
            "post",
            "preview",
            {"table": "items", "columns": {"value": {"generator": "unknown_test_generator"}}},
            "unknown_test_generator",
        ),
    ],
)
def test_database_input_errors_are_structured(
    client: TestClient,
    db_path: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    detail: str,
) -> None:
    cid = connect(client, db_path)
    response = client.request(method, f"/api/connections/{cid}/{path}", json=body)
    assert response.status_code == 400, response.text
    assert detail in response.json()["detail"]


@pytest.mark.parametrize("endpoint", ["validate", "repair"])
def test_heal_accepts_driver_qualified_sqlite_url(client: TestClient, db_path: str, endpoint: str) -> None:
    pytest.importorskip("sqlseed_ai")
    cid = connect(client, db_path, as_url=True)
    response = client.post(
        f"/api/connections/{cid}/heal/{endpoint}",
        json={"yaml": "tables:\n- name: items\n  count: 2\n  columns:\n  - name: value\n    generator: integer\n"},
    )
    assert response.status_code == 200
    assert response.json()["ok"], response.json()


def test_yaml_template_classifies_driver_qualified_url(client: TestClient, db_path: str) -> None:
    cid = connect(client, db_path, as_url=True)
    response = client.get(f"/api/connections/{cid}/tables/items/yaml-template")
    config = yaml.safe_load(response.json()["yaml"])
    assert config["url"] == f"sqlite+pysqlite:///{db_path}"
    assert "db_path" not in config


@pytest.mark.parametrize("kind", ["fill", "auto_heal"])
def test_close_refuses_queued_job_and_worker_can_finish(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    if kind == "auto_heal":
        pytest.importorskip("sqlseed_ai")
    cid = connect(client, db_path)
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    name = "_run_fill_job" if kind == "fill" else "_run_auto_heal_job"
    original = getattr(api, name)

    def delayed(*args: Any) -> None:
        entered.set()
        try:
            assert release.wait(10)
            original(*args)
        finally:
            ended.set()

    monkeypatch.setattr(api, name, delayed)
    endpoint = "fill" if kind == "fill" else "heal/auto"
    payload = {"table": "items", "count": 2} if kind == "fill" else {"backend": "invalid_backend"}
    job_id = client.post(f"/api/connections/{cid}/{endpoint}", json=payload).json()["job_id"]
    try:
        assert entered.wait(5)
        closed = client.delete(f"/api/connections/{cid}")
    finally:
        release.set()
        assert ended.wait(10)
    assert closed.status_code == 409, closed.text
    assert "任务" in closed.json()["detail"]
    result = poll_job(client, job_id)
    assert result["status"] == ("done" if kind == "fill" else "error")
    assert api.state.get_job(job_id).finished_at > 0
    assert client.delete(f"/api/connections/{cid}").status_code == 200


@pytest.mark.parametrize("kind", ["fill", "auto_heal"])
def test_worker_with_missing_connection_finishes_as_error(client: TestClient, db_path: str, kind: str) -> None:
    cid = connect(client, db_path)
    job = api.state.create_job(cid, kind, "items")
    worker = api._run_fill_job if kind == "fill" else api._run_auto_heal_job
    req = api.FillRequest(table="items", count=1) if kind == "fill" else api.AutoHealRequest()
    worker("expired-connection", job.job_id, req)
    assert job.status == "error"
    assert "unknown connection" in job.error
    assert job.finished_at > 0


def test_create_job_rejects_closed_connection(client: TestClient, db_path: str) -> None:
    cid = connect(client, db_path)
    assert client.delete(f"/api/connections/{cid}").status_code == 200
    with pytest.raises(KeyError, match="unknown connection"):
        api.state.create_job(cid, "fill", "items")


@pytest.mark.parametrize("endpoint", ["preview", "fill"])
def test_generation_applies_table_transform(client: TestClient, db_path: str, tmp_path: Path, endpoint: str) -> None:
    script = tmp_path / "transform.py"
    script.write_text("def transform_row(row, ctx):\n    return {**row, 'value': 876}\n", encoding="utf-8")
    cid = connect(client, db_path)
    response = client.post(
        f"/api/connections/{cid}/{endpoint}",
        json={
            "table": "items",
            "count": 2,
            "seed": 17,
            "transform": str(script),
            "columns": {"value": {"generator": "integer", "min_value": 1, "max_value": 1}},
        },
    )
    assert response.status_code == 200, response.text
    if endpoint == "fill":
        assert poll_job(client, response.json()["job_id"])["status"] == "done"
        rows = client.get(f"/api/connections/{cid}/tables/items/rows").json()["rows"]
    else:
        rows = response.json()["rows"]
    assert [row["value"] for row in rows] == [876, 876]


@pytest.mark.parametrize("as_url", [False, True])
def test_auto_heal_publishes_complete_result_before_done(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
    as_url: bool,
) -> None:
    pytest.importorskip("sqlseed_ai")
    from sqlseed_ai import runtime

    class NoNetworkClient:
        def chat_completions_create(self, **kwargs: Any) -> Any:
            pytest.fail("unexpected LLM call")

        def close(self) -> None:
            pass

    monkeypatch.setattr(runtime, "build_llm_client", lambda _cfg: NoNetworkClient())
    cid = connect(client, db_path, as_url=as_url)
    job = api.state.create_job(cid, "auto_heal", "auto-heal")
    published: list[dict[str, Any]] = []
    original_setattr = Job.__setattr__

    def observe_status(self: Job, name: str, value: Any) -> None:
        original_setattr(self, name, value)
        if self is job and name == "status" and value == "done":
            published.append({"result": dict(self.result), "finished_at": self.finished_at})

    monkeypatch.setattr(Job, "__setattr__", observe_status)
    api._run_auto_heal_job(
        cid,
        job.job_id,
        api.AutoHealRequest(
            model="offline-test",
            backend="openai_compat",
            api_key="test-key",
            base_url="http://127.0.0.1:1/v1",
        ),
    )
    assert job.status == "done", job.error
    assert len(published) == 1
    assert published[0]["result"]["yaml"]
    assert published[0]["result"]["llm_calls"] == 0
    assert published[0]["finished_at"] > 0


def test_auto_heal_missing_runtime_dependency_returns_503(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sqlseed_ai")
    cid = connect(client, db_path)
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def missing_runtime(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sqlseed_ai.runtime":
            raise ImportError("runtime dependency missing: private-provider-secret")
        return original_import(name, *args, **kwargs)

    def missing_runtime_module(name: str, package: str | None = None) -> Any:
        if name == "sqlseed_ai.runtime":
            return missing_runtime(name)
        return original_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", missing_runtime)
    monkeypatch.setattr(importlib, "import_module", missing_runtime_module)
    response = client.post(f"/api/connections/{cid}/heal/auto", json={})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ai_unavailable"
    assert detail["component_id"] == "ai"
    assert detail["availability_status"] == "import_error"
    assert detail["recovery_action"] == "repair"
    assert "private-provider-secret" not in response.text
    assert "未安装" not in detail["message"]
    assert client.delete(f"/api/connections/{cid}").status_code == 200


@pytest.mark.parametrize(
    ("module_name", "export_name", "endpoint"),
    [
        ("sqlseed_ai.contracts.builtin_violations", "BUILTIN_VIOLATIONS", "heal/validate"),
        ("sqlseed_ai.runtime", "build_ai_config", "heal/auto"),
    ],
)
def test_heal_missing_required_export_returns_503_before_job_admission(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    export_name: str,
    endpoint: str,
) -> None:
    pytest.importorskip("sqlseed_ai")
    module = importlib.import_module(module_name)
    cid = connect(client, db_path)
    monkeypatch.setattr(api, "require_ai_available", lambda: None)
    monkeypatch.delattr(module, export_name)

    response = client.post(f"/api/connections/{cid}/{endpoint}", json={"yaml": "tables: []"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ai_unavailable"
    assert detail["availability_status"] == "import_error"
    assert detail["recovery_action"] == "repair"
    assert not api.state.recent_jobs()
    assert client.delete(f"/api/connections/{cid}").status_code == 200


@pytest.mark.parametrize("failure", [None, "construct", "run"])
def test_auto_heal_releases_owned_client_before_terminal_state(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    pytest.importorskip("sqlseed_ai")
    from sqlseed_ai import runtime
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.healer._client import OpenAICompatAdapter

    transport_client, sdk_client = no_network_openai_client()
    monkeypatch.setattr(runtime, "build_llm_client", lambda _config: OpenAICompatAdapter(sdk_client))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("controlled runtime failure")

    if failure == "construct":
        monkeypatch.setattr(runtime, "build_heal_orchestrator", fail)
    elif failure == "run":
        monkeypatch.setattr(AutoHealOrchestrator, "run", fail)
    cid = connect(client, db_path)
    job = api.state.create_job(cid, "auto_heal", "auto-heal")
    published_closed: list[bool] = []
    original_setattr = Job.__setattr__

    def observe_terminal(self: Job, name: str, value: Any) -> None:
        original_setattr(self, name, value)
        if self is job and name == "status" and value in {"done", "error"}:
            published_closed.append(transport_client.is_closed)

    monkeypatch.setattr(Job, "__setattr__", observe_terminal)
    try:
        api._run_auto_heal_job(cid, job.job_id, api.AutoHealRequest(backend="ollama", model="fixed-model"))
        assert job.status == ("error" if failure else "done"), job.error
        assert job.finished_at > 0
        assert transport_client.is_closed
        assert published_closed == [True]
        if failure:
            assert "controlled runtime failure" in job.error
        else:
            assert job.result["llm_calls"] == 0
            assert yaml.safe_load(job.result["yaml"])["tables"]
        assert client.delete(f"/api/connections/{cid}").status_code == 200
    finally:
        sdk_client.close()


@pytest.mark.parametrize("phase", ["after_lookup", "before_lock"])
def test_preview_closed_before_lock_returns_404_without_reopening(
    client: TestClient,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    cid = connect(client, db_path)
    orch = api.state.get_connection(cid).orchestrator
    reached, release = threading.Event(), threading.Event()

    def gate() -> None:
        reached.set()
        assert release.wait(5)

    if phase == "after_lookup":
        original = api._conn_or_404

        def delayed_lookup(conn_id: str) -> Any:
            result = original(conn_id)
            gate()
            return result

        monkeypatch.setattr(api, "_conn_or_404", delayed_lookup)
    else:
        original_operation = api.state.connection_operation

        @contextmanager
        def delayed_operation(*args: Any, **kwargs: Any) -> Any:
            # Admission now atomically checks liveness and tries the lock.
            # Pause just before that boundary, where close can still win.
            gate()
            with original_operation(*args, **kwargs) as connection:
                yield connection

        monkeypatch.setattr(api.state, "connection_operation", delayed_operation)

    responses: list[Any] = []
    thread = threading.Thread(
        target=lambda: responses.append(
            client.post(
                f"/api/connections/{cid}/preview",
                json={"table": "items", "count": 1},
            )
        )
    )
    thread.start()
    try:
        assert reached.wait(5)
        closed = client.delete(f"/api/connections/{cid}")
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert closed.status_code == 200, closed.text
    assert responses[0].status_code == 404, responses[0].text
    assert "unknown connection" in responses[0].json()["detail"]
    assert not orch._connected
