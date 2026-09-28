"""Web message descriptors survive real boundaries without changing business data."""

from __future__ import annotations

import json
import multiprocessing
from collections.abc import Callable, Iterator
from copy import deepcopy
from pathlib import Path
from string import Formatter
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, workbench, workbench_data
from sqlseed_web.app import create_app
from sqlseed_web.diagnostics import public_error
from sqlseed_web.messages import (
    Message,
    MessageRoute,
    catalog,
    legacy_message,
    materialize_messages,
    message,
    message_list,
)
from sqlseed_web.state import UIState
from sqlseed_web.workbench_ai_stream import analysis_response
from sqlseed_web.workbench_store import WorkspaceStore
from sqlseed_web.worker_control import ControlChannel, ControlError

from .test_workbench_store import draft_payload, run_payload

_EMPTY_PLAN = "backend.workbench_runtime.select_at_least_one_table_to_generate"
_CONTEXT = "backend.workbench_ai.reading_the_schema_and_current_rules"
_AI_FAILURE = "backend.workbench_ai.the_ai_service_returned_http_check_the"


@pytest.fixture(name="message_client")
def fixture_message_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    registry = UIState()
    for module in (api, workbench, workbench_data):
        monkeypatch.setattr(module, "state", registry)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.db"))
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(tmp_path / "settings.json"))
    path = tmp_path / "business.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, message TEXT, message_key TEXT, message_params TEXT)")
        db.execute(
            "INSERT INTO records VALUES (1, ?, ?, ?)",
            ("用户内容", _EMPTY_PLAN, '{"p1":"user input"}'),
        )
    # Deliberately avoid lifespan and therefore the live environment's lock.
    client = TestClient(create_app(), base_url="http://127.0.0.1:9876", client=("127.0.0.1", 40000))
    try:
        yield client, path
    finally:
        client.close()
        for connection in registry.list_connections():
            registry.close_connection(connection["conn_id"])


def test_http_legacy_string_object_and_validation_array_remain_compatible(message_client: tuple) -> None:
    client, path = message_client
    response = client.post("/api/connections", json={"db_path": str(path), "url": "sqlite://"})
    body = response.json()
    assert response.status_code == 422
    assert body["detail"] == "provide exactly one of db_path / url"
    assert body["detail_key"].startswith("backend.api.")
    assert body["detail_params"] == {}

    forbidden = client.get("/api/connections", headers={"Origin": "https://untrusted.example"}).json()["detail"]
    assert forbidden["code"] == "cross_origin_forbidden"
    assert forbidden["message"] == "业务请求必须来自当前工作台页面。"
    assert forbidden["message_key"] in catalog()

    rejected = client.post("/api/workbench/parse", json={"conn_id": [], "text": "x", "api_key": "hidden-secret"})
    assert rejected.status_code == 422
    details = rejected.json()["detail"]
    assert isinstance(details, list)
    assert {item["type"] for item in details} == {"string_type", "extra_forbidden"}
    assert all(item["msg_key"] in catalog() and item["msg_params"] == {} for item in details)
    assert "hidden-secret" not in rejected.text
    assert all("input" not in item and "ctx" not in item for item in details)


def test_existing_file_failure_keeps_nested_localizable_cause(message_client: tuple) -> None:
    client, path = message_client
    missing = path.with_name("missing.db")
    response = client.post("/api/connections", json={"db_path": str(missing), "require_existing": True})
    body = response.json()
    assert response.status_code == 400 and not missing.exists()
    assert body["detail"].startswith("connection failed:")
    assert body["detail_key"] == "backend.api.connection_failed"
    cause = body["detail_params"]["p1"]
    assert cause["message_key"].startswith("backend.sqlite_target.")
    assert "已有的 SQLite" in cause["message"]


@pytest.mark.parametrize("identifier", ["missing", "missing'quote", "missing\\path"])
def test_missing_connection_preserves_key_error_raw_repr_and_descriptor(message_client: tuple, identifier: str) -> None:
    client, _ = message_client
    response = client.get(f"/api/connections/{quote(identifier, safe='')}/tables")
    body = response.json()
    assert response.status_code == 404
    assert body["detail"] == str(KeyError(f"unknown connection: {identifier}"))
    assert body["detail_key"] == "backend.state.unknown_connection"
    assert body["detail_params"] == {"p1": identifier}


