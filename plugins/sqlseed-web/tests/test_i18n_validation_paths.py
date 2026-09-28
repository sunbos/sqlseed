"""Rejected workspace requests preserve messages and real database state."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, workbench, workbench_data
from sqlseed_web.app import create_app
from sqlseed_web.messages import Message, catalog
from sqlseed_web.state import Connection, UIState
from sqlseed_web.workbench_runtime import (
    WorkbenchError,
    bind_document,
    check_document,
    execute_run,
    parse_document,
    plan_execution,
)
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import WorkspaceStore

from .test_workbench_store import draft_payload, run_payload


def assert_message(value: Any, suffix: str) -> None:
    assert isinstance(value, Message)
    assert value.key.endswith(suffix)
    assert value.key in catalog()
    assert str(value)


@pytest.mark.parametrize(
    ("changes", "suffix"),
    [
        ({"document": []}, "document_must_be_a_configuration_object"),
        ({"target_label": "postgresql://[broken/db"}, "invalid_target_label_use_a_credential_free"),
        ({"tables": ["orders"]}, "each_run_table_must_be_an_object"),
        ({"tables": [{"name": "orders", "count": True}]}, "run_table_count_must_be_a_nonnegative"),
        ({"tables": [{"name": "orders", "count": -1}]}, "run_table_count_must_be_a_nonnegative"),
        ({"tables": [{"name": "orders", "count": 1, "status": "invalid"}]}, "unknown_run_table_status"),
        ({"status": "invalid"}, "unknown_run_status"),
        ({"tables": {}}, "tables_must_be_a_list_of_at"),
        ({"tables": [{"name": "orders", "count": 1}] * 1001}, "tables_must_be_a_list_of_at"),
        ({"tables": [{"name": "orders", "count": 1}] * 2}, "run_table_names_must_be_unique"),
        ({"rows_inserted": -1}, "rows_inserted_must_be_a_nonnegative_integer"),
        (
            {"tables": [{"name": "orders", "count": 1, "rows_inserted": True}]},
            "rows_inserted_must_be_a_nonnegative_integer",
        ),
        ({"revision": 0}, "revision_must_be_a_positive_integer_or"),
        ({"created_at": -1}, "created_at_must_be_a_nonnegative_timestamp"),
        ({"plan_hash": "not-a-sha256"}, "plan_hash_must_be_a_sha_256"),
        ({"execution": {"mode": "replace_selected"}}, "replacement_execution_requires_an_immutable_plan_hash"),
        ({"order": [1]}, "order_must_be_a_bounded_list_of"),
    ],
)
def test_invalid_run_snapshots_never_replace_or_append_history(tmp_path: Path, changes: dict, suffix: str) -> None:
    store = WorkspaceStore(tmp_path / "workspace.db")
    original = store.create_run(run_payload(status="done"))
    invalid = run_payload(**changes)
    with pytest.raises(ValueError) as caught:
        store.create_run(invalid)
    assert_message(caught.value.args[0], suffix)
    assert store.list_runs() == [original]
    assert store.get_run(original["id"]) == original


@pytest.mark.parametrize("case", ["view-state", "revision"])
def test_invalid_draft_creation_keeps_saved_revision(tmp_path: Path, case: str) -> None:
    store = WorkspaceStore(tmp_path / "workspace.db")
    saved = store.save_draft(draft_payload())
    payload = draft_payload(view_state=[]) if case == "view-state" else draft_payload()
    expected_revision = 1 if case == "revision" else None
    with pytest.raises(ValueError) as caught:
        store.save_draft(payload, expected_revision=expected_revision)
    assert_message(
        caught.value.args[0],
        "view_state_must_be_an_object" if case == "view-state" else "expected_revision_is_only_valid_when_updating",
    )
    assert store.list_drafts() == [saved]


def test_nonobject_persisted_record_is_reported_without_overwriting_it(tmp_path: Path) -> None:
    store = WorkspaceStore(tmp_path / "workspace.db")
    draft = store.save_draft(draft_payload())
    with sqlite_connection(store.path) as db:
        db.execute("UPDATE workspace_drafts SET payload = '[]' WHERE id = ?", (draft["id"],))
    with pytest.raises(RuntimeError) as caught:
        store.get_draft(draft["id"])
    assert_message(caught.value.args[0], "invalid_workspace_record_expected_a_json_object")
    with sqlite_connection(store.path) as db:
        assert db.execute("SELECT payload FROM workspace_drafts").fetchone() == ("[]",)


@pytest.fixture(name="validation_db")
def fixture_validation_db(tmp_path: Path) -> Iterator[tuple[UIState, Connection]]:
    path = tmp_path / "validation.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, amount INTEGER NOT NULL);"
            "INSERT INTO items VALUES(1, 'existing', 7);"
            "CREATE TABLE required_self(id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES required_self(id));"
            "CREATE TABLE pair_self(x INTEGER, y INTEGER, px INTEGER, py INTEGER, PRIMARY KEY(x, y),"
            " FOREIGN KEY(px, py) REFERENCES pair_self(x, y));"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        yield registry, conn
    finally:
        for job in registry.recent_jobs():
            if job.status == "running":
                registry.complete_job(job.job_id, error="test cleanup")
        registry.close_connection(conn.conn_id)


def item_document(columns: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"provider": "base", "tables": [{"name": "items", "count": 3, "columns": columns or []}]}


@pytest.mark.parametrize(
    ("columns", "code", "suffix"),
    [
        (
            [{"name": "code", "generator": "choice", "params": {"choices": ["same"]}}],
            "unique_domain_exhausted",
            "only_explicit_candidate_values_are_available_insufficient",
        ),
        (
            [{"name": "id", "generator": "integer", "params": {"min_value": 1, "max_value": 2}}],
            "unique_domain_exhausted",
            "the_explicit_integer_range_is_too_small",
        ),
        (
            [{"name": "amount", "derive_from": "missing", "expression": "missing * 2"}],
            "unknown_derive_source",
            "the_derived_source_column_does_not_exist",
        ),
        (
            [{"name": "amount", "derive_from": "id", "expression": "unknown(id)"}],
            "unknown_expression_function",
            "unsupported_expression_function",
        ),
        (
            [{"name": "code", "generator": "string", "null_ratio": 0.5}],
            "not_null",
            "not_null_columns_cannot_have_null_ratio",
        ),
        ([{"name": "code", "generator": "skip"}], "required_column", "a_not_null_column_without_a_default"),
        ([{"name": "amount", "generator": "integer"}] * 2, "duplicate_column", "duplicate_column_configuration"),
    ],
)
def test_rule_rejections_have_localizable_field_context_and_do_not_write(
    validation_db: tuple, columns: list[dict], code: str, suffix: str
) -> None:
    _, conn = validation_db
    schema = inspect_connection(conn)
    document = item_document(columns)
    original = deepcopy(document)
    result = check_document(conn, document, schema["schema_hash"], preview=True)
    assert not result["ok"]
    issue = next(item for item in result["issues"] if item["code"] == code)
    assert issue["table"] == "items"
    assert issue["column"] == columns[0]["name"]
    assert_message(issue["message"], suffix)
    assert result["samples"] == {}
    assert document == original
    assert conn.orchestrator.query("SELECT * FROM items") == [{"id": 1, "code": "existing", "amount": 7}]


@pytest.mark.parametrize(
    ("document", "code", "suffix"),
    [
        ({"tables": [{"name": "missing", "count": 2}]}, "unknown_table", "the_table_does_not_exist"),
        ({"tables": [{"name": "items", "count": 2}] * 2}, "duplicate_table", "a_table_cannot_occur_more_than_once"),
        (
            {"tables": [{"name": "required_self", "count": 2}]},
            "self_reference_no_seed",
            "an_empty_table_with_a_not_null",
        ),
        (
            {"tables": [{"name": "pair_self", "count": 2}]},
            "composite_self_reference",
            "core_does_not_guarantee_second_phase_backfill",
        ),
        (
            {**item_document(), "custom_column_mappings": {"exact": {"code": {"generator": "imaginary"}}}},
            "unknown_generator",
            "custom_mappings_contain_an_unknown_generator",
        ),
        (
            {
                **item_document(),
                "associations": [
                    {"column_name": "amount", "source_table": "items", "target_tables": ["items"], "strategy": "random"}
                ],
            },
            "association_strategy",
            "core_does_not_currently_distinguish_the_random",
        ),
        (
            {
                **item_document(),
                "associations": [{"column_name": "missing", "source_table": "items", "target_tables": ["items"]}],
            },
            "invalid_association_target",
            "the_association_target_table_or_column_does",
        ),
        (
            {
                **item_document(),
                "associations": [{"column_name": "amount", "source_table": "missing", "target_tables": ["items"]}],
            },
            "invalid_parent_source",
            "the_referenced_source_table_or_column_does",
        ),
    ],
)
def test_invalid_relation_plans_explain_blocking_and_preserve_all_tables(
    validation_db: tuple, document: dict, code: str, suffix: str
) -> None:
    _, conn = validation_db
    result = check_document(conn, {"provider": "base", **document}, inspect_connection(conn)["schema_hash"])
    assert not result["ok"]
    issue = next(item for item in result["issues"] if item["code"] == code)
    assert_message(issue["message"], suffix)
    assert conn.orchestrator.get_row_count("items") == 1
    for table in ("required_self", "pair_self"):
        assert conn.orchestrator.get_row_count(table) == 0


@pytest.mark.parametrize(
    ("options", "suffix"),
    [
        ({"count": 0}, "preview_count_must_be_between_1_and"),
        ({"count": 101}, "preview_count_must_be_between_1_and"),
        ({"sample_max_attempts": False}, "sample_max_attempts_must_be_a_positive"),
        ({"sample_max_attempts": 0}, "sample_max_attempts_must_be_a_positive"),
    ],
)
def test_invalid_preview_budgets_are_rejected_before_generation(
    validation_db: tuple, options: dict, suffix: str
) -> None:
    _, conn = validation_db
    document = item_document()
    schema_hash = inspect_connection(conn)["schema_hash"]
    with pytest.raises(WorkbenchError) as caught:
        check_document(conn, document, schema_hash, **options)
    assert_message(caught.value.args[0], suffix)
    assert conn.orchestrator.get_row_count("items") == 1


@pytest.mark.parametrize(
    ("text", "suffix"),
    [("tables: [", "cannot_parse_yaml_json"), ("- items", "configuration_must_be_a_yaml_json_object")],
)
def test_invalid_yaml_and_ambiguous_targets_never_bind(validation_db: tuple, text: str, suffix: str) -> None:
    _, conn = validation_db
    with pytest.raises(WorkbenchError) as caught:
        parse_document(conn, text)
    assert caught.value.code == "parse_error"
    assert_message(caught.value.args[0], suffix)
    document = {**item_document(), "db_path": conn.target, "url": "sqlite://"}
    with pytest.raises(WorkbenchError) as ambiguous:
        bind_document(conn, document)
    assert ambiguous.value.code == "target_mismatch"
    assert_message(ambiguous.value.args[0], "provide_only_one_of_db_path_and")
    assert conn.orchestrator.get_row_count("items") == 1


def test_saved_schema_mismatch_blocks_plan_before_a_run_is_created(validation_db: tuple, tmp_path: Path) -> None:
    registry, conn = validation_db
    schema = inspect_connection(conn)
    store = WorkspaceStore(tmp_path / "workspace.db")
    draft = store.save_draft(
        draft_payload(
            target_key=schema["target_key"],
            target_label=schema["target_label"],
            document=item_document(),
            schema_hash="old",
        )
    )
    with pytest.raises(WorkbenchError) as caught:
        plan_execution(conn.conn_id, draft["id"], 1, schema["schema_hash"], "old", registry=registry, store=store)
    assert caught.value.code == "schema_changed"
    assert_message(caught.value.args[0], "the_saved_draft_s_schema_version_does")
    assert store.list_runs() == []
    assert registry.recent_jobs() == []
    assert conn.orchestrator.get_row_count("items") == 1


def test_queued_schema_change_finishes_job_without_writing(validation_db: tuple, tmp_path: Path) -> None:
    registry, conn = validation_db
    store = WorkspaceStore(tmp_path / "workspace.db")
    schema = inspect_connection(conn)
    run = store.create_run(
        run_payload(
            target_key=schema["target_key"],
            target_label=schema["target_label"],
            document=item_document(),
            schema_hash="outdated",
            config_hash="outdated",
            tables=[{"name": "items", "count": 3, "status": "queued", "rows_inserted": 0}],
        )
    )
    job = registry.create_job(conn.conn_id, "workbench", "queued")
    execute_run(run["id"], conn.conn_id, job.job_id, registry=registry, store=store)
    saved = store.get_run(run["id"])
    assert saved["status"] == "error"
    assert saved["rows_inserted"] == 0
    assert saved["errors_i18n"][0]["key"].endswith("configuration_sources_or_schema_changed_while_queued")
    assert registry.job_snapshot(job.job_id).status == "error"
    assert conn.orchestrator.get_row_count("items") == 1
    # A rejected queued run must release the connection reservation.
    next_job = registry.create_job(conn.conn_id, "workbench", "next")
    registry.complete_job(next_job.job_id)


def test_terminal_storage_failure_keeps_committed_rows_and_releases_reservation(
    validation_db: tuple, tmp_path: Path
) -> None:
    registry, conn = validation_db
    store = WorkspaceStore(tmp_path / "workspace.db")
    schema = inspect_connection(conn)
    document = item_document()
    document["tables"][0]["seed"] = 17
    checked = check_document(conn, document, schema["schema_hash"])
    assert checked["ok"]
    run = store.create_run(
        run_payload(
            target_key=schema["target_key"],
            target_label=schema["target_label"],
            document=document,
            schema_hash=schema["schema_hash"],
            config_hash=checked["config_hash"],
            order=["items"],
            tables=[{"name": "items", "count": 3, "status": "queued", "rows_inserted": 0}],
        )
    )
    with sqlite_connection(store.path) as db:
        db.execute(
            "CREATE TRIGGER reject_terminal BEFORE UPDATE ON workspace_runs "
            "WHEN NEW.status = 'done' BEGIN SELECT RAISE(ABORT, 'history write denied'); END"
        )
    job = registry.create_job(conn.conn_id, "workbench", "storage failure")
    execute_run(run["id"], conn.conn_id, job.job_id, registry=registry, store=store)
    saved = store.get_run(run["id"])
    assert saved["status"] == "error"
    assert saved["rows_inserted"] == 3
    assert saved["errors_i18n"][0]["key"].endswith("cannot_save_the_final_run_state")
    terminal = registry.job_snapshot(job.job_id)
    assert terminal.status == "error"
    assert terminal.rows_inserted == 3
    assert conn.orchestrator.get_row_count("items") == 4
    assert conn.orchestrator.query("SELECT code, amount FROM items WHERE id = 1") == [{"code": "existing", "amount": 7}]
    next_job = registry.create_job(conn.conn_id, "workbench", "next")
    registry.complete_job(next_job.job_id)


@pytest.fixture(name="validation_client")
def fixture_validation_client(validation_db: tuple, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    registry, conn = validation_db
    for module in (api, workbench, workbench_data):
        monkeypatch.setattr(module, "state", registry)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "api-workspace.db"))
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(tmp_path / "settings.json"))
    client = TestClient(create_app(), base_url="http://127.0.0.1:9876", client=("127.0.0.1", 40000))
    try:
        yield client, registry, conn
    finally:
        client.close()


@pytest.mark.parametrize(
    ("method", "route", "payload", "status", "suffix"),
    [
        ("get", "/api/jobs/missing", None, 404, "unknown_job"),
        ("post", "/api/config/serialize", {"yaml": "x: ["}, 422, "invalid_yaml"),
        ("post", "/api/config/serialize", {"yaml": "- item"}, 422, "yaml_root_must_be_a_mapping"),
    ],
)
def test_api_rejections_preserve_status_legacy_text_and_descriptor(
    validation_client: tuple, method: str, route: str, payload: dict | None, status: int, suffix: str
) -> None:
    client, registry, conn = validation_client
    response = client.request(method, route, **({"json": payload} if payload is not None else {}))
    body = response.json()
    assert response.status_code == status
    assert isinstance(body["detail"], str)
    assert body["detail_key"].endswith(suffix)
    assert body["detail_key"] in catalog()
    assert isinstance(body["detail_params"], dict)
    assert conn.orchestrator.get_row_count("items") == 1
    assert registry.recent_jobs() == []


def test_busy_preview_is_rejected_then_recovers_after_job_completion(validation_client: tuple) -> None:
    client, registry, conn = validation_client
    job = registry.create_job(conn.conn_id, "workbench", "reserved")
    response = client.post(f"/api/connections/{conn.conn_id}/preview", json={"table": "items", "count": 2})
    assert response.status_code == 409
    assert response.json()["detail_key"].endswith("connection_task_busy")
    registry.complete_job(job.job_id)
    restored = client.post(f"/api/connections/{conn.conn_id}/preview", json={"table": "items", "count": 2})
    assert restored.status_code == 200
    assert len(restored.json()["rows"]) == 2
    assert conn.orchestrator.get_row_count("items") == 1
