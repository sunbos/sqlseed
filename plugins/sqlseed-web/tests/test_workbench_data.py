"""Bounded, read-only data browsing against isolated real SQLite databases."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import api, workbench, workbench_data
from sqlseed_web.app import create_app
from sqlseed_web.state import UIState
from sqlseed_web.workbench_schema import _target_identity
from sqlseed_web.workbench_store import get_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlseed_web.state import Connection


@pytest.fixture(name="data_client")
def fixture_data_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, UIState]]:
    registry = UIState()
    monkeypatch.setattr(api, "state", registry)
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setattr(workbench_data, "state", registry)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("SQLSEED_AI_ENABLED", "0")
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client, registry
    for conn in registry.list_connections():
        registry.close_connection(conn["conn_id"])


@pytest.fixture(name="database")
def fixture_database(tmp_path: Path) -> Path:
    path = tmp_path / "target.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL, "
            "optional TEXT DEFAULT NULL, payload BLOB);"
            "CREATE TABLE composite (a INTEGER NOT NULL, b INTEGER NOT NULL, value TEXT, PRIMARY KEY (b, a));"
            "CREATE TABLE empty_table (id INTEGER PRIMARY KEY, note TEXT NOT NULL DEFAULT 'fresh', "
            "doubled INTEGER GENERATED ALWAYS AS (id * 2) STORED);"
            "CREATE TABLE no_primary (value TEXT);"
            'CREATE TABLE "odd table" ("key""part" INTEGER PRIMARY KEY, "user value" TEXT);'
        )
        db.executemany(
            "INSERT INTO records (id, value, payload) VALUES (?, ?, ?)",
            [(5, "five", b"\x00\xff"), (1, "one", None), (3, "three", None), (2, "two", None)],
        )
        db.executemany("INSERT INTO composite VALUES (?, ?, ?)", [(1, 2, "last"), (2, 1, "middle"), (1, 1, "first")])
        db.executemany("INSERT INTO no_primary VALUES (?)", [("alpha",), ("beta",)])
        db.execute('INSERT INTO "odd table" VALUES (?, ?)', (8, "quoted identifiers"))
    return path


def connect(registry: UIState, path: Path) -> Connection:
    return registry.add_connection(str(path), provider="base")


def endpoint(conn: Connection, table: str = "records") -> str:
    return f"/api/workbench/connections/{conn.conn_id}/tables/{quote(table, safe='')}/data"


def create_run(conn: Connection, tables: tuple[str, ...] = ("records",), **overrides: Any) -> dict[str, Any]:
    target_key, target_label = _target_identity(conn)
    return get_store().create_run(
        {
            "target_key": target_key,
            "target_label": target_label,
            "schema_hash": "test-schema",
            "document": {"provider": "base", "tables": [{"name": name, "count": 2} for name in tables]},
            "tables": [{"name": name, "count": 2, "status": "done"} for name in tables],
            "status": "done",
            **overrides,
        }
    )


def test_reads_bounded_current_records_in_primary_key_order(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    response = client.get(endpoint(conn), params={"limit": 2, "offset": 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert [row["id"] for row in result["rows"]] == [2, 3]
    assert [row["value"] for row in result["rows"]] == ["two", "three"]
    assert result["total"] == 4
    assert result["limit"] == 2
    assert result["offset"] == 1
    assert result["order_by"] == ["id"]
    assert result["table"] == "records"
    assert result["dialect"] == "sqlite"
    expected_key, expected_label = _target_identity(conn)
    assert result["target_key"] == expected_key
    assert result["target_label"] == expected_label
    assert datetime.fromisoformat(result["read_at"]).tzinfo is not None
    assert [column["name"] for column in result["columns"]] == ["id", "value", "optional", "payload"]
    last = client.get(endpoint(conn), params={"limit": 2, "offset": 3}).json()
    assert [row["id"] for row in last["rows"]] == [5]
    assert last["rows"][0]["payload"] == "0x00ff"
    beyond = client.get(endpoint(conn), params={"offset": 99}).json()
    assert beyond["rows"] == []
    assert beyond["total"] == 4


def test_compound_primary_key_uses_constraint_order_not_column_order(data_client: Any, database: Path) -> None:
    client, registry = data_client
    result = client.get(endpoint(connect(registry, database), "composite"), params={"limit": 2}).json()
    assert result["order_by"] == ["b", "a"]
    assert [(row["b"], row["a"]) for row in result["rows"]] == [(1, 1), (1, 2)]


def test_empty_tables_keep_the_same_real_column_metadata_as_schema(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    result = client.get(endpoint(conn, "empty_table")).json()
    schema = client.get(f"/api/workbench/connections/{conn.conn_id}/schema").json()
    expected = next(table["columns"] for table in schema["tables"] if table["name"] == "empty_table")
    assert result["columns"] == expected
    assert result["rows"] == []
    assert result["total"] == 0
    assert result["columns"][2]["is_computed"] is True
    assert result["columns"][1]["default"] == "'fresh'"


def test_tables_without_primary_key_do_not_claim_a_stable_order(data_client: Any, database: Path) -> None:
    client, registry = data_client
    result = client.get(endpoint(connect(registry, database), "no_primary")).json()
    assert result["order_by"] == []
    assert sorted(row["value"] for row in result["rows"]) == ["alpha", "beta"]


def test_identifiers_are_quoted_and_unknown_tables_do_not_reveal_other_names(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    result = client.get(endpoint(conn, "odd table")).json()
    assert result["rows"] == [{'key"part': 8, "user value": "quoted identifiers"}]
    assert result["order_by"] == ['key"part']
    for table in ("unknown", 'records"; DROP TABLE records; --'):
        response = client.get(endpoint(conn, table))
        assert response.status_code == 404
        assert "composite" not in response.text
        assert "DROP" not in response.text
    assert client.get(endpoint(conn)).json()["total"] == 4


def test_encoded_path_and_percent_characters_remain_literal_identifiers(data_client: Any, database: Path) -> None:
    client, registry = data_client
    with sqlite_connection(database) as db:
        db.execute('CREATE TABLE "segment/data%" ("rate%:value" INTEGER PRIMARY KEY, "text" TEXT)')
        db.execute('INSERT INTO "segment/data%" VALUES (?, ?)', (7, "literal name"))
    response = client.get(endpoint(connect(registry, database), "segment/data%"))
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [{"rate%:value": 7, "text": "literal name"}]
    assert response.json()["order_by"] == ["rate%:value"]


def test_large_integers_and_nonfinite_numbers_are_readable_without_json_precision_loss(
    data_client: Any, database: Path
) -> None:
    client, registry = data_client
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE numeric_values (id INTEGER PRIMARY KEY, positive REAL, negative REAL)")
        db.execute("INSERT INTO numeric_values VALUES (?, ?, ?)", (9007199254740993, float("inf"), -float("inf")))
    response = client.get(endpoint(connect(registry, database), "numeric_values"))
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [{"id": "9007199254740993", "positive": "inf", "negative": "-inf"}]


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"limit": "1.5"}, {"offset": -1}, {"offset": "x"}])
def test_pagination_input_is_validated_before_database_access(data_client: Any, database: Path, query: Any) -> None:
    client, registry = data_client
    response = client.get(endpoint(connect(registry, database)), params=query)
    assert response.status_code == 422


def test_busy_or_closed_connections_are_rejected_without_queuing(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    with registry.connection_operation(conn.conn_id):
        assert client.get(endpoint(conn)).status_code == 409
    job = registry.create_job(conn.conn_id, "workbench", "reserved")
    try:
        assert client.get(endpoint(conn)).status_code == 409
    finally:
        registry.complete_job(job.job_id)
    registry.close_connection(conn.conn_id)
    assert client.get(endpoint(conn)).status_code == 404


def test_run_data_requires_the_same_target_and_a_table_in_the_run(
    data_client: Any, database: Path, tmp_path: Path
) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    run = create_run(conn)
    assert client.get(endpoint(conn), params={"run_id": run["id"]}).status_code == 200
    outside = client.get(endpoint(conn, "empty_table"), params={"run_id": run["id"]})
    assert outside.status_code == 403
    assert outside.json()["detail"]["code"] == "table_outside_run"
    other_path = tmp_path / "another.db"
    with sqlite_connection(other_path) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
    other = connect(registry, other_path)
    wrong_target = client.get(endpoint(other), params={"run_id": run["id"]})
    assert wrong_target.status_code == 409
    assert wrong_target.json()["detail"]["code"] == "target_mismatch"
    assert client.get(endpoint(conn), params={"run_id": "missing"}).status_code == 404


def test_partial_run_exposes_current_table_contents_without_claiming_inserted_rows(
    data_client: Any, database: Path
) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    run = create_run(conn, status="error", rows_inserted=1)
    result = client.get(endpoint(conn), params={"run_id": run["id"]}).json()
    assert result["total"] == 4
    assert len(result["rows"]) == 4
    assert "rows_inserted" not in result


def test_data_read_does_not_change_rows_schema_sequence_or_database_file(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    conn.orchestrator.get_table_names()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite_connection(database) as db:
        before_dump = list(db.iterdump())
    for table in ("records", "composite", "empty_table", "no_primary"):
        assert client.get(endpoint(conn, table)).status_code == 200
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with sqlite_connection(database) as db:
        assert list(db.iterdump()) == before_dump


def test_run_connection_candidates_match_target_without_opening_databases(
    data_client: Any, database: Path, tmp_path: Path
) -> None:
    client, registry = data_client
    original = connect(registry, database)
    parallel = registry.add_connection(f"sqlite:///{database}", provider="base")
    other = connect(registry, tmp_path / "not-created.db")
    run = create_run(original)
    with registry.connection_operation(original.conn_id):
        response = client.get(f"/api/workbench/runs/{run['id']}/data-connections")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["target_key"] == run["target_key"]
    assert result["target_label"] == run["target_label"]
    assert {item["conn_id"] for item in result["connections"]} == {original.conn_id, parallel.conn_id}
    assert all(set(item) == {"conn_id", "target_label"} for item in result["connections"])
    assert not (tmp_path / "not-created.db").exists()
    assert other.conn_id not in response.text
    registry.close_connection(original.conn_id)
    registry.close_connection(parallel.conn_id)
    assert client.get(f"/api/workbench/runs/{run['id']}/data-connections").json()["connections"] == []
    assert client.get("/api/workbench/runs/missing/data-connections").status_code == 404


def test_refresh_reads_current_rows_and_new_columns_from_the_existing_connection(
    data_client: Any, database: Path
) -> None:
    client, registry = data_client
    conn = connect(registry, database)
    before = client.get(endpoint(conn)).json()
    assert before["total"] == 4
    with sqlite_connection(database) as db:
        db.execute("ALTER TABLE records ADD COLUMN new_field TEXT DEFAULT 'new value'")
        db.execute("INSERT INTO records (value) VALUES ('later row')")
    after = client.get(endpoint(conn)).json()
    assert after["total"] == 5
    assert after["columns"][-1]["name"] == "new_field"
    assert all(row["new_field"] == "new value" for row in after["rows"])
    assert after["rows"][-1]["value"] == "later row"


def test_readonly_sqlite_connection_can_browse_data(data_client: Any, database: Path) -> None:
    client, registry = data_client
    conn = registry.add_connection(f"sqlite:///file:{database}?mode=ro&uri=true", provider="base")
    response = client.get(endpoint(conn))
    assert response.status_code == 200
    assert response.json()["total"] == 4


def test_driver_failures_are_redacted_and_release_the_connection_gate(data_client: Any, tmp_path: Path) -> None:
    client, registry = data_client
    path = tmp_path / "private-credential.db"
    path.write_bytes(b"not a SQLite database")
    conn = connect(registry, path)
    response = client.get(endpoint(conn))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "data_read_failed"
    assert "private-credential" not in response.text
    assert "SQL" not in response.text
    with registry.connection_operation(conn.conn_id):
        pass


def test_connection_candidates_never_expose_postgresql_credentials_or_open_remote_databases(data_client: Any) -> None:
    client, registry = data_client
    conn = registry.add_connection(
        "postgresql://secret-user:private-password@db.example.test/app?sslmode=require", provider="base"
    )
    run = create_run(conn)
    response = client.get(f"/api/workbench/runs/{run['id']}/data-connections")
    assert response.status_code == 200
    assert response.json()["connections"] == [
        {"conn_id": conn.conn_id, "target_label": "postgresql://db.example.test:5432/app"}
    ]
    assert all(secret not in response.text for secret in ("secret-user", "private-password", "sslmode", "require"))
