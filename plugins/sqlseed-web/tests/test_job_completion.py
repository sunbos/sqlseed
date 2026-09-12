"""Unexpected worker defects still terminate jobs and release real connections."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, runtime_session, workbench_runtime
from sqlseed_web.state import UIState
from sqlseed_web.supervised_plugins import SupervisedPluginManager
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import WorkspaceStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlseed_web.state import Connection, Job


@pytest.fixture(name="owned_connection")
def fixture_owned_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[UIState, Connection]]:
    target = tmp_path / "target.db"
    with sqlite_connection(target) as database:
        database.execute("CREATE TABLE items(value INTEGER NOT NULL)")
    registry = UIState()
    connection = registry.add_connection(str(target), provider="base")
    connection.orchestrator.get_table_names()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(runtime_session, "state", registry)
    try:
        yield registry, connection
    finally:
        for job in registry.recent_jobs():
            if job.status == "running":
                registry.complete_job(job.job_id, error="Test cleanup after failed assertion")
        for item in registry.list_connections():
            registry.close_connection(item["conn_id"])


def _assert_failed_and_released(registry: UIState, connection: Connection, job: Job) -> None:
    terminal = registry.job_snapshot(job.job_id)
    assert terminal.status == "error"
    assert terminal.finished_at > 0
    assert terminal.error and "private implementation detail" not in terminal.error
    next_job = registry.create_job(connection.conn_id, "fill", "subsequent operation")
    registry.complete_job(next_job.job_id)
    assert connection.orchestrator.get_row_count("items") == 0


@pytest.mark.parametrize("kind", ["fill", "auto_heal"])
def test_legacy_job_defect_propagates_after_releasing_reservation(
    owned_connection: tuple[UIState, Connection], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    registry, connection = owned_connection
    job = registry.create_job(connection.conn_id, kind, "items")
    failure = AttributeError("private implementation detail")

    def broken_operation(*_args, **_kwargs):
        raise failure

    if kind == "fill":
        monkeypatch.setattr(connection.orchestrator, "fill_table", broken_operation)
        request = api.FillRequest(table="items", count=1)
        worker = api._run_fill_job
    else:
        pytest.importorskip("sqlseed_ai")
        runtime = importlib.import_module("sqlseed_ai.runtime")
        monkeypatch.setattr(runtime, "build_ai_config", broken_operation)
        request = api.AutoHealRequest()
        worker = api._run_auto_heal_job

    with pytest.raises(AttributeError) as caught:
        worker(connection.conn_id, job.job_id, request)

    assert caught.value is failure
    _assert_failed_and_released(registry, connection, job)


def _saved_run(connection: Connection, store: WorkspaceStore) -> dict:
    schema = inspect_connection(connection)
    document = workbench_runtime.normalize_document(
        connection,
        {
            "provider": "base",
            "tables": [{"name": "items", "count": 1, "columns": [{"name": "value", "generator": "integer"}]}],
        },
    )
    checked = workbench_runtime.check_document(connection, document, schema["schema_hash"])
    assert checked["ok"], checked
    return store.create_run(
        {
            "target_key": schema["target_key"],
            "target_label": schema["target_label"],
            "schema_hash": schema["schema_hash"],
            "config_hash": checked["config_hash"],
            "document": document,
            "tables": [{"name": "items", "requested_count": 1, "status": "queued", "rows_inserted": 0}],
        }
    )


@pytest.mark.parametrize("failure_stage", ["snapshot", "execution", "terminal"])
def test_workbench_defect_cannot_leave_running_or_report_success(
    owned_connection: tuple[UIState, Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    registry, connection = owned_connection
    store = WorkspaceStore(tmp_path / "workspace.db")
    run = _saved_run(connection, store)
    job = registry.create_job(connection.conn_id, "workbench", "items")
    failure = AttributeError("private implementation detail")
    update_run = store.update_run

    def broken_operation(*_args, **_kwargs):
        raise failure

    def reject_terminal(run_id, changes):
        if changes.get("status") == "done":
            raise failure
        return update_run(run_id, changes)

    with monkeypatch.context() as fault:
        if failure_stage == "snapshot":
            fault.setattr(store, "get_run", broken_operation)
        elif failure_stage == "execution":
            fault.setattr(workbench_runtime, "_fill_run_table", broken_operation)
        else:
            fault.setattr(store, "update_run", reject_terminal)
        with pytest.raises(AttributeError) as caught:
            workbench_runtime.execute_run(run["id"], connection.conn_id, job.job_id, registry=registry, store=store)

    assert caught.value is failure
    terminal = store.get_run(run["id"])
    assert terminal["status"] == "error"
    assert terminal.get("errors") or terminal.get("error")
    assert all(table["status"] != "running" for table in terminal["tables"])
    assert "private implementation detail" not in str(terminal)
    if failure_stage == "terminal":
        assert registry.job_snapshot(job.job_id).status == "error"
        assert terminal["rows_inserted"] == 1
        assert connection.orchestrator.get_row_count("items") == 1
        next_job = registry.create_job(connection.conn_id, "fill", "after persistence failure")
        registry.complete_job(next_job.job_id)
    else:
        _assert_failed_and_released(registry, connection, job)


def test_restore_defect_closes_and_unregisters_the_unfinished_connection(
    owned_connection: tuple[UIState, Connection], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, connection = owned_connection
    saved = runtime_session.export_session()
    runtime_session.close_session()
    failure = AttributeError("private implementation detail")
    original = type(connection.orchestrator).get_table_names
    opened = []

    def incomplete_open(orchestrator):
        original(orchestrator)
        opened.append(orchestrator)
        raise failure

    monkeypatch.setattr(type(connection.orchestrator), "get_table_names", incomplete_open)
    with pytest.raises(AttributeError) as caught:
        runtime_session.restore_session(saved)

    assert caught.value is failure
    assert len(opened) == 1
    assert opened[0]._connected is False
    assert_empty(registry.list_connections(), list)


@pytest.mark.parametrize("failure_stage", ["maintenance", "restore"])
def test_supervised_defect_cannot_leave_service_recovery_running(failure_stage: str) -> None:
    failure = AttributeError("private implementation detail")
    calls = []

    def enter_maintenance():
        calls.append("maintenance")
        if failure_stage == "maintenance":
            raise failure

    def restore_business():
        calls.append("restore")
        if failure_stage == "restore":
            raise failure
        return {"service_restarted": True, "connections": []}

    controller = SimpleNamespace(enter_maintenance=enter_maintenance, restore_business=restore_business)
    manager = SupervisedPluginManager(controller)
    manager._task = {"status": "running", "output": []}
    manager._package_status = "succeeded"
    manager.phase = "preparing"

    with pytest.raises(AttributeError) as caught:
        if failure_stage == "maintenance":
            manager._run({}, {})
        else:
            manager._restore()

    assert caught.value is failure
    terminal = manager.task_snapshot()
    assert terminal["status"] == "failed"
    assert terminal["restart_required"] is False
    assert "private implementation detail" not in terminal["message"]
    restored = failure_stage == "maintenance"
    assert terminal["service_ready"] is restored
    assert terminal["stage"] == ("ready" if restored else "recovery_failed")
    assert manager.service_generation == (2 if restored else 1)
    assert calls == (["maintenance", "restore"] if restored else ["restore"])
