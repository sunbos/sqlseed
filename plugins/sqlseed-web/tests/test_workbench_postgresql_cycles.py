"""Real PostgreSQL workbench checks keep SQLite-only cycle support unavailable."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlseed._utils.sql_safe import quote_identifier

from sqlseed_web import api, workbench
from sqlseed_web.app import create_app
from sqlseed_web.state import UIState

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration


@pytest.fixture(name="pg_cycle")
def fixture_pg_cycle(pg_url: str) -> Iterator[Engine]:
    """Own one schema; URL search_path also isolates fresh workbench sessions."""
    namespace = f"sqlseed_web_cycle_{uuid4().hex}"
    quoted_namespace = quote_identifier(namespace)
    database_url = make_url(pg_url)
    previous_options = database_url.query.get("options", "")
    assert isinstance(previous_options, str)
    isolated_url = database_url.update_query_dict({"options": f"{previous_options} -csearch_path={namespace}".strip()})
    admin = create_engine(database_url)
    try:
        with admin.begin() as db:
            db.execute(text(f"CREATE SCHEMA {quoted_namespace}"))
        try:
            engine = create_engine(isolated_url)
            try:
                with engine.begin() as db:
                    statements = [
                        "CREATE TABLE cycle_a(id SERIAL PRIMARY KEY, b_id INTEGER NOT NULL, note TEXT NOT NULL)",
                        (
                            "CREATE TABLE cycle_b(id SERIAL PRIMARY KEY, a_id INTEGER NOT NULL REFERENCES cycle_a(id), "
                            "note TEXT NOT NULL)"
                        ),
                        "INSERT INTO cycle_a(b_id,note) VALUES(1,'a-original')",
                        "INSERT INTO cycle_b(a_id,note) VALUES(1,'b-original')",
                        "ALTER TABLE cycle_a ADD FOREIGN KEY(b_id) REFERENCES cycle_b(id)",
                        "SELECT setval('cycle_a_id_seq',37,true)",
                        "SELECT setval('cycle_b_id_seq',53,false)",
                    ]
                    for statement in statements:
                        db.execute(text(statement)).close()
                yield engine
            finally:
                engine.dispose()
        finally:
            with admin.begin() as db:
                db.execute(text(f"DROP SCHEMA {quoted_namespace} CASCADE"))
    finally:
        admin.dispose()


def _cycle_snapshot(engine: Engine) -> dict[str, list[tuple[object, ...]]]:
    """Read both cyclic tables and sequence state so rejection tests detect any database side effect."""
    queries = {
        "cycle_a": "SELECT id,b_id,note FROM cycle_a ORDER BY id",
        "cycle_b": "SELECT id,a_id,note FROM cycle_b ORDER BY id",
        "cycle_a_id_seq": "SELECT last_value,is_called FROM cycle_a_id_seq",
        "cycle_b_id_seq": "SELECT last_value,is_called FROM cycle_b_id_seq",
    }
    with engine.connect() as db:
        return {name: [tuple(row) for row in db.execute(text(query))] for name, query in queries.items()}


@pytest.fixture(name="pg_workbench")
def fixture_pg_workbench(
    pg_cycle: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UIState, str, dict[str, Any]]]:
    """Expose a real isolated PostgreSQL cycle through the application with a temporary workspace."""
    assert _cycle_snapshot(pg_cycle) == {
        "cycle_a": [(1, 1, "a-original")],
        "cycle_b": [(1, 1, "b-original")],
        "cycle_a_id_seq": [(37, True)],
        "cycle_b_id_seq": [(53, False)],
    }
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.sqlite3"))
    conn = registry.add_connection(pg_cycle.url.render_as_string(hide_password=False), provider="base")
    try:
        with TestClient(create_app()) as client:
            response = client.get(f"/api/workbench/connections/{conn.conn_id}/schema")
            assert response.status_code == 200, response.text
            schema = response.json()
            assert schema["dialect"] == "postgresql"
            assert {table["name"] for table in schema["tables"]} == {"cycle_a", "cycle_b"}
            assert len(schema["edges"]) == 2
            yield client, registry, conn.conn_id, schema
    finally:
        registry.close_connection(conn.conn_id)


def _cycle_document() -> dict[str, Any]:
    """Request both cyclic tables with stable generation settings and no hidden rule adjustments."""
    return {
        "provider": "base",
        "tables": [{"name": name, "count": 3, "seed": 31} for name in ("cycle_a", "cycle_b")],
    }


@pytest.mark.parametrize("endpoint", ["check", "preview"])
def test_pg_workbench_rejects_seeded_cycles_without_touching_rows_or_sequences(
    pg_cycle: Engine, pg_workbench: tuple[TestClient, UIState, str, dict[str, Any]], endpoint: str
) -> None:
    """Keep PostgreSQL cycles unsupported even with valid parents and preserve rows, sequences and job state."""
    client, registry, conn_id, schema = pg_workbench
    before = _cycle_snapshot(pg_cycle)
    response = client.post(
        f"/api/workbench/{endpoint}",
        json={
            "conn_id": conn_id,
            "schema_hash": schema["schema_hash"],
            "document": _cycle_document(),
            "count": 3,
        },
    )
    assert response.status_code == 200, response.text
    checked = response.json()
    assert checked["ok"] is False
    assert checked["existing_cycle_sources"] == []
    assert checked["order"] == checked["layers"] == []
    assert checked["samples"] == checked["effective_rules"] == {}
    assert {
        (source["table"], source["column"], source["source_table"], tuple(source["source_columns"]))
        for source in checked["sources"]
    } == {("cycle_a", "b_id", "cycle_b", ("id",)), ("cycle_b", "a_id", "cycle_a", ("id",))}
    assert all(
        source["has_values"] and source["selected"] and source["row_count"] == 1 for source in checked["sources"]
    )
    assert [issue["code"] for issue in checked["issues"]] == ["cross_table_cycle"]
    issue = checked["issues"][0]
    assert issue["severity"] == "error"
    assert set(issue["tables"]) == {"cycle_a", "cycle_b"}
    assert set(issue["edge_ids"]) == {edge["id"] for edge in schema["edges"]}
    assert issue["message_key"] == "backend.workbench_runtime.cross_table_cycles_require_general_backfill_the"
    assert "其他数据库的循环尚不支持" in issue["message"]
    assert _cycle_snapshot(pg_cycle) == before
    assert registry.recent_jobs() == []


def test_pg_run_rechecks_saved_cycle_even_when_client_bypasses_check_and_preview(
    pg_cycle: Engine, pg_workbench: tuple[TestClient, UIState, str, dict[str, Any]]
) -> None:
    """Enforce the cycle boundary on run admission even when a caller bypasses both frontend checks."""
    client, registry, conn_id, schema = pg_workbench
    before = _cycle_snapshot(pg_cycle)
    response = client.post(
        "/api/workbench/drafts",
        json={
            "conn_id": conn_id,
            "name": "Unsupported PostgreSQL cycle",
            "schema_hash": schema["schema_hash"],
            "document": _cycle_document(),
        },
    )
    assert response.status_code == 200, response.text
    draft = response.json()
    # Deliberately bypass both frontend checks; admission must inspect the saved document.
    response = client.post(
        "/api/workbench/runs",
        json={
            "conn_id": conn_id,
            "draft_id": draft["id"],
            "revision": draft["revision"],
            "schema_hash": draft["schema_hash"],
            "config_hash": "",
            "execution": {"mode": "append", "reset_identity": False},
        },
    )
    assert response.status_code == 409, response.text
    rejected = response.json()["detail"]
    assert rejected["code"] == "check_failed"
    assert "其他数据库的循环尚不支持" in rejected["message"]
    history = client.get("/api/workbench/runs")
    assert history.status_code == 200, history.text
    assert history.json() == []
    reopened = client.get(f"/api/workbench/drafts/{draft['id']}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json() == draft
    assert registry.recent_jobs() == []
    assert _cycle_snapshot(pg_cycle) == before
