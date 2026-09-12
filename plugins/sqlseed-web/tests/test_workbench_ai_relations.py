"""AI scopes and finite relation templates use the real SQLite/core validators."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from datetime import date
from importlib import metadata
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlseed.core.expression import ExpressionEngine
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import workbench_ai
from sqlseed_web.state import UIState
from sqlseed_web.workbench_schema import inspect_connection

from .workbench_test_helpers import generator_suggestion, suggestion_response


@pytest.fixture(name="relation_client")
def fixture_relation_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    try:
        metadata.version("sqlseed-ai")
    except metadata.PackageNotFoundError:
        pytest.skip("AI relation regression requires the optional sqlseed-ai distribution")
    importlib.import_module("sqlseed_ai.config")
    path = tmp_path / "relations.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE invoices(id INTEGER PRIMARY KEY AUTOINCREMENT, quantity INTEGER NOT NULL, "
            "price REAL NOT NULL, total REAL NOT NULL CHECK(total >= 0), alias TEXT, first TEXT NOT NULL, "
            "last TEXT NOT NULL, fullname TEXT NOT NULL, started DATE NOT NULL, finished DATE);"
            "CREATE TABLE notes(id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT);"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    monkeypatch.setattr(workbench_ai, "state", registry)
    app = FastAPI()
    app.include_router(workbench_ai.router)
    table = {
        "name": "invoices",
        "count": 5,
        "columns": [
            {"name": "quantity", "generator": "integer", "params": {"min_value": 2, "max_value": 2}},
            {"name": "price", "generator": "float", "params": {"min_value": 3, "max_value": 3}},
            {"name": "total", "generator": "float", "params": {"min_value": 1, "max_value": 1}},
            {"name": "first", "generator": "choice", "params": {"choices": ["小明"]}},
            {"name": "last", "generator": "choice", "params": {"choices": ["王"]}},
            {"name": "fullname", "generator": "string", "params": {}},
            {"name": "started", "generator": "date", "params": {"start_date": "2026-01-01", "end_date": "2026-01-01"}},
        ],
    }
    payload = {
        "conn_id": conn.conn_id,
        "schema_hash": inspect_connection(conn)["schema_hash"],
        "tables": ["invoices"],
        "document": {"provider": "base", "locale": "zh_CN", "tables": [table]},
    }
    with TestClient(app) as client:
        yield client, registry, payload
    registry.close_connection(conn.conn_id)


def relation(
    column: str = "total", template: str = "product", sources: list[str] | None = None, **options: Any
) -> dict[str, Any]:
    return {
        "kind": "relation",
        "table": "invoices",
        "column": column,
        "template": template,
        "sources": sources or ["quantity", "price"],
        "options": options,
        "reason": "金额等于同一行数量乘单价",
    }


@pytest.fixture(name="null_target_client")
def fixture_null_target_client(relation_client: Any) -> Any:
    client, registry, payload = relation_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite_connection(conn.target) as db:
        db.execute(
            "CREATE TABLE amounts(quantity INTEGER NOT NULL, price REAL NOT NULL, total REAL, "
            "default_total REAL DEFAULT 0, null_default_total REAL DEFAULT NULL, replacement REAL)"
        )
    payload.update(
        schema_hash=inspect_connection(conn)["schema_hash"],
        tables=["amounts"],
        allowed_targets=[{"table": "amounts", "columns": ["total"]}],
        document={
            "provider": "base",
            "tables": [
                {
                    "name": "amounts",
                    "count": 3,
                    "columns": [
                        {"name": "quantity", "generator": "integer", "params": {"min_value": 2, "max_value": 2}},
                        {"name": "price", "generator": "float", "params": {"min_value": 3, "max_value": 3}},
                        {"name": "total", "generator": "skip"},
                        {"name": "default_total", "generator": "skip"},
                        {"name": "null_default_total", "generator": "skip"},
                        {"name": "replacement", "generator": "float", "params": {"min_value": 1, "max_value": 1}},
                    ],
                }
            ],
        },
    )
    return client, registry, payload


def test_explicit_null_target_accepts_reviewable_product_without_writing(
    null_target_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = null_target_client
    before = deepcopy(payload)
    monkeypatch.setattr(
        workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": [{**relation(), "table": "amounts"}]}
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rejected"] == []
    assert [patch["column"] for patch in result["suggestions"]] == ["total"]
    patch = result["suggestions"][0]
    assert patch["before"]["generator"] == "skip"
    assert patch["after"]["derive_from"] == ["quantity", "price"]
    assert patch["evidence"]["rows"][0] == {"quantity": 2, "price": 3.0, "total": 6.0}
    assert result["validation"]["ok"] is True
    assert payload == before
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("amounts") == 0


@pytest.mark.parametrize("column", ["default_total", "null_default_total"])
def test_real_database_default_targets_remain_protected(
    null_target_client: Any, monkeypatch: pytest.MonkeyPatch, column: str
) -> None:
    client, _, payload = null_target_client
    payload["allowed_targets"][0]["columns"] = [column]
    monkeypatch.setattr(
        workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": [{**relation(column), "table": "amounts"}]}
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert len(response.json()["rejected"]) == 1


def test_derived_default_column_is_a_relation_source_but_remains_a_protected_target(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = relation_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite_connection(conn.target) as db:
        db.execute("ALTER TABLE invoices ADD COLUMN subtotal REAL NOT NULL DEFAULT 0")
    payload["schema_hash"] = inspect_connection(conn)["schema_hash"]
    payload["document"]["tables"][0]["columns"].append(
        {"name": "subtotal", "derive_from": "quantity", "expression": "value * 2"}
    )
    captured = []

    response = suggestion_response(
        client,
        payload,
        monkeypatch,
        [
            relation("total", template="copy", sources=["subtotal"]),
            generator_suggestion("invoices", "subtotal", "float"),
        ],
        messages=captured,
    )
    result = response.json()
    assert [patch["column"] for patch in result["suggestions"]] == ["total"]
    assert result["suggestions"][0]["evidence"]["rows"][0] == {"subtotal": 4, "total": 4}
    assert len(result["rejected"]) == 1
    prompt = json.loads(captured[1]["content"])
    assert "subtotal" in prompt["relation_source_columns"]["invoices"]
    assert any(item["column"] == "subtotal" for item in prompt["protected_rules"])
    assert conn.orchestrator.get_row_count("invoices") == 0


def test_explicit_null_source_stays_unavailable_in_context_and_relation(
    null_target_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = null_target_client
    payload["allowed_targets"][0]["columns"] = ["replacement"]
    captured = []

    def reply(messages: Any, **kwargs: Any) -> Any:
        captured.extend(messages)
        return {"suggestions": [{**relation("replacement", sources=["total", "price"]), "table": "amounts"}]}

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert len(response.json()["rejected"]) == 1
    assert "total" not in json.loads(captured[1]["content"])["relation_source_columns"]["amounts"]


def test_column_targets_keep_full_table_context_and_business_description(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    payload.update(allowed_targets=[{"table": "invoices", "columns": ["total"]}], business_context="订单金额需要相等")
    captured = []

    def reply(messages: Any, **kwargs: Any) -> Any:
        captured.extend(messages)
        return {"suggestions": [relation(), {"table": "invoices", "column": "price", "generator": "integer"}]}

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert [item["column"] for item in response.json()["suggestions"]] == ["total"]
    context = json.loads(captured[1]["content"])
    assert context["allowed_targets"] == [{"table": "invoices", "columns": ["total"]}]
    assert context["business_context"] == "订单金额需要相等"
    assert {col["name"] for col in context["schema"][0]["columns"]} >= {"quantity", "price", "total"}


def test_relation_is_compiled_and_readonly_samples_show_same_row_evidence(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = relation_client
    monkeypatch.setattr(workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": [relation(precision=2)]})
    result = client.post("/api/workbench/ai/suggest", json=payload)
    assert result.status_code == 200, result.text
    patch = result.json()["suggestions"][0]
    assert patch["after"]["derive_from"] == ["quantity", "price"]
    assert patch["after"].get("generator") is None
    assert ExpressionEngine().evaluate(patch["after"]["expression"], {"value": [2, 3]}) == 6
    assert patch["evidence"]["rows"][0] == {"quantity": 2, "price": 3.0, "total": 6.0}
    assert result.json()["validation"]["ok"] is True
    assert registry.get_connection(payload["conn_id"]).orchestrator.get_row_count("invoices") == 0


@pytest.mark.parametrize(
    "suggestion",
    [
        relation(template="arbitrary"),
        relation(expression="value * 10"),
        relation(sources=["missing", "price"]),
        relation(sources=["id", "price"]),
        relation(sources=["first", "price"]),
        relation(precision=99),
        relation("quantity", "copy", ["alias"]),
        relation("fullname", "copy", ["alias"]),
    ],
)
def test_unsupported_relation_and_incompatible_sources_are_rejected(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch, suggestion: Any
) -> None:
    client, _, payload = relation_client
    monkeypatch.setattr(workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": [suggestion]})
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert response.json()["rejected"]


@pytest.mark.parametrize("old", [False, True])
def test_old_and_new_derived_cycles_are_rejected_atomically(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch, old: bool
) -> None:
    client, _, payload = relation_client
    changes = [relation("price", "copy", ["total"])]
    if old:
        payload["document"]["tables"][0]["columns"] = [
            c for c in payload["document"]["tables"][0]["columns"] if c["name"] != "total"
        ] + [{"name": "total", "derive_from": "price", "expression": "value * 2"}]
    else:
        changes.append(relation("total", "copy", ["price"]))
    monkeypatch.setattr(workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": changes})
    result = client.post("/api/workbench/ai/suggest", json=payload).json()
    assert result["suggestions"] == []
    assert result["rejected"]


def test_unselected_draft_advanced_rules_are_preserved_and_locked(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    payload["tables"] = ["notes"]
    payload["table_drafts"] = [
        {
            "name": "notes",
            "count": 77,
            "seed": 91,
            "columns": [{"name": "body", "generator": "string", "faker_method": "word"}],
        }
    ]
    before = deepcopy(payload)
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda _, **kwargs: {"suggestions": [{"table": "notes", "column": "body", "generator": "email"}]},
    )
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert payload == before


def test_related_generator_changes_share_atomic_review_group(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    monkeypatch.setattr(
        workbench_ai,
        "_call_model",
        lambda _, **kwargs: {
            "suggestions": [
                relation(),
                {
                    "table": "invoices",
                    "column": "price",
                    "generator": "float",
                    "params": {"min_value": 9, "max_value": 9},
                },
            ]
        },
    )
    result = client.post("/api/workbench/ai/suggest", json=payload).json()
    patches = result["suggestions"]
    assert len(patches) == 2
    assert patches[0]["group_id"] == patches[1]["group_id"]


def test_compiled_concat_copy_and_date_offset_use_core_expression_engine(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    changes = [
        relation("fullname", "concat", ["last", "first"], separator=""),
        relation("alias", "copy", ["first"]),
        relation("finished", "date_offset", ["started"], days=7),
    ]
    monkeypatch.setattr(workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": changes})
    result = client.post("/api/workbench/ai/suggest", json=payload).json()
    patches = {patch["column"]: patch for patch in result["suggestions"]}
    assert set(patches) == {"fullname", "alias", "finished"}
    engine = ExpressionEngine()
    assert engine.evaluate(patches["fullname"]["after"]["expression"], {"value": ["王", "小明"]}) == "王小明"
    assert engine.evaluate(patches["alias"]["after"]["expression"], {"value": None}) is None
    assert engine.evaluate(patches["finished"]["after"]["expression"], {"value": date(2026, 1, 1)}) == date(2026, 1, 8)


def test_candidate_check_rejects_real_check_constraint_failure(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    for col in payload["document"]["tables"][0]["columns"]:
        if col["name"] == "price":
            col["params"] = {"min_value": -3, "max_value": -3}
    monkeypatch.setattr(workbench_ai, "_call_model", lambda _, **kwargs: {"suggestions": [relation()]})
    result = client.post("/api/workbench/ai/suggest", json=payload).json()
    assert result["suggestions"] == []
    assert result["validation"]["ok"] is False


def test_existing_implicit_row_dependencies_also_group_source_changes_atomically(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    columns = payload["document"]["tables"][0]["columns"]
    columns[:] = [col for col in columns if col["name"] != "total"] + [
        {"name": "total", "derive_from": "price", "expression": "value * row['quantity']"}
    ]
    patches = suggestion_response(
        client,
        payload,
        monkeypatch,
        [
            generator_suggestion("invoices", "quantity", "integer", min_value=2, max_value=2),
            generator_suggestion("invoices", "price", "float", min_value=4, max_value=4),
        ],
    ).json()["suggestions"]
    assert len(patches) == 2
    assert patches[0]["group_id"] == patches[1]["group_id"]


def test_database_cross_column_check_groups_independent_generator_patches(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, registry, payload = relation_client
    conn = registry.get_connection(payload["conn_id"])
    with sqlite_connection(conn.target) as db:
        db.execute(
            "CREATE TABLE ranges(lower_bound INTEGER NOT NULL, upper_bound INTEGER NOT NULL, CHECK(upper_bound >= lower_bound))"
        )
    payload.update(
        schema_hash=inspect_connection(conn)["schema_hash"],
        tables=["ranges"],
        document={"provider": "base", "tables": [{"name": "ranges", "count": 3, "columns": []}]},
    )
    patches = suggestion_response(
        client,
        payload,
        monkeypatch,
        [
            generator_suggestion("ranges", "lower_bound", "integer", min_value=10, max_value=10),
            generator_suggestion("ranges", "upper_bound", "integer", min_value=20, max_value=20),
        ],
    ).json()["suggestions"]
    assert len(patches) == 2
    assert patches[0]["group_id"] == patches[1]["group_id"]


def test_real_gemma_qualified_source_shape_stays_rejected_and_prompt_names_exact_source_format(
    relation_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, payload = relation_client
    messages_seen = []

    def reply(messages: Any, **kwargs: Any) -> Any:
        messages_seen.extend(messages)
        return {"suggestions": [relation(sources=["invoices.quantity", "invoices.price"], precision=2)]}

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200
    assert response.json()["suggestions"] == []
    assert response.json()["rejected"]
    assert "unqualified column names" in messages_seen[0]["content"]
    assert "never table.column" in messages_seen[0]["content"]
    context = json.loads(messages_seen[1]["content"])
    assert context["relation_source_columns"]["invoices"] == [
        "quantity",
        "price",
        "total",
        "alias",
        "first",
        "last",
        "fullname",
        "started",
        "finished",
    ]
