"""Schema-only AI suggestions preserve database and executable boundaries."""

from __future__ import annotations

import importlib
import json
import sqlite3
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlseed_web import workbench_ai
from sqlseed_web.state import UIState
from sqlseed_web.workbench_schema import inspect_connection

ORIGINAL_CALL_MODEL = workbench_ai._call_model


@pytest.fixture()
def ai_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, UIState, dict[str, Any]]]:
    try:
        metadata.version("sqlseed-ai")
    except metadata.PackageNotFoundError:
        pytest.skip("AI business regression requires the optional sqlseed-ai distribution")
    # Installed-but-broken imports should fail visibly, not become a missing-plugin skip.
    importlib.import_module("sqlseed_ai.config")
    path = tmp_path / "private-target.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE);"
            "CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), amount REAL NOT NULL, doubled REAL);"
            "INSERT INTO users(email) VALUES ('private-person@example.test');"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    monkeypatch.setattr(workbench_ai, "state", registry)
    monkeypatch.setattr(workbench_ai, "_call_model", lambda messages, **kwargs: {"suggestions": []})
    payload = {
        "conn_id": conn.conn_id,
        "schema_hash": inspect_connection(conn)["schema_hash"],
        "tables": ["orders"],
        "document": {
            "provider": "base",
            "locale": "zh_CN",
            "tables": [
                {
                    "name": "orders",
                    "count": 100,
                    "columns": [
                        {"name": "amount", "generator": "float", "params": {"min_value": 1, "max_value": 5}},
                        {"name": "doubled", "derive_from": "amount", "expression": "value * 2"},
                    ],
                }
            ],
        },
    }
    app = FastAPI()
    app.include_router(workbench_ai.router)
    with TestClient(app) as client:
        yield client, registry, payload
    registry.close_connection(conn.conn_id)