def test_language_headers_do_not_change_schema_hash_config_or_user_data(message_client: tuple) -> None:
    client, path = message_client
    created = client.post("/api/connections", json={"db_path": str(path), "provider": "base", "locale": "en_US"})
    identifier = created.json()["conn_id"]
    route = f"/api/workbench/connections/{identifier}/schema"
    english = client.get(route, headers={"Accept-Language": "en"}).json()
    chinese = client.get(route, headers={"Accept-Language": "zh-CN"}).json()
    assert english == chinese
    document = {"provider": "base", "locale": "zh_CN", "tables": []}
    payload = {"conn_id": identifier, "schema_hash": english["schema_hash"], "document": document}
    first = client.post("/api/workbench/check", json=payload, headers={"Accept-Language": "en"}).json()
    second = client.post("/api/workbench/check", json=payload, headers={"Accept-Language": "zh-CN"}).json()
    assert first == second and first["issues"][0]["message_key"] == _EMPTY_PLAN
    assert document["locale"] == "zh_CN"
    data = client.get(f"/api/workbench/connections/{identifier}/tables/records/data").json()
    assert data["rows"][0]["message"] == "用户内容"
    assert data["rows"][0]["message_key"] == _EMPTY_PLAN
    assert data["rows"][0]["message_params"] == '{"p1":"user input"}'


def test_descriptors_redact_parameters_and_preserve_nested_composition() -> None:
    inner = message(
        "backend.workbench_runtime.cannot_parse_yaml_json", p1="postgresql://user:hidden@host/db?password=secret"
    )
    joined = message_list([message(_EMPTY_PLAN), inner], "；")
    payload = materialize_messages({"message": public_error(ValueError(joined)), "errors": [inner, "driver output"]})
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "hidden" not in encoded and "secret" not in encoded
    assert payload["message_key"] == "backend.message_list"
    assert payload["message_params"]["separator"] == "；"
    assert payload["message_params"]["items"][0]["message_key"] == _EMPTY_PLAN
    assert payload["errors_i18n"][0]["key"] == inner.key
    assert payload["errors_i18n"][1] is None
    assert materialize_messages(deepcopy({"message": joined})) == materialize_messages({"message": joined})
    raw = {"message": "用户内容", "message_key": _EMPTY_PLAN, "message_params": {"unchanged": True}}
    assert materialize_messages(raw) == raw


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("scalar", [False, True])
def test_actual_ai_delivery_preserves_phase_and_failure_descriptors(stream: bool, scalar: bool) -> None:
    app = create_app()
    router = APIRouter(route_class=MessageRoute)

    def run(progress: Callable[[str, str], None], cancelled: Callable[[], None]) -> dict[str, Any]:
        progress("context", message(_CONTEXT))
        cancelled()
        failure = message(_AI_FAILURE, p1=503)
        raise HTTPException(502, detail=failure if scalar else {"code": "ai_service_unavailable", "message": failure})

    @router.post("/api/message-stream", response_model=None)
    async def stream_route(request: Request) -> dict[str, Any] | Response:
        return await analysis_response("i18n-test", run, request)

    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/message-stream", headers={"Accept": "application/x-ndjson"} if stream else {})
    if stream:
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["stage"] == "context" and events[0]["message_key"] == _CONTEXT
        failure = events[-1]
        assert failure["type"] == "error"
    else:
        assert response.status_code == 502
        failure = response.json()["detail"]
    assert failure["message_key"] == _AI_FAILURE
    assert failure["message_params"] == {"p1": 503}
    assert "503" in failure["message"]


