"""Process handoff restores file-backed sessions without persisting credentials."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from sqlseed_web import runtime_session
from sqlseed_web.state import UIState


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    value = UIState()
    monkeypatch.setattr(runtime_session, "state", value)
    yield value
    for item in value.list_connections():
        value.close_connection(item["conn_id"])


def test_export_close_restore_preserves_connection_id_rows_provider_locale_and_ai_binding(
    tmp_path: Path, registry: UIState
) -> None:
    path = tmp_path / "session.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, label TEXT)")
        db.execute("INSERT INTO records VALUES (1, 'existing')")
    conn = registry.add_connection(str(path), provider="faker", locale="zh_CN")
    conn.orchestrator.get_table_names()
    overrides = {
        "backend": "openai_compat",
        "base_url": "https://service.test/v1",
        "model": "selected-model",
        "api_key": "secret-only-in-ipc",
        "_api_key_service": '["openai_compat","https://service.test/v1"]',
        "_api_key_cleared": "1",
    }
    registry.set_ai_override(overrides)
    files_before = set(tmp_path.iterdir())
    snapshot = runtime_session.export_session()
    assert snapshot == {
        "connections": [{"conn_id": conn.conn_id, "target": str(path), "provider": "faker", "locale": "zh_CN"}],
        "ai_override": overrides,
    }
    snapshot["ai_override"]["api_key"] = "new-ipc-key"
    assert registry.get_ai_override()["api_key"] == "secret-only-in-ipc"
    assert set(tmp_path.iterdir()) == files_before
    runtime_session.close_session()
    assert registry.list_connections() == []
    assert conn.orchestrator._connected is False
    summary = runtime_session.restore_session(snapshot)
    assert summary == {"restored_connections": 1, "failed_connections": [], "ai_session_restored": True}
    restored = registry.get_connection(conn.conn_id)
    assert restored.provider == "faker"
    assert restored.locale == "zh_CN"
    assert restored.orchestrator.get_row_count("records") == 1
    assert registry.get_ai_override() == snapshot["ai_override"]
    assert "new-ipc-key" not in str(summary)


@pytest.mark.parametrize(
    "target",
    [":memory:", "sqlite://", "sqlite:///:memory:", "sqlite:///file:shared-session?mode=memory&cache=shared&uri=true"],
)
def test_memory_connections_block_handoff_without_closing_or_losing_rows(target: str, registry: UIState) -> None:
    conn = registry.add_connection(target, provider="base")
    conn.orchestrator.get_table_names()
    with conn.orchestrator._db._engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE records(value TEXT)")
        db.exec_driver_sql("INSERT INTO records VALUES ('keep memory rows')")
    with pytest.raises(HTTPException) as rejected:
        runtime_session.export_session()
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "plugin_session_not_restorable"
    assert "内存" in rejected.value.detail["message"]
    assert registry.get_connection(conn.conn_id) is conn
    assert conn.orchestrator.get_row_count("records") == 1


def test_restore_reports_partial_failures_without_exposing_targets_or_secrets(
    tmp_path: Path, registry: UIState
) -> None:
    path = tmp_path / "valid.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records(value INTEGER)")
    snapshot = {
        "connections": [
            {"conn_id": "restore-ok", "target": str(path), "provider": "base", "locale": "en_US"},
            {
                "conn_id": "restore-failed",
                "target": "unsupported://user:secret@private-host/db",
                "provider": "base",
                "locale": "en_US",
            },
        ],
        "ai_override": {"api_key": "secret", "_api_key_service": "service-bound"},
    }
    summary = runtime_session.restore_session(snapshot)
    assert summary["restored_connections"] == 1
    assert len(summary["failed_connections"]) == 1
    assert summary["failed_connections"][0]["conn_id"] == "restore-failed"
    assert summary["failed_connections"][0]["message"]
    assert "secret" not in str(summary)
    assert "private-host" not in str(summary)
    assert summary["ai_session_restored"] is True
    assert registry.get_connection("restore-ok").orchestrator.get_table_names() == ["records"]
    assert len(registry.list_connections()) == 1


def test_duplicate_restored_id_cannot_replace_or_close_an_existing_connection(
    tmp_path: Path, registry: UIState
) -> None:
    path = tmp_path / "original.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE records(value INTEGER)")
    original = registry.add_connection(str(path), provider="base", connection_id="same-id")
    original.orchestrator.get_table_names()
    with pytest.raises(ValueError, match="connection"):
        registry.add_connection(str(path), provider="base", connection_id="same-id")
    assert registry.get_connection("same-id") is original
    assert original.orchestrator._connected is True


def test_connection_that_cannot_reopen_is_not_left_registered(tmp_path: Path, registry: UIState) -> None:
    summary = runtime_session.restore_session(
        {
            "connections": [
                {
                    "conn_id": "gone",
                    "target": str(tmp_path / "missing-parent" / "gone.db"),
                    "provider": "base",
                    "locale": "en_US",
                }
            ],
            "ai_override": {},
        }
    )
    assert summary["restored_connections"] == 0
    assert [item["conn_id"] for item in summary["failed_connections"]] == ["gone"]
    assert registry.list_connections() == []


def test_a_removed_database_is_reported_without_creating_an_empty_replacement(
    tmp_path: Path, registry: UIState
) -> None:
    missing = tmp_path / "removed.db"
    summary = runtime_session.restore_session(
        {
            "connections": [{"conn_id": "gone", "target": str(missing), "provider": "base", "locale": "en_US"}],
            "ai_override": {},
        }
    )
    assert summary["restored_connections"] == 0
    assert not missing.exists()
    assert registry.list_connections() == []


def test_oversized_prepared_session_resumes_business_and_preserves_the_live_state(
    registry: UIState, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_web import managed_worker, runtime_lifecycle, worker_control

    gate = runtime_lifecycle.RuntimeGate()
    monkeypatch.setattr(runtime_lifecycle, "runtime_gate", gate)
    monkeypatch.setattr(worker_control, "MAX_MESSAGE_BYTES", 512)
    override = {"api_key": "private-session-secret" * 50, "_api_key_service": "same-service"}
    registry.set_ai_override(override)
    with pytest.raises(HTTPException) as error:
        managed_worker.prepare_runtime_session()
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "plugin_session_too_large"
    assert "private-session-secret" not in str(error.value)
    assert registry.get_ai_override() == override
    with gate.request():
        assert gate.activity()["requests"] == 1
