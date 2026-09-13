"""Real SQLite aliases, isolated memory targets, and saved identity compatibility."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import workbench
from sqlseed_web.state import Connection, ConnectionBusyError, UIState
from sqlseed_web.workbench_runtime import WorkbenchError, _checked_saved, check_document, normalize_document
from sqlseed_web.workbench_schema import inspect_connection
from sqlseed_web.workbench_store import WorkspaceStore


def historical_key(kind: str, value: str) -> str:
    """The persisted pre-R4 format; changing it would strand ordinary drafts."""
    encoded = json.dumps([kind, value], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _assert_shared_write_admission(registry: UIState, one: Connection, two: Connection) -> None:
    assert len({entry["group_key"] for entry in registry.list_connections()}) == 1
    registry.create_job(one.conn_id, "workbench", "first")
    with pytest.raises(ConnectionBusyError, match="此数据库"):
        registry.create_job(two.conn_id, "workbench", "alias")


@pytest.fixture(name="registry")
def fixture_registry() -> Iterator[UIState]:
    state = UIState()
    yield state
    for job in state.recent_jobs():
        state.complete_job(job.job_id)
    for conn in state.list_connections():
        state.close_connection(conn["conn_id"])


@pytest.fixture(name="database")
def fixture_database(tmp_path: Path) -> Path:
    path = tmp_path / "orders with spaces.db"
    # sqlite3's own context manager commits/rolls back but does not close the
    # handle. Release it before aliases rename the file on Windows.
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER NOT NULL); INSERT INTO items VALUES(1, 7)"
        )
    return path


@pytest.mark.parametrize("alias", ["url", "file_uri", "localhost_uri", "encoded_colon_uri", "symlink"])
def test_real_file_aliases_share_configuration_group_and_write_admission(
    registry: UIState, database: Path, alias: str
) -> None:
    database = database.rename(database.with_name("orders with spaces %41.db"))
    if alias == "url":
        target = f"sqlite+pysqlite:///{database}"
    elif alias in {"file_uri", "localhost_uri", "encoded_colon_uri"}:
        file_uri = database.as_uri()
        if alias == "localhost_uri":
            file_uri = file_uri.replace("file://", "file://localhost", 1)
        elif alias == "encoded_colon_uri":
            file_uri = "file:" + file_uri.removeprefix("file:").replace(":", "%3A")
        target = f"sqlite:///{file_uri}?uri=true&mode=rw"
    else:
        link = database.with_name("linked.db")
        link.symlink_to(database)
        target = str(link)
    one = registry.add_connection(str(database), provider="base")
    two = registry.add_connection(target, provider="base")
    assert (
        one.orchestrator.query("SELECT value FROM items")
        == two.orchestrator.query("SELECT value FROM items")
        == [{"value": 7}]
    )
    original, equivalent = inspect_connection(one), inspect_connection(two)
    assert original["target_key"] == historical_key("sqlite", str(database.resolve()))
    assert equivalent["target_key"] == original["target_key"]
    assert equivalent["target_label"] == str(database.resolve())
    _assert_shared_write_admission(registry, one, two)


@pytest.mark.parametrize("name", ["identity-shared", ":memory:"])
def test_named_shared_memory_uses_one_identity_without_ambiguous_legacy_aliases(registry: UIState, name: str) -> None:
    uri = f"file:{name}?mode=memory&cache=shared"
    with sqlite_connection(uri, uri=True) as anchor:
        anchor.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(7)")
        one = registry.add_connection(f"sqlite:///{uri}&uri=true", provider="base")
        two = registry.add_connection(f"sqlite:///{uri}&uri=true&timeout=10", provider="base")
        assert one.orchestrator.query("SELECT value FROM items") == two.orchestrator.query("SELECT value FROM items")
        first, second = inspect_connection(one), inspect_connection(two)
        assert first["target_key"] == second["target_key"]
        assert "target_key_aliases" not in first
        assert "target_key_aliases" not in second
        _assert_shared_write_admission(registry, one, two)


@pytest.mark.parametrize("target", [":memory:", "sqlite:///:memory:", "sqlite:///file:private?mode=memory&uri=true"])
def test_private_memory_never_shares_group_configuration_or_write_admission(registry: UIState, target: str) -> None:
    one = registry.add_connection(target, provider="base")
    two = registry.add_connection(target, provider="base")
    one.orchestrator.execute("CREATE TABLE private_marker(value INTEGER)")
    assert one.orchestrator.get_table_names() == ["private_marker"]
    assert two.orchestrator.get_table_names() == []
    first, second = inspect_connection(one), inspect_connection(two)
    assert first["target_key"] == historical_key("sqlite-memory", one.conn_id)
    assert second["target_key"] != first["target_key"]
    assert len({entry["group_key"] for entry in registry.list_connections()}) == 2
    registry.create_job(one.conn_id, "workbench", "first")
    registry.create_job(two.conn_id, "workbench", "independent")


def test_memory_query_without_uri_mode_still_identifies_the_real_disk_database(
    registry: UIState, database: Path
) -> None:
    plain = registry.add_connection(str(database), provider="base")
    ignored_options = registry.add_connection(f"sqlite:///{database}?mode=memory&cache=shared", provider="base")
    assert ignored_options.orchestrator.query("SELECT value FROM items") == [{"value": 7}]
    assert inspect_connection(ignored_options)["target_key"] == inspect_connection(plain)["target_key"]
    registry.create_job(plain.conn_id, "workbench", "first")
    with pytest.raises(ConnectionBusyError, match="此数据库"):
        registry.create_job(ignored_options.conn_id, "workbench", "alias")


def test_differently_named_shared_memory_databases_remain_independent(registry: UIState) -> None:
    one = registry.add_connection("sqlite:///file:identity-one?mode=memory&cache=shared&uri=true", provider="base")
    two = registry.add_connection("sqlite:///file:identity-two?mode=memory&cache=shared&uri=true", provider="base")
    one.orchestrator.execute("CREATE TABLE private_marker(value INTEGER)")
    assert one.orchestrator.get_table_names() == ["private_marker"]
    assert two.orchestrator.get_table_names() == []
    assert inspect_connection(one)["target_key"] != inspect_connection(two)["target_key"]
    registry.create_job(one.conn_id, "workbench", "first")
    registry.create_job(two.conn_id, "workbench", "independent")


def test_legacy_uri_draft_requires_explicit_import_and_does_not_rewrite_saved_history(
    registry: UIState, database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = f"sqlite:///file:{quote(str(database))}?uri=true&mode=rw"
    conn = registry.add_connection(target, provider="base")
    schema = inspect_connection(conn)
    old_label = str(Path(f"file:{quote(str(database))}").resolve())
    old_key = historical_key("sqlite", old_label)
    store = WorkspaceStore(tmp_path / "workspace.db")
    document = normalize_document(conn, {"provider": "base", "tables": [{"name": "items", "count": 2}]})
    draft = store.save_draft(
        {
            "name": "Legacy URI",
            "target_key": old_key,
            "target_label": old_label,
            "document": document,
            "schema_hash": schema["schema_hash"],
            "view_state": {},
        }
    )
    run = store.create_run({**draft, "id": "historical-run", "draft_id": draft["id"], "status": "done"})
    monkeypatch.setattr(workbench, "state", registry)
    monkeypatch.setattr(workbench, "get_store", lambda: store)
    app = FastAPI()
    app.include_router(workbench.router)
    with TestClient(app) as client:
        listed = client.get("/api/workbench/drafts", params={"conn_id": conn.conn_id})
        assert listed.status_code == 200, listed.text
        assert listed.json() == []
        assert schema["target_key"] != old_key
        assert "target_key_aliases" not in schema
        checked = check_document(conn, document, schema["schema_hash"])
        assert checked["ok"], checked
        with pytest.raises(WorkbenchError, match="目标不匹配"):
            _checked_saved(conn, store, draft["id"], 1, schema["schema_hash"], checked["config_hash"])
        assert store.get_draft(draft["id"]) == draft
        exported = client.get(f"/api/workbench/drafts/{draft['id']}/export")
        assert exported.status_code == 200, exported.text
        imported = client.post(
            "/api/workbench/drafts",
            json={
                "conn_id": conn.conn_id,
                "name": draft["name"],
                "document": document,
                "schema_hash": schema["schema_hash"],
                "view_state": {},
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["target_key"] == historical_key("sqlite", str(database.resolve()))
        assert imported.json()["id"] != draft["id"]
        assert store.get_draft(draft["id"]) == draft
    assert store.get_run(run["id"]) == run


def test_identical_schema_in_another_database_does_not_authorize_a_saved_draft(
    registry: UIState, database: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other.db"
    with (
        sqlite_connection(database) as source,
        sqlite_connection(other) as destination,
    ):
        source.backup(destination)
    one = registry.add_connection(str(database), provider="base")
    two = registry.add_connection(f"sqlite:///file:{quote(str(other))}?uri=true", provider="base")
    schema = inspect_connection(one)
    assert inspect_connection(two)["schema_hash"] == schema["schema_hash"]
    document = normalize_document(one, {"provider": "base", "tables": [{"name": "items", "count": 2}]})
    store = WorkspaceStore(tmp_path / "workspace.db")
    draft = store.save_draft(
        {
            "name": "Other target",
            "document": document,
            "view_state": {},
            **{key: schema[key] for key in ("target_key", "target_label", "schema_hash")},
        }
    )
    checked = check_document(two, document, schema["schema_hash"])
    with pytest.raises(WorkbenchError, match="目标不匹配"):
        _checked_saved(two, store, draft["id"], 1, schema["schema_hash"], checked["config_hash"])


@pytest.mark.skipif(sys.platform == "win32", reason="Windows filenames cannot contain a literal colon")
def test_literal_file_prefix_draft_is_never_authorized_for_a_different_uri_database(
    registry: UIState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    # SQLITE_USE_URI builds parse a relative "file:" prefix even with uri=False.
    # An absolute path creates the literal filename on both SQLite builds, as
    # SQLAlchemy also does for the non-URI connection below.
    for filename, marker in (("file:catalog.db", 7), ("catalog.db", 99)):
        with sqlite_connection(tmp_path / filename, uri=False) as db:
            db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT INTO items VALUES(1, ?)", (marker,))
    literal = registry.add_connection("sqlite:///file:catalog.db?uri=false", provider="base")
    uri = registry.add_connection("sqlite:///file:catalog.db?uri=true&mode=rw", provider="base")
    assert literal.orchestrator.query("SELECT value FROM items") == [{"value": 7}]
    assert uri.orchestrator.query("SELECT value FROM items") == [{"value": 99}]
    schema = inspect_connection(literal)
    uri_schema = inspect_connection(uri)
    assert schema["schema_hash"] == uri_schema["schema_hash"]
    assert schema["target_key"] != uri_schema["target_key"]
    document = normalize_document(literal, {"provider": "base", "tables": [{"name": "items", "count": 2}]})
    store = WorkspaceStore(tmp_path / "workspace.db")
    draft = store.save_draft(
        {
            "name": "Literal filename",
            "document": document,
            "view_state": {},
            **{key: schema[key] for key in ("target_key", "target_label", "schema_hash")},
        }
    )
    checked = check_document(uri, document, uri_schema["schema_hash"])
    assert checked["ok"], checked
    with pytest.raises(WorkbenchError, match="目标不匹配"):
        _checked_saved(uri, store, draft["id"], 1, uri_schema["schema_hash"], checked["config_hash"])


@pytest.mark.parametrize("memory", [False, True])
def test_custom_vfs_is_rejected_before_registering_an_isolated_database_as_the_same_target(
    registry: UIState, database: Path, memory: bool
) -> None:
    name = "/identity-vfs-memory" if memory else str(database)
    ordinary_uri = f"file:{name}" + ("?mode=memory&cache=shared" if memory else "?mode=rw")
    vfs_uri = ordinary_uri + "&vfs=memdb"
    # Real SQLite verifies the same name with memdb VFS addresses another database.
    with (
        sqlite_connection(ordinary_uri, uri=True) as ordinary,
        sqlite_connection(vfs_uri, uri=True) as isolated,
    ):
        if memory:
            ordinary.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(7)")
        assert ordinary.execute("SELECT value FROM items").fetchall() == [(7,)]
        assert isolated.execute("SELECT name FROM sqlite_schema WHERE name='items'").fetchall() == []
        isolated.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(99)")
        assert isolated.execute("SELECT value FROM items").fetchall() == [(99,)]
        assert ordinary.execute("SELECT value FROM items").fetchall() == [(7,)]
        with pytest.raises(ValueError, match="VFS"):
            registry.add_connection(f"sqlite:///{vfs_uri}&uri=true", provider="base")
        assert registry.list_connections() == []


@pytest.mark.parametrize("query", ["mode=memory%00&cache=shared", "mode%00=memory&cache=shared", "vfs%00=memdb"])
def test_uri_nul_truncation_cannot_disguise_an_isolated_memory_database_as_a_disk_target(
    registry: UIState, database: Path, query: str
) -> None:
    sqlite_uri = f"file:{quote(str(database))}?{query}"
    with (
        sqlite_connection(database) as disk,
        sqlite_connection(sqlite_uri, uri=True) as isolated,
    ):
        assert disk.execute("SELECT value FROM items").fetchall() == [(7,)]
        assert isolated.execute("SELECT name FROM sqlite_schema WHERE name='items'").fetchall() == []
        isolated.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(99)")
        assert isolated.execute("SELECT value FROM items").fetchall() == [(99,)]
        assert disk.execute("SELECT value FROM items").fetchall() == [(7,)]
        # SQLAlchemy decodes URL query values before sqlite3 decodes the URI.
        target = f"sqlite:///{sqlite_uri.replace('%00', '%2500')}&uri=true"
        with pytest.raises(ValueError, match="NUL"):
            registry.add_connection(target, provider="base")
        assert registry.list_connections() == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows filenames cannot contain TAB, CR, or LF")
@pytest.mark.parametrize("control", ["\t", "\r", "\n"])
def test_raw_uri_controls_cannot_silently_change_the_database_filename(
    registry: UIState, tmp_path: Path, control: str
) -> None:
    ordinary = tmp_path / "catalog.db"
    different = tmp_path / f"ca{control}talog.db"
    for path, marker in ((ordinary, 7), (different, 99)):
        with sqlite_connection(path) as db:
            db.execute("CREATE TABLE items(value INTEGER)")
            db.execute("INSERT INTO items VALUES(?)", (marker,))
    raw_uri = f"file:{different}"
    with sqlite_connection(raw_uri, uri=True) as raw:
        assert raw.execute("SELECT value FROM items").fetchall() == [(99,)]
    with pytest.raises(ValueError, match="控制字符"):
        registry.add_connection(f"sqlite:///{raw_uri}?uri=true", provider="base")
    # Percent encoding retains the actual filename and is supported.
    encoded = registry.add_connection(f"sqlite:///file:{quote(str(different))}?uri=true", provider="base")
    normal = registry.add_connection(str(ordinary), provider="base")
    assert encoded.orchestrator.query("SELECT value FROM items") == [{"value": 99}]
    assert inspect_connection(encoded)["target_key"] != inspect_connection(normal)["target_key"]


def test_non_utf8_memory_uri_names_are_rejected_instead_of_replaced_by_one_identity(registry: UIState) -> None:
    uris = [f"file:identity-{name}?mode=memory&cache=shared" for name in ("%FF", "%FE")]
    with (
        sqlite_connection(uris[0], uri=True) as first,
        sqlite_connection(uris[1], uri=True) as second,
    ):
        first.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(7)")
        second.executescript("CREATE TABLE items(value INTEGER); INSERT INTO items VALUES(99)")
        assert first.execute("SELECT value FROM items").fetchall() == [(7,)]
        assert second.execute("SELECT value FROM items").fetchall() == [(99,)]
        for uri in uris:
            with pytest.raises(ValueError, match="UTF-8"):
                registry.add_connection(f"sqlite:///{uri}&uri=true", provider="base")
        assert registry.list_connections() == []