def test_schema_only_context_and_reviewed_patch(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, registry, payload = ai_client
    captured = []

    def reply(messages: Any, **kwargs: Any) -> dict[str, Any]:
        captured.extend(messages)
        return {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "amount",
                    "generator": "float",
                    "params": {"min_value": 10, "max_value": 100},
                    "reason": "金额应使用合理的小数范围",
                }
            ]
        }

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    result = client.post("/api/workbench/ai/suggest", json=payload)
    assert result.status_code == 200, result.text
    suggestion = result.json()["suggestions"][0]
    assert suggestion["after"]["params"]["min_value"] == 10
    assert suggestion["before"]["params"]["min_value"] == 1
    assert suggestion["reason"] == "金额应使用合理的小数范围"
    prompt = json.dumps(captured)
    assert "private-person" not in prompt and "private-target" not in prompt
    assert "row_count" not in prompt and "_ref_values" not in prompt
    assert "users" in prompt and "foreign_keys" in prompt
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("orders") == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"table": "unknown", "column": "amount", "generator": "float"},
        {"table": "orders", "column": "gone", "generator": "string"},
        {"table": "orders", "column": "user_id", "generator": "integer"},
        {"table": "orders", "column": "id", "generator": "integer"},
        {"table": "orders", "column": "doubled", "generator": "float"},
        {"table": "orders", "column": "amount", "generator": "fake_generator"},
        {"table": "orders", "column": "amount", "generator": "float", "params": {"_ref_values": [10]}},
        {"table": "orders", "column": "amount", "generator": "integer", "params": {"min_value": "oops"}},
        {"table": "orders", "column": "amount", "generator": "float", "expression": "value"},
        {"table": "orders", "column": "amount", "generator": "float", "faker_method": "anything"},
    ],
)
def test_model_output_cannot_escape_column_contract(ai_client: Any, monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    client, _, payload = ai_client
    monkeypatch.setattr(workbench_ai, "_call_model", lambda messages, **kwargs: {"suggestions": [bad]})
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert response.json()["rejected"]


def test_schema_changes_before_or_during_analysis_reject(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, registry, payload = ai_client
    assert client.post("/api/workbench/ai/suggest", json={**payload, "schema_hash": "old"}).status_code == 409

    def change_schema(messages: Any, **kwargs: Any) -> dict[str, Any]:
        with sqlite3.connect(registry.get_connection(payload["conn_id"]).target) as db:
            db.execute("ALTER TABLE orders ADD COLUMN note TEXT")
        return {"suggestions": []}

    monkeypatch.setattr(workbench_ai, "_call_model", change_schema)
    assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 409


def test_untrusted_response_and_failure_do_not_echo_model_or_secrets(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = ai_client
    monkeypatch.setattr(workbench_ai, "_call_model", lambda messages, **kwargs: {"suggestions": "private-secret"})
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 502 and "private-secret" not in response.text

    def fail(messages: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("API key private-secret")

    monkeypatch.setattr(workbench_ai, "_call_model", fail)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 502 and "private-secret" not in response.text


def test_ai_config_never_echoes_key_and_blank_preserves_it(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("sqlseed_ai")
    client, registry, _ = ai_client
    for name in (
        "SQLSEED_AI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "SQLSEED_AI_BASE_URL",
        "OPENAI_BASE_URL",
        "SQLSEED_AI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "openai_compat")
    assert client.get("/api/workbench/ai/config").json()["ready"] is False
    configured = client.post(
        "/api/workbench/ai/config",
        json={
            "backend": "openai_compat",
            "model": "test-model",
            "base_url": "https://example.test/v1",
            "api_key": "private-key",
        },
    )
    assert configured.status_code == 200 and configured.json()["ready"]
    assert "private-key" not in configured.text
    response = client.post(
        "/api/workbench/ai/config",
        json={"backend": "openai_compat", "model": "next-model", "base_url": "https://example.test/v1", "api_key": ""},
    )
    assert response.json()["ready"] and registry.get_ai_override()["api_key"] == "private-key"
    assert "private-key" not in client.get("/api/workbench/ai/config").text
    assert client.post("/api/workbench/ai/config", json={"backend": "invalid"}).status_code == 422


def test_missing_plugin_is_optional(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = ai_client

    def missing() -> Any:
        raise ImportError("not installed")

    monkeypatch.setattr(workbench_ai, "_effective_config", missing)
    result = client.get("/api/workbench/ai/config")
    assert result.status_code == 200
    assert result.json()["available"] is False


def test_connectivity_uses_models_endpoint_without_exposing_secret(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlseed_ai")
    import httpx

    client, registry, _ = ai_client
    registry.set_ai_override(
        {
            "backend": "openai_compat",
            "base_url": "https://ai.example.test/v1",
            "model": "demo",
            "api_key": "private-probe-key",
        }
    )
    captured = []

    def probe(url: str, **kwargs: Any) -> httpx.Response:
        captured.append((url, kwargs))
        return httpx.Response(200, json={"data": [{"id": "demo"}]})

    monkeypatch.setattr(httpx, "get", probe)
    result = client.post("/api/workbench/ai/test")
    assert result.json()["models"] == ["demo"]
    assert captured[0][0] == "https://ai.example.test/v1/models"
    assert captured[0][1]["headers"]["Authorization"] == "Bearer private-probe-key"
    assert "private-probe-key" not in result.text


def test_connection_target_cannot_be_forwarded_and_scope_is_validated(ai_client: Any) -> None:
    client, _, payload = ai_client
    result = client.post(
        "/api/workbench/ai/suggest", json={**payload, "document": {**payload["document"], "url": "postgresql://secret"}}
    )
    assert result.status_code == 422
    assert client.post("/api/workbench/ai/suggest", json={**payload, "tables": ["gone"]}).status_code == 422
    assert client.post("/api/workbench/ai/suggest", json={**payload, "tables": []}).status_code == 422


def test_disconnect_during_analysis_cannot_produce_applicable_suggestions(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = ai_client

    def remove(messages: Any, **kwargs: Any) -> dict[str, Any]:
        registry.close_connection(payload["conn_id"])
        return {"suggestions": []}

    monkeypatch.setattr(workbench_ai, "_call_model", remove)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "generator,params",
    [
        ("date", {"start_date": "yesterday"}),
        ("datetime", {"start_time": "not-a-time"}),
        ("date", {"start_date": "2026-09-10", "end_date": "2026-09-01"}),
        ("date", {"weekdays": "sometimes"}),
        ("choice", {"choices": []}),
        ("integer", {"min_value": 10, "max_value": 1}),
    ],
)
def test_invalid_semantic_parameters_are_not_presented_as_suggestions(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, generator: str, params: dict[str, Any]
) -> None:
    client, _, payload = ai_client
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [{"table": "orders", "column": "amount", "generator": generator, "params": params}]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert not response.json()["suggestions"]


@pytest.mark.parametrize("explicit", [False, True])
def test_default_with_active_generator_is_ai_editable(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN balance REAL NOT NULL DEFAULT 0 CHECK(balance >= 0)")
        db.execute("ALTER TABLE orders ADD COLUMN reserved REAL NOT NULL DEFAULT 0")
    payload["schema_hash"] = inspect_connection(conn)["schema_hash"]
    if explicit:
        payload["document"]["tables"][0]["columns"].append(
            {"name": "balance", "generator": "float", "params": {"min_value": 0, "max_value": 999999}}
        )
    captured = []

    def reply(messages: Any, **kwargs: Any) -> Any:
        captured.extend(messages)
        return {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "balance",
                    "generator": "float",
                    "params": {"min_value": 0, "max_value": 10000},
                }
            ]
        }

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert [patch["column"] for patch in result["suggestions"]] == ["balance"]
    prompt = json.loads(captured[1]["content"])
    assert "balance" in prompt["relation_source_columns"]["orders"]
    assert "reserved" not in prompt["relation_source_columns"]["orders"]
    assert conn.orchestrator.get_row_count("orders") == 0


def test_custom_mapping_that_uses_default_stays_protected(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN balance REAL NOT NULL DEFAULT 0")
    payload["schema_hash"] = inspect_connection(conn)["schema_hash"]
    payload["document"]["custom_column_mappings"] = {"exact": {"balance": {"generator": "skip"}}}
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda _, **kwargs: {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "balance",
                    "generator": "float",
                    "params": {"min_value": 0, "max_value": 10},
                }
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []


@pytest.mark.parametrize("generator", ["skip", "float"])
def test_default_eligibility_resolves_custom_mappings_without_ai_or_record_data(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, generator: str
) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN reserved REAL NOT NULL DEFAULT 0")
    payload["schema_hash"] = inspect_connection(conn)["schema_hash"]
    payload["document"]["custom_column_mappings"] = {"exact": {"reserved": {"generator": generator}}}
    monkeypatch.setattr(
        workbench_ai, "_call_model", lambda _, **kwargs: pytest.fail("Eligibility must not call the model")
    )
    response = client.post(
        "/api/workbench/ai/eligibility",
        json={key: payload[key] for key in ("conn_id", "schema_hash", "document")},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "schema_hash": payload["schema_hash"],
        "default_modes": {"orders": {"reserved": generator}},
    }
    assert conn.orchestrator.get_row_count("orders") == 0


def test_default_eligibility_preserves_unselected_draft_override(ai_client: Any) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN reserved REAL NOT NULL DEFAULT 0")
    table = payload["document"]["tables"].pop()
    table["columns"].append({"name": "reserved", "generator": "float", "params": {"min_value": 1, "max_value": 2}})
    payload["document"]["custom_column_mappings"] = {"exact": {"reserved": {"generator": "skip"}}}
    response = client.post(
        "/api/workbench/ai/eligibility",
        json={
            "conn_id": payload["conn_id"],
            "schema_hash": inspect_connection(conn)["schema_hash"],
            "document": payload["document"],
            "table_drafts": [table],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["default_modes"]["orders"]["reserved"] == "float"


def test_default_eligibility_resolves_enrichment_without_exposing_its_values(ai_client: Any) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN reserved TEXT NOT NULL DEFAULT 'pending'")
        db.executemany("INSERT INTO orders(amount, reserved) VALUES (?, ?)", [(1, "private-enrichment-value")] * 30)
    payload["document"]["tables"][0]["enrich"] = True
    response = client.post(
        "/api/workbench/ai/eligibility",
        json={
            "conn_id": payload["conn_id"],
            "schema_hash": inspect_connection(conn)["schema_hash"],
            "document": payload["document"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["default_modes"]["orders"]["reserved"] == "choice"
    assert "private-enrichment-value" not in response.text
    assert conn.orchestrator.get_row_count("orders") == 30


def test_suggestion_stream_reports_actual_stages_and_keeps_database_readonly(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = ai_client
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "amount",
                    "generator": "float",
                    "params": {"min_value": 10, "max_value": 100},
                }
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload, headers={"Accept": "application/x-ndjson"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["stage"] for event in events if event["type"] == "progress"] == [
        "context",
        "model",
        "validation",
        "preview",
    ]
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["suggestions"][0]["after"]["params"]["min_value"] == 10
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("orders") == 0


def test_candidate_failure_exposes_unique_domain_issue(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, payload = ai_client
    payload["tables"] = ["users"]
    payload["document"]["tables"] = [{"name": "users", "count": 100, "columns": []}]
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [
                {
                    "table": "users",
                    "column": "email",
                    "generator": "choice",
                    "params": {"choices": ["synthetic@example.test"]},
                }
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    validation = response.json()["validation"]
    issue = next(issue for issue in validation["issues"] if issue["code"] == "unique_domain_exhausted")
    assert issue["table"] == "users" and issue["column"] == "email"
    assert "100" in issue["message"] and "1" in issue["message"]
    assert response.json()["suggestions"] == []


def test_prompt_explains_real_pattern_template_and_base_phone_semantics(ai_client: Any) -> None:
    _, registry, payload = ai_client
    schema = inspect_connection(registry.get_connection(payload["conn_id"]))
    column = payload["document"]["tables"][0]["columns"][0]
    column["constraints"] = {"min_value": 1, "max_value": 5, "regex": "[0-9]+"}
    column["params"]["values"] = ["private-record"]
    column["params"]["path"] = "/private-file.csv"
    messages = workbench_ai._messages(schema, payload["tables"], payload["document"], workbench_ai.generator_catalog())
    context = json.loads(messages[1]["content"])
    entries = {entry["id"]: entry for entry in context["generators"]}
    assert "ORD-[0-9]{8}" in json.dumps(entries["pattern"])
    assert "{random_digits:11}" in json.dumps(entries["template"])
    assert "mask" in context["provider_guidance"] and "base" in context["provider_guidance"].lower()
    assert context["existing_constraints"] == [
        {"table": "orders", "column": "amount", "constraints": column["constraints"]}
    ]
    assert "private-record" not in json.dumps(messages) and "private-file" not in json.dumps(messages)


@pytest.mark.parametrize("params", [{}, {"pattern": ""}, {"pattern": None, "regex": None}, {"pattern": "["}])
def test_ai_pattern_requires_an_effective_valid_regular_expression(params: Any) -> None:
    entry = next(entry for entry in workbench_ai.generator_catalog()["entries"] if entry["id"] == "pattern")
    with pytest.raises(ValueError, match="正则"):
        workbench_ai._validate_params(params, entry)


def test_candidate_check_failure_identifies_column_without_sample_value(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("ALTER TABLE orders ADD COLUMN phone TEXT CHECK(length(phone) BETWEEN 11 AND 11)")
    payload["schema_hash"] = inspect_connection(conn)["schema_hash"]
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [
                {"table": "orders", "column": "phone", "generator": "phone", "params": {"mask": "##########"}}
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    validation = response.json()["validation"]
    issue = next(issue for issue in validation["issues"] if issue["code"] == "sample_check_failed")
    assert issue["table"] == "orders" and issue["column"] == "phone"
    assert "11" in issue["message"] and "长度" in issue["message"]
    assert "000-0000-0001" not in response.text


def test_ai_gate_covers_json_and_stream_without_holding_database_lease(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client, registry, payload = ai_client
    entered, release = Event(), Event()

    def reply(messages: Any, **kwargs: Any) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return {"suggestions": []}

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/api/workbench/ai/suggest", json=payload)
        try:
            assert entered.wait(3)
            with registry.connection_operation(payload["conn_id"]) as conn:
                assert conn.orchestrator.get_row_count("users") == 1
            second = client.post("/api/workbench/ai/suggest", json=payload, headers={"Accept": "application/x-ndjson"})
            assert second.status_code == 409, second.text
            assert second.json()["detail"]["code"] == "ai_busy"
        finally:
            release.set()
        assert first.result(3).status_code == 200
    assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 200


@pytest.mark.parametrize("stream", [False, True])
def test_model_failure_is_safe_and_has_actionable_error_code(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    client, _, payload = ai_client

    def fail(messages: Any, **kwargs: Any) -> dict[str, Any]:
        raise TimeoutError("private-key-and-provider-request")

    monkeypatch.setattr(workbench_ai, "_call_model", fail)
    response = client.post(
        "/api/workbench/ai/suggest", json=payload, headers={"Accept": "application/x-ndjson"} if stream else {}
    )
    if stream:
        assert response.status_code == 200
        error = json.loads(response.text.splitlines()[-1])
        assert error["type"] == "error"
    else:
        assert response.status_code == 504
        error = response.json()["detail"]
    assert error["code"] == "ai_model_timeout"
    assert "超时" in error["message"] and "private-key" not in response.text


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
def test_disconnect_stops_post_model_work_but_keeps_gate_until_worker_exits(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, spec_version: str
) -> None:
    import asyncio
    from threading import Event

    from sqlseed_web import workbench_ai_stream

    client, registry, payload = ai_client
    entered, release = Event(), Event()
    operations: list[Any] = []
    original = workbench_ai_stream.AnalysisOperation

    def record_operation(*args: Any) -> Any:
        operation = original(*args)
        operations.append(operation)
        return operation

    def reply(messages: Any, **kwargs: Any) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "amount",
                    "generator": "float",
                    "params": {"min_value": 10, "max_value": 100},
                }
            ]
        }

    monkeypatch.setattr(workbench_ai_stream, "AnalysisOperation", record_operation)
    monkeypatch.setattr(workbench_ai, "_call_model", reply)

    async def disconnect_request() -> list[dict[str, Any]]:
        disconnect = asyncio.Event()
        received = False
        events: list[dict[str, Any]] = []
        body = json.dumps(payload).encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec_version},
            "method": "POST",
            "path": "/api/workbench/ai/suggest",
            "raw_path": b"/api/workbench/ai/suggest",
            "query_string": b"",
            "scheme": "http",
            "http_version": "1.1",
            "headers": [(b"content-type", b"application/json"), (b"accept", b"application/x-ndjson")],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }

        async def receive() -> dict[str, Any]:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                events.extend(json.loads(line) for line in message["body"].decode().splitlines())
                if any(event.get("stage") == "model" for event in events):
                    assert await asyncio.to_thread(entered.wait, 2)
                    disconnect.set()

        await asyncio.wait_for(client.app(scope, receive, send), 1)
        return events

    try:
        events = asyncio.run(disconnect_request())
        assert operations[0].cancelled.is_set()
        response = client.post("/api/workbench/ai/suggest", json=payload)
        assert response.status_code == 409
        assert not any(event.get("stage") in {"validation", "preview"} for event in events)
    finally:
        release.set()
        if operations:
            operations[0].thread.join(3)
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("orders") == 0
    assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 200


def test_stream_deadline_reports_timeout_keeps_gate_and_skips_preview(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from sqlseed_web import workbench_ai_stream

    client, registry, payload = ai_client
    entered, release = Event(), Event()
    operations: list[Any] = []
    original = workbench_ai_stream.AnalysisOperation

    def record_operation(*args: Any) -> Any:
        operation = original(*args)
        operations.append(operation)
        return operation

    def reply(messages: Any, **kwargs: Any) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "amount",
                    "generator": "float",
                    "params": {"min_value": 10, "max_value": 100},
                }
            ]
        }

    monkeypatch.setattr(workbench_ai_stream, "AnalysisOperation", record_operation)
    monkeypatch.setattr(workbench_ai_stream, "ANALYSIS_TIMEOUT", 0.3)
    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    try:
        response = client.post("/api/workbench/ai/suggest", json=payload, headers={"Accept": "application/x-ndjson"})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert entered.is_set()
        assert events[-1]["type"] == "error" and events[-1]["code"] == "ai_timeout"
        assert operations[0].cancelled.is_set()
        assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 409
    finally:
        release.set()
        if operations:
            operations[0].thread.join(3)
    assert not any(event.get("stage") == "preview" for event in list(operations[0].queue.queue))
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("orders") == 0
    assert client.post("/api/workbench/ai/suggest", json=payload).status_code == 200


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "ai_model_not_found"),
        (400, "ai_request_rejected"),
        (422, "ai_request_rejected"),
        (503, "ai_service_unavailable"),
    ],
)
def test_model_http_errors_are_specific_without_response_content(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    client, _, payload = ai_client

    class ServiceFailure(Exception):
        status_code = status

    def fail(messages: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            raise ServiceFailure("secret-provider-response")
        except ServiceFailure as exc:
            raise RuntimeError("outer sensitive request") from exc

    monkeypatch.setattr(workbench_ai, "_call_model", fail)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == code
    assert "secret-provider" not in response.text and "sensitive" not in response.text


def test_analysis_pins_service_configuration_before_context_work(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig

    client, _, payload = ai_client
    config = AIConfig(
        backend=AIBackend.OPENAI_COMPAT,
        model="first-model",
        base_url="https://first.test/v1",
        api_key="first-private-key",
    )
    captured: list[Any] = []
    original_schema = workbench_ai._analysis_schema

    def change_settings(conn: Any, body: Any, names: Any = None) -> Any:
        config.model = "second-model"
        config.base_url = "https://second.test/v1"
        config.api_key = "second-private-key"
        return original_schema(conn, body, names)

    def reply(analyzer: Any, messages: Any, **kwargs: Any) -> dict[str, Any]:
        captured.append(analyzer.config)
        return {"suggestions": []}

    monkeypatch.setattr(workbench_ai, "_effective_config", lambda: config)
    monkeypatch.setattr(workbench_ai, "_analysis_schema", change_settings)
    monkeypatch.setattr(workbench_ai, "_call_model", ORIGINAL_CALL_MODEL)
    monkeypatch.setattr(SchemaAnalyzer, "call_llm", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert captured[0].model == "first-model"
    assert captured[0].base_url == "https://first.test/v1"
    assert captured[0].api_key == "first-private-key"
    assert "private-key" not in response.text


def test_rejected_rule_identifies_known_field_and_safe_parameter_reason(
    ai_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = ai_client
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [
                {
                    "table": "orders",
                    "column": "amount",
                    "generator": "pattern",
                    "params": {"pattern": "[private-model-fragment"},
                },
                {"table": "invented-secret-table", "column": "private-column", "generator": "fake-private-generator"},
                {"table": "orders", "column": "id", "generator": "integer"},
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    rejected = response.json()["rejected"]
    assert "orders.amount" in rejected[0] and "正则表达式无效" in rejected[0]
    assert "orders.id" in rejected[2] and "保持原规则" in rejected[2]
    assert "private-" not in response.text and "secret-table" not in response.text


def test_ai_sample_budget_allows_three_rows_of_a_wide_table(ai_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, registry, payload = ai_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite3.connect(conn.target) as db:
        db.execute("CREATE TABLE wide(" + ",".join(f"field_{index} INTEGER NOT NULL" for index in range(200)) + ")")
    payload.update(schema_hash=inspect_connection(conn)["schema_hash"], tables=["wide"])
    payload["document"]["tables"] = [
        {
            "name": "wide",
            "count": 3,
            "columns": [
                {"name": f"field_{index}", "generator": "integer", "params": {"min_value": 1, "max_value": 10}}
                for index in range(200)
            ],
        }
    ]
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda messages, **kwargs: {
            "suggestions": [
                {
                    "table": "wide",
                    "column": "field_0",
                    "generator": "integer",
                    "params": {"min_value": 20, "max_value": 30},
                }
            ]
        },
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["validation"]["ok"], response.text
    assert response.json()["suggestions"][0]["after"]["params"] == {"min_value": 20, "max_value": 30}
    assert conn.orchestrator.get_row_count("wide") == 0