def test_private_ipc_retains_task_output_and_error_descriptors() -> None:
    first, second = multiprocessing.Pipe()
    left, right = ControlChannel(first), ControlChannel(second)

    def handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "failure":
            raise HTTPException(409, detail={"code": "busy", "message": message(_EMPTY_PLAN)})
        if method == "scalar_failure":
            raise HTTPException(409, detail=message(_EMPTY_PLAN))
        if method == "nested_failure":
            cause = message_list([message(_EMPTY_PLAN), message(_CONTEXT)], "；")
            raise HTTPException(400, detail=legacy_message("backend.api.connection_failed", p1=cause))
        if method == "quoted_failure":
            cause = legacy_message("backend.state.unknown_connection", p1="missing'path\\name\n")
            raise HTTPException(404, detail=public_error(KeyError(cause)))
        return {"message": message(_EMPTY_PLAN), "output": [message(_CONTEXT), "pip output"]}

    left.start(handle)
    right.start(handle)
    try:
        result = right.call("task", {})
        assert result["message_key"] == _EMPTY_PLAN
        assert result["output_i18n"] == [{"key": _CONTEXT, "params": {}}, None]
        with pytest.raises(ControlError) as error:
            right.call("failure", {})
        assert error.value.detail["message_key"] == _EMPTY_PLAN
        with pytest.raises(ControlError) as scalar:
            right.call("scalar_failure", {})
        assert materialize_messages({"detail": scalar.value.detail})["detail_key"] == _EMPTY_PLAN
        with pytest.raises(ControlError) as nested:
            right.call("nested_failure", {})
        nested_wire = materialize_messages({"detail": nested.value.detail})
        assert nested_wire["detail"].startswith("connection failed:")
        assert nested_wire["detail_params"]["p1"]["message_params"]["items"][1]["message_key"] == _CONTEXT
        with pytest.raises(ControlError) as quoted:
            right.call("quoted_failure", {})
        quoted_wire = materialize_messages({"detail": quoted.value.detail})
        assert quoted.value.status_code == 404
        assert quoted_wire["detail"] == str(KeyError("unknown connection: missing'path\\name\n"))
        assert quoted_wire["detail_key"] == "backend.state.unknown_connection"
        assert quoted_wire["detail_params"] == {"p1": "missing'path\\name\n"}
        assert materialize_messages(deepcopy({"detail": quoted.value.detail})) == quoted_wire
    finally:
        left.close()
        right.close()


def test_run_feedback_survives_reopen_and_clearing_discards_stale_descriptors(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    store = WorkspaceStore(path)
    run = store.create_run(run_payload())
    stored = store.update_run(
        run["id"], {"status": "error", "error": message(_EMPTY_PLAN), "errors": [message(_EMPTY_PLAN)]}
    )
    reopened = WorkspaceStore(path).get_run(run["id"])
    assert reopened == stored
    assert reopened["error_key"] == _EMPTY_PLAN
    assert reopened["errors_i18n"] == [{"key": _EMPTY_PLAN, "params": {}}]
    cleared = store.update_run(run["id"], {"error": None, "errors": []})
    assert "error_key" not in cleared and "error_params" not in cleared and "errors_i18n" not in cleared
    assert cleared["document"] == run["document"]


def test_invalid_cyclic_workspace_value_keeps_validation_failure_and_writes_nothing(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    view: dict[str, Any] = {}
    view["cycle"] = view
    with pytest.raises(ValueError, match="valid JSON values"):
        store.save_draft(draft_payload(view_state=view))
    assert store.list_drafts() == []


def test_catalog_languages_have_matching_placeholders_and_are_bundled(message_client: tuple) -> None:
    client, _ = message_client
    response = client.get("/static/i18n/backend-messages.json")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
    assert response.json() == catalog()
    for key, pair in catalog().items():
        assert key.startswith("backend.") and len(pair) == 2 and all(pair)
        placeholders = [{field for _, field, _, _ in Formatter().parse(template) if field} for template in pair]
        assert placeholders[0] == placeholders[1], key
    assert isinstance(message(_EMPTY_PLAN), Message)


def test_unavailable_component_management_and_installer_instructions_have_descriptors(message_client: tuple) -> None:
    from sqlseed_web.settings_environment import _Installer

    client, _ = message_client
    result = client.get("/api/settings/plugins/management")
    assert result.status_code == 200
    status = result.json()
    assert not status["available"] and status["reason_key"] in catalog()
    assert "外部" in status["reason"]
    installer = _Installer("pip", "C:\\Isolated Env\\python.exe", None, "powershell")
    commands = installer.commands("install", "sqlseed-ai>=0.2.4.dev0")
    wire = materialize_messages({"commands": commands})["commands"]
    assert all(item["label_key"] in catalog() and item["note_key"] in catalog() for item in wire)
    assert [item["command"] for item in wire] == [item["command"] for item in commands]
