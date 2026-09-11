"""Durable workspace snapshots and concurrent revision checks on real SQLite."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest


def draft_payload(**changes: Any) -> dict[str, Any]:
    return {
        "name": "Orders fixture",
        "target_key": "sha256:orders",
        "target_label": "postgresql://tester:***@localhost/orders",
        "document": {
            "provider": "base",
            "locale": "zh_CN",
            "tables": [{"name": "orders", "count": 3, "seed": 0, "columns": []}],
        },
        "schema_hash": "schema-v1",
        "view_state": {"positions": {"orders": {"x": 12, "y": 24}}},
        **changes,
    }


def run_payload(**changes: Any) -> dict[str, Any]:
    draft = draft_payload()
    return {
        "draft_id": "draft-1",
        "revision": 1,
        "target_key": draft["target_key"],
        "target_label": draft["target_label"],
        "document": draft["document"],
        "schema_hash": draft["schema_hash"],
        "status": "queued",
        "tables": [{"name": "orders", "count": 3, "status": "queued", "rows_inserted": 0}],
        **changes,
    }


def test_draft_snapshot_survives_reopen_and_does_not_alias_input(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    path = tmp_path / "metadata" / "workspace.sqlite3"
    store = WorkspaceStore(path)
    payload = draft_payload()
    created = store.save_draft(payload)
    payload["document"]["tables"][0]["count"] = 99

    restored = WorkspaceStore(path).get_draft(created["id"])
    assert restored == created
    assert restored["revision"] == 1
    assert restored["document"]["tables"][0]["count"] == 3
    assert restored["updated_at"]
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_draft_edit_requires_the_latest_revision(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import RevisionConflict, WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    original = store.save_draft(draft_payload())
    for expected in (None, 0, 2):
        with pytest.raises(RevisionConflict):
            store.save_draft(draft_payload(name="Lost change"), draft_id=original["id"], expected_revision=expected)
    saved = store.save_draft(draft_payload(name="Revised"), draft_id=original["id"], expected_revision=1)
    assert saved["revision"] == 2
    assert saved["name"] == "Revised"
    with pytest.raises(RevisionConflict):
        store.save_draft(draft_payload(), draft_id=original["id"], expected_revision=1)
    assert store.get_draft(original["id"]) == saved


def test_concurrent_draft_edits_have_exactly_one_winner(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import RevisionConflict, WorkspaceStore

    path = tmp_path / "workspace.db"
    stores = [WorkspaceStore(path), WorkspaceStore(path)]
    original = stores[0].save_draft(draft_payload())

    def edit(index: int) -> str:
        try:
            stores[index].save_draft(draft_payload(name=f"Edit {index}"), draft_id=original["id"], expected_revision=1)
        except RevisionConflict:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == ["conflict", "saved"]
    assert stores[0].get_draft(original["id"])["revision"] == 2


def test_draft_listing_filters_target_and_orders_latest_first(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    first = store.save_draft(draft_payload())
    other = store.save_draft(draft_payload(target_key="other"))
    latest = store.save_draft(draft_payload(name="Latest"), draft_id=first["id"], expected_revision=1)
    assert [row["id"] for row in store.list_drafts()] == [latest["id"], other["id"]]
    assert store.list_drafts("sha256:orders")[0]["revision"] == 2
    assert store.list_drafts("absent") == []
    with pytest.raises(KeyError):
        store.get_draft("missing")
    with pytest.raises(KeyError):
        store.save_draft(draft_payload(), draft_id="missing", expected_revision=1)


@pytest.mark.parametrize("field", ["db_path", "url"])
def test_connection_fields_are_rejected_in_documents(tmp_path: Path, field: str) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    document = {**draft_payload()["document"], field: "postgresql://user:secret@host/db"}
    with pytest.raises(ValueError, match=r"connection|db_path|url"):
        store.save_draft(draft_payload(document=document))
    with pytest.raises(ValueError, match=r"connection|db_path|url"):
        store.create_run(run_payload(document=document))
    assert not store.list_drafts()
    assert not store.list_runs()


@pytest.mark.parametrize("field", ["target_label", "target_key"])
def test_unredacted_connection_passwords_are_rejected(tmp_path: Path, field: str) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    with pytest.raises(ValueError, match=r"password|credential"):
        store.save_draft(draft_payload(**{field: "postgresql://user:secret@host/db"}))
    with pytest.raises(ValueError, match=r"password|credential"):
        store.create_run(run_payload(**{field: "postgresql://user:secret@host/db"}))
    assert b"secret" not in store.path.read_bytes()


def test_run_snapshots_are_fixed_while_status_and_progress_change(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    payload = run_payload(id="job-123")
    created = store.create_run(payload)
    payload["document"]["tables"][0]["count"] = 100
    assert created["id"] == "job-123"
    tables = [{"name": "orders", "count": 3, "status": "done", "rows_inserted": 3}]
    finished = store.update_run(created["id"], {"status": "done", "tables": tables, "rows_inserted": 3})
    assert finished["document"]["tables"][0]["count"] == 3
    assert finished["tables"][0]["rows_inserted"] == 3
    assert store.get_run(created["id"]) == finished
    assert WorkspaceStore(store.path).get_run(created["id"]) == finished
    with pytest.raises(ValueError, match=r"exist|duplicate"):
        store.create_run(run_payload(id="job-123"))


@pytest.mark.parametrize("field", ["document", "schema_hash", "draft_id", "revision", "target_key", "id", "created_at"])
def test_run_snapshot_fields_cannot_be_replaced(tmp_path: Path, field: str) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    created = store.create_run(run_payload())
    with pytest.raises(ValueError, match=r"immutable|update|change"):
        store.update_run(created["id"], {field: "tampered"})
    assert store.get_run(created["id"]) == created


def test_recovery_marks_unfinished_runs_without_guessing_insert_counts(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    path = tmp_path / "workspace.db"
    store = WorkspaceStore(path)
    queued = store.create_run(run_payload())
    running = store.create_run(run_payload(status="running"))
    store.update_run(
        running["id"],
        {"tables": [{"name": "orders", "count": 3, "status": "running", "rows_inserted": 1}], "rows_inserted": 1},
    )
    completed = store.create_run(run_payload(status="done"))

    recovered = WorkspaceStore(path)
    assert recovered.get_run(completed["id"])["status"] == "done"
    assert recovered.get_run(queued["id"])["status"] == "interrupted"
    restored = recovered.get_run(running["id"])
    assert restored["status"] == "interrupted"
    assert restored["tables"][0]["status"] == "interrupted"
    assert restored["rows_inserted"] == restored["tables"][0]["rows_inserted"] == 1
    assert restored["row_counts_exact"] is False
    assert restored["finished_at"]
    fresh = recovered.create_run(run_payload())
    assert recovered.get_run(fresh["id"])["status"] == "queued"


def test_run_list_is_bounded_and_missing_runs_raise_key_error(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    created = [store.create_run(run_payload()) for _ in range(4)]
    assert [row["id"] for row in store.list_runs(limit=2)] == [row["id"] for row in reversed(created[-2:])]
    with pytest.raises(ValueError):
        store.list_runs(limit=-1)
    with pytest.raises(KeyError):
        store.get_run("missing")
    with pytest.raises(KeyError):
        store.update_run("missing", {"status": "done"})


def test_get_store_caches_the_configured_path_without_recovering_live_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlseed_web.workbench_store import get_store

    path = tmp_path / "configured.db"
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(path))
    store = get_store()
    run = store.create_run(run_payload())
    assert store.path == path
    assert get_store() is store
    assert get_store().get_run(run["id"])["status"] == "queued"
    assert path.is_file()


def test_size_and_non_json_values_are_rejected_before_writes(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    for payload in (
        draft_payload(name="x" * 513),
        draft_payload(document={"content": "x" * 2_100_000}),
        draft_payload(view_state={"zoom": float("nan")}),
    ):
        with pytest.raises(ValueError):
            store.save_draft(payload)
    assert store.list_drafts() == []


def test_newer_workspace_schema_is_not_overwritten(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    path = tmp_path / "future.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA user_version = 99")
        db.execute("CREATE TABLE future (payload TEXT)")
        db.execute("INSERT INTO future VALUES (?)", (json.dumps({"preserve": True}),))
    with pytest.raises(RuntimeError, match=r"schema|version"):
        WorkspaceStore(path)
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT payload FROM future").fetchone()[0] == '{"preserve": true}'


def test_runtime_run_shape_preserves_order_and_requested_counts(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    tables = [{"name": "orders", "requested_count": 3, "status": "queued", "rows_inserted": 0, "errors": []}]
    created = store.create_run(run_payload(name="Fixture", config_hash="config-v1", order=["orders"], tables=tables))
    assert created["name"] == "Fixture"
    assert created["config_hash"] == "config-v1"
    assert created["order"] == ["orders"]
    updated = store.update_run(created["id"], {"errors": ["Table blocked"], "elapsed": 0.5, "batch_count": 1})
    assert updated["errors"] == ["Table blocked"]
    assert updated["elapsed"] == 0.5
    with pytest.raises(ValueError):
        store.update_run(created["id"], {"config_hash": "tampered"})
    with pytest.raises(ValueError):
        store.update_run(created["id"], {"tables": [{**tables[0], "requested_count": 99}]})


def test_run_errors_cannot_persist_unredacted_credentials(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    created = store.create_run(run_payload())
    with pytest.raises(ValueError, match=r"password|credential"):
        store.update_run(created["id"], {"error": "Connection failed: postgresql://user:secret@host/db"})
    assert store.get_run(created["id"])["error"] is None


def test_parallel_run_workers_do_not_lose_records_or_independent_progress(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    path = tmp_path / "workspace.db"
    stores = [WorkspaceStore(path), WorkspaceStore(path)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(lambda index: stores[index % 2].create_run(run_payload()), range(20)))
    assert len({run["id"] for run in runs}) == len(stores[0].list_runs()) == 20
    run_id = runs[0]["id"]
    changes = [{"progress": {"completed": 1}}, {"status": "running"}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda index: stores[index].update_run(run_id, changes[index]), range(2)))
    assert stores[0].get_run(run_id)["status"] == "running"
    assert stores[0].get_run(run_id)["progress"] == {"completed": 1}


def test_default_store_uses_user_application_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlseed_web import workbench_store

    monkeypatch.delenv("SQLSEED_WEB_WORKSPACE_PATH", raising=False)
    monkeypatch.setattr(workbench_store.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    store = workbench_store.get_store()
    assert store.path == tmp_path / "Library" / "Application Support" / "sqlseed" / "workspace.sqlite3"


def test_failed_runs_keep_unstarted_tables_separate_from_unknown_counts(tmp_path: Path) -> None:
    from sqlseed_web.workbench_store import WorkspaceStore

    store = WorkspaceStore(tmp_path / "workspace.db")
    created = store.create_run(run_payload())
    updated = store.update_run(
        created["id"],
        {
            "status": "error",
            "row_counts_exact": False,
            "tables": [{"name": "orders", "count": 3, "status": "not_run", "rows_inserted": None}],
        },
    )
    assert updated["tables"][0]["status"] == "not_run"
    assert updated["tables"][0]["rows_inserted"] is None
    assert updated["row_counts_exact"] is False
