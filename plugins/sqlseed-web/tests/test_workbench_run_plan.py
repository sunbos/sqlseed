"""The shared run helper drains real workers and reports deadlines without polling."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from sqlseed_web import runtime_lifecycle, workbench_runtime
from sqlseed_web.state import Connection

from . import test_workbench_runtime as helpers

fixture_connection = helpers.fixture_connection


def test_run_plan_closes_its_connection_after_preflight_failure(
    connection: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = helpers._RunPlanRegistry()
    monkeypatch.setattr(helpers, "_RunPlanRegistry", lambda: registry)
    invalid = {"provider": "base", "tables": [{"name": "not_in_schema", "count": 1}]}

    with pytest.raises(AssertionError):
        helpers.run_plan(connection, invalid, tmp_path)

    assert registry.list_connections() == []
    assert registry.recent_jobs() == []
    assert connection.orchestrator.get_row_count("parents") == 0


@pytest.mark.parametrize("stage", ["validation", "after_completion"])
def test_run_plan_timeout_keeps_diagnostics_and_drains_the_actual_worker(
    connection: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    registry = helpers._RunPlanRegistry()
    monkeypatch.setattr(helpers, "_RunPlanRegistry", lambda: registry)
    entered, release = threading.Event(), threading.Event()
    original_start = workbench_runtime.start_run
    original_snapshot = helpers._run_plan_snapshot
    snapshots: list[dict[str, Any]] = []
    activity_before = runtime_lifecycle.runtime_gate.activity()

    def pause() -> None:
        entered.set()
        if not release.wait(30):
            raise RuntimeError("The test did not release its controlled worker")

    if stage == "validation":
        original_check = workbench_runtime._current_run_check

        def delayed_check(*args: Any, **kwargs: Any) -> Any:
            pause()
            return original_check(*args, **kwargs)

        monkeypatch.setattr(workbench_runtime, "_current_run_check", delayed_check)
    else:
        original_execute = workbench_runtime.execute_run

        def delayed_exit(*args: Any, **kwargs: Any) -> None:
            original_execute(*args, **kwargs)
            pause()

        monkeypatch.setattr(workbench_runtime, "execute_run", delayed_exit)

    def start_at_known_stage(*args: Any, **kwargs: Any) -> dict[str, Any]:
        run = original_start(*args, **kwargs)
        assert entered.wait(30), "The actual worker did not reach the controlled stage"
        return run

    def release_after_snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
        snapshot = original_snapshot(*args, **kwargs)
        snapshots.append(snapshot)
        release.set()
        return snapshot

    monkeypatch.setattr(workbench_runtime, "start_run", start_at_known_stage)
    monkeypatch.setattr(helpers, "_run_plan_snapshot", release_after_snapshot)
    document = {**helpers.document(), "provider": "base"}
    try:
        with pytest.raises(pytest.fail.Exception, match="run exceeded 0.01s") as failure:
            helpers.run_plan(connection, document, tmp_path, timeout=0.01)
    finally:
        release.set()
        if registry.worker is not None:
            registry.worker.join(30)

    assert "cleanup_drained=True" in str(failure.value)
    assert snapshots[0]["status"] == ("queued" if stage == "validation" else "done")
    assert snapshots[0]["worker_alive"] is True
    assert snapshots[0]["worker_stack"]
    assert snapshots[-1]["worker_alive"] is False
    assert snapshots[-1]["status"] == "done"
    assert all(job.status == "done" for job in registry.recent_jobs())
    assert registry.list_connections() == []
    assert registry.worker_errors == []
    assert runtime_lifecycle.runtime_gate.activity() == activity_before
    assert connection.orchestrator.get_row_count("parents") == 3
    assert connection.orchestrator.get_row_count("children") == 4


def test_run_plan_keeps_a_stalled_workers_connection_owned_until_it_exits(
    connection: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = helpers._RunPlanRegistry()
    monkeypatch.setattr(helpers, "_RunPlanRegistry", lambda: registry)
    entered, release = threading.Event(), threading.Event()
    original_check = workbench_runtime._current_run_check
    original_start = workbench_runtime.start_run
    activity_before = runtime_lifecycle.runtime_gate.activity()

    def delayed_check(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        if not release.wait(30):
            raise RuntimeError("The test did not release its controlled worker")
        return original_check(*args, **kwargs)

    def start_at_known_stage(*args: Any, **kwargs: Any) -> dict[str, Any]:
        run = original_start(*args, **kwargs)
        assert entered.wait(30)
        return run

    monkeypatch.setattr(workbench_runtime, "_current_run_check", delayed_check)
    monkeypatch.setattr(workbench_runtime, "start_run", start_at_known_stage)
    try:
        with pytest.raises(pytest.fail.Exception, match="cleanup_drained=False") as failure:
            helpers.run_plan(
                connection, {**helpers.document(), "provider": "base"}, tmp_path, timeout=0.01, cleanup_timeout=0.01
            )
        assert '"phase": "validation"' in str(failure.value)
        assert registry.worker is not None and registry.worker.is_alive()
        assert len(registry.list_connections()) == 1
        assert registry.recent_jobs()[0].status == "running"
    finally:
        release.set()
        if registry.worker is not None:
            registry.worker.join(30)

    assert registry.worker is not None and not registry.worker.is_alive()
    assert registry.list_connections() == []
    assert registry.recent_jobs()[0].status == "done"
    assert runtime_lifecycle.runtime_gate.activity() == activity_before
    assert connection.orchestrator.get_row_count("children") == 4


def test_run_plan_cleanup_cannot_hide_the_original_worker_defect(
    connection: Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = helpers._RunPlanRegistry()
    monkeypatch.setattr(helpers, "_RunPlanRegistry", lambda: registry)
    original_close = registry.close_connection
    defect = AttributeError("original worker defect")
    cleanup_error = RuntimeError("cleanup failed after closing")

    def broken_fill(*_args: Any, **_kwargs: Any) -> None:
        raise defect

    def close_then_fail(conn_id: str) -> None:
        original_close(conn_id)
        raise cleanup_error

    monkeypatch.setattr(workbench_runtime, "_fill_run_table", broken_fill)
    monkeypatch.setattr(registry, "close_connection", close_then_fail)
    with pytest.raises(AttributeError) as failure:
        helpers.run_plan(connection, {**helpers.document(), "provider": "base"}, tmp_path)

    assert failure.value is defect
    assert registry.worker_errors == [defect, cleanup_error]
    assert registry.worker is not None and not registry.worker.is_alive()
    assert registry.list_connections() == []
    assert registry.recent_jobs()[0].status == "error"
    assert connection.orchestrator.get_row_count("parents") == 0
