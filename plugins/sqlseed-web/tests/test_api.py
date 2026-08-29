"""API smoke tests for sqlseed-web.

Uses FastAPI TestClient against a real SQLite DB (repo rule: never mock the
database layer — see root AGENTS.md Pitfall #13).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient  # noqa: E402

from sqlseed_web.app import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    # Reset module-level state so connections from other tests don't leak
    # into grouping assertions (the singleton survives across TestClients).
    from sqlseed_web import state as state_mod

    for c in state_mod.state.list_connections():
        state_mod.state.close_connection(c["conn_id"])
    return TestClient(app)


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = tmp_path / "ui_test.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
        conn.execute(
            "CREATE TABLE orders ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER REFERENCES users(id), "
            "amount REAL CHECK (amount >= 0))"
        )
    return str(path)


@pytest.fixture()
def conn_id(client: TestClient, db_path: str) -> str:
    res = client.post("/api/connections", json={"db_path": db_path})
    assert res.status_code == 200, res.text
    return res.json()["conn_id"]


class TestMeta:
    def test_generators_count_matches_dispatch(self, client: TestClient) -> None:
        from sqlseed.generators._dispatch import GeneratorDispatchMixin

        res = client.get("/api/meta/generators")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == len(GeneratorDispatchMixin.GENERATOR_MAP)
        assert body["count"] >= 35
        assert "email" in body["names"]
        assert isinstance(body["params"], dict)

    def test_locales_covers_mimesis_map(self, client: TestClient) -> None:
        from sqlseed.generators.mimesis_provider import MimesisProvider

        res = client.get("/api/meta/locales")
        body = res.json()
        codes = {loc["code"] for loc in body["locales"]}
        assert body["default"] in codes
        # Every locale explicitly mapped in MimesisProvider.set_locale must be selectable.
        import inspect

        src = inspect.getsource(MimesisProvider.set_locale)
        for code in ("zh_CN", "en_US", "ja_JP", "ko_KR", "de_DE", "fr_FR"):
            assert code in codes
            assert f'"{code}"' in src

    def test_dialect_kinds(self, client: TestClient) -> None:
        res = client.get("/api/meta/dialects")
        kinds = {k["id"] for k in res.json()["kinds"]}
        assert kinds == {"sqlite", "postgresql", "url"}

    def test_hooks_count(self, client: TestClient) -> None:
        res = client.get("/api/meta/hooks")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 12
        names = {h["name"] for h in body["hooks"]}
        assert "sqlseed_transform_row" in names
        first = [h for h in body["hooks"] if h["firstresult"]]
        assert len(first) >= 3  # ai_analyze, apply_ai_suggestions, pre_generate_templates

    def test_providers(self, client: TestClient) -> None:
        res = client.get("/api/meta/providers")
        body = res.json()
        assert "faker" in body["available"]
        assert "base" in body["available"]

    def test_health(self, client: TestClient) -> None:
        assert client.get("/api/health").json() == {"status": "ok"}


class TestFsBrowse:
    def test_browse_defaults_to_home(self, client: TestClient) -> None:
        from pathlib import Path

        res = client.get("/api/fs/browse")
        assert res.status_code == 200
        body = res.json()
        assert body["path"] == str(Path.home())
        assert body["parent"]

    def test_browse_directory_lists_db_files(self, client: TestClient, tmp_path: Path) -> None:
        db = tmp_path / "pickme.db"
        db.write_bytes(b"")
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / "subdir").mkdir()
        res = client.get("/api/fs/browse", params={"path": str(tmp_path)})
        body = res.json()
        names = {e["name"] for e in body["entries"]}
        # DB files and dirs are listed by default; other files filtered out.
        assert names == {"pickme.db", "subdir"}
        db_entry = next(e for e in body["entries"] if e["name"] == "pickme.db")
        assert db_entry["is_db"] is True and db_entry["is_dir"] is False and db_entry["size"] == 0

    def test_browse_all_files_flag(self, client: TestClient, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("x")
        res = client.get("/api/fs/browse", params={"path": str(tmp_path), "all_files": "true"})
        assert "notes.txt" in {e["name"] for e in res.json()["entries"]}

    def test_browse_missing_path_404(self, client: TestClient) -> None:
        res = client.get("/api/fs/browse", params={"path": "/nonexistent/definitely/not/here"})
        assert res.status_code == 404

    def test_browse_file_not_dir_400(self, client: TestClient, tmp_path: Path) -> None:
        f = tmp_path / "f.db"
        f.write_bytes(b"")
        res = client.get("/api/fs/browse", params={"path": str(f)})
        assert res.status_code == 400


class TestConnections:
    def test_connect_lists_tables(self, client: TestClient, db_path: str) -> None:
        res = client.post("/api/connections", json={"db_path": db_path})
        body = res.json()
        assert {t["name"] for t in body["tables"]} == {"users", "orders"}
        users = next(t for t in body["tables"] if t["name"] == "users")
        assert users["column_count"] == 3

    def test_locale_selectable(self, client: TestClient, db_path: str) -> None:
        res = client.post("/api/connections", json={"db_path": db_path, "locale": "zh_CN"})
        assert res.status_code == 200
        assert res.json()["conn_id"]

    def test_same_target_grouping(self, client: TestClient, db_path: str) -> None:
        """Two connections to the same file share a group_key with sequential indexes."""
        client.post("/api/connections", json={"db_path": db_path})
        client.post("/api/connections", json={"db_path": db_path})
        conns = client.get("/api/connections").json()["connections"]
        same = [c for c in conns if c["target"] == db_path]
        assert len(same) == 2
        keys = {c["group_key"] for c in same}
        assert len(keys) == 1
        assert sorted(c["group_index"] for c in same) == [1, 2]
        assert {c["group_size"] for c in same} == {2}

    def test_group_key_normalizes_paths(self, client: TestClient, tmp_path: Path) -> None:
        """File path, ./relative and sqlite:/// URL of one DB normalize to one group."""
        db = tmp_path / "grouped.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        client.post("/api/connections", json={"db_path": str(db)})
        client.post("/api/connections", json={"db_path": f"sqlite:///{db}"})
        conns = client.get("/api/connections").json()["connections"]
        keys = {c["group_key"] for c in conns}
        assert len(conns) == 2
        assert len(keys) == 1
        assert next(iter(keys)) == str(db)

    def test_ai_config_roundtrip(self, client: TestClient) -> None:
        """Session AI override stores and merges over env defaults."""
        pytest.importorskip("sqlseed_ai")
        res = client.post(
            "/api/ai/config",
            json={"backend": "ollama", "model": "gemma4:e4b", "api_key": None, "base_url": None},
        )
        body = res.json()
        assert body["available"] is True
        assert body["override"]["backend"] == "ollama"
        assert body["effective"]["backend"] == "ollama"
        assert body["effective"]["model"] == "gemma4:e4b"
        # Reset for other tests (state singleton).
        client.post("/api/ai/config", json={})

    def test_ai_config_get_without_override(self, client: TestClient) -> None:
        pytest.importorskip("sqlseed_ai")
        body = client.get("/api/ai/config").json()
        assert body["available"] is True
        assert len(body["backends"]) == 4

    def test_topo_order_referenced_first(self, client: TestClient, db_path: str) -> None:
        """orders references users — users must precede orders in the order."""
        cid = client.post("/api/connections", json={"db_path": db_path}).json()["conn_id"]
        order = client.get(f"/api/connections/{cid}/topo-order").json()["tables"]
        assert order.index("users") < order.index("orders")

    def test_topo_order_subset(self, client: TestClient, db_path: str) -> None:
        cid = client.post("/api/connections", json={"db_path": db_path}).json()["conn_id"]
        order = client.get(f"/api/connections/{cid}/topo-order?tables=orders").json()["tables"]
        assert order == ["orders"]

    def test_distinct_targets_distinct_groups(self, client: TestClient, tmp_path: Path) -> None:
        db1 = tmp_path / "a.db"
        db2 = tmp_path / "b.db"
        for db in (db1, db2):
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        client.post("/api/connections", json={"db_path": str(db1)})
        client.post("/api/connections", json={"db_path": str(db2)})
        conns = client.get("/api/connections").json()["connections"]
        assert len({c["group_key"] for c in conns}) == 2
        assert all(c["group_size"] == 1 for c in conns)

    def test_mutually_exclusive_target(self, client: TestClient, db_path: str) -> None:
        res = client.post("/api/connections", json={"db_path": db_path, "url": "postgresql://x"})
        assert res.status_code == 422

    def test_close(self, client: TestClient, conn_id: str) -> None:
        assert client.delete(f"/api/connections/{conn_id}").status_code == 200
        assert client.get(f"/api/connections/{conn_id}/tables/users/schema").status_code == 404


class TestSchemaMapping:
    def test_schema_endpoint(self, client: TestClient, conn_id: str) -> None:
        res = client.get(f"/api/connections/{conn_id}/tables/users/schema")
        body = res.json()
        assert body["row_count"] == 0
        names = [c["name"] for c in body["columns"]]
        assert names == ["id", "name", "email"]
        assert "id" in body["skippable"]  # AUTOINCREMENT PK

    def test_mapping_endpoint(self, client: TestClient, conn_id: str) -> None:
        res = client.get(f"/api/connections/{conn_id}/tables/users/mapping")
        mapping = res.json()["mapping"]
        assert mapping["id"]["generator_name"] == "skip"
        assert mapping["name"]["generator_name"] in ("string", "name", "text")

    def test_yaml_template(self, client: TestClient, conn_id: str) -> None:
        res = client.get(f"/api/connections/{conn_id}/tables/users/yaml-template")
        assert "users" in res.json()["yaml"]


class TestPreviewFill:
    def test_preview_does_not_write(self, client: TestClient, conn_id: str) -> None:
        res = client.post(f"/api/connections/{conn_id}/preview", json={"table": "users", "count": 3})
        rows = res.json()["rows"]
        assert len(rows) == 3
        count = client.get(f"/api/connections/{conn_id}/tables/users/rows").json()["total"]
        assert count == 0

    def test_fill_job_lifecycle(self, client: TestClient, conn_id: str) -> None:
        res = client.post(f"/api/connections/{conn_id}/fill", json={"table": "users", "count": 10})
        job_id = res.json()["job_id"]
        for _ in range(50):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] != "running":
                break
        assert job["status"] == "done", job.get("error")
        assert job["result"]["rows_inserted"] == 10
        rows = client.get(f"/api/connections/{conn_id}/tables/users/rows?limit=5").json()
        assert rows["total"] == 10
        assert len(rows["rows"]) == 5

    def test_query_rejects_non_select(self, client: TestClient, conn_id: str) -> None:
        res = client.post(f"/api/connections/{conn_id}/query", json={"sql": "DROP TABLE users"})
        assert res.status_code == 422


class TestConfig:
    def test_yaml_roundtrip(self, client: TestClient) -> None:
        yaml_text = "db_path: app.db\ntables:\n  - name: users\n    count: 5\n    columns:\n      - name: email\n        generator: email\n"
        res = client.post("/api/config/parse", json={"yaml": yaml_text})
        body = res.json()
        assert body["valid"] is True
        assert body["config"]["tables"][0]["columns"][0]["generator"] == "email"

    def test_unknown_generator_passes_load_config(self, client: TestClient) -> None:
        """Contract boundary: load_config validates structure, not generator names.

        Unknown generators surface later — UnknownGeneratorError at fill time
        (GENERATOR_MAP lookup) or as violations in the heal lab.
        """
        res = client.post(
            "/api/config/parse",
            json={
                "yaml": (
                    "db_path: app.db\ntables:\n  - name: users\n    columns:\n"
                    "      - name: x\n        generator: not_a_generator_xyz\n"
                )
            },
        )
        body = res.json()
        assert body["valid"] is True
        assert body["config"]["tables"][0]["columns"][0]["generator"] == "not_a_generator_xyz"

    def test_missing_connection_target_rejected(self, client: TestClient) -> None:
        res = client.post(
            "/api/config/parse",
            json={"yaml": "tables:\n  - name: users\n    columns:\n      - name: x\n        generator: email\n"},
        )
        body = res.json()
        assert body["valid"] is False
        assert "db_path" in body["error"]

    def test_broken_yaml_syntax(self, client: TestClient) -> None:
        res = client.post("/api/config/parse", json={"yaml": ":\n: :\n["})
        assert res.json()["valid"] is False


class TestAiTestConnection:
    """/api/ai/test-connection — friendly connectivity probe per backend.

    Ollama/LM Studio need NO API key; the probe URL must be ``{base}/models``
    (base already ends in ``/v1``). Probing ``/models`` on the bare host
    returns 404 on Ollama — that bug made a healthy local server look dead.
    """

    def test_local_probe_hits_v1_models_and_lists_models(self, client, monkeypatch) -> None:
        pytest.importorskip("sqlseed_ai")
        import httpx

        seen: dict[str, object] = {}

        class FakeResp:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"data": [{"id": "gemma4:31b-cloud"}]}

        def fake_get(url: str, **kwargs: object) -> FakeResp:
            seen["url"] = url
            return FakeResp()

        monkeypatch.setattr(httpx, "get", fake_get)
        client.post("/api/ai/config", json={"backend": "ollama"})
        try:
            body = client.post("/api/ai/test-connection").json()
            assert body["ok"] is True
            assert seen["url"] == "http://localhost:11434/v1/models"
            assert body["models"] == ["gemma4:31b-cloud"]
            assert "无需 API Key" in body["message"]
            assert "gemma4:31b-cloud" in body["message"]
        finally:
            client.post("/api/ai/config", json={})

    def test_online_backend_without_key_reports_friendly(self, client, monkeypatch) -> None:
        pytest.importorskip("sqlseed_ai")
        for var in ("SQLSEED_AI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        client.post("/api/ai/config", json={"backend": "google_ai_studio"})
        try:
            body = client.post("/api/ai/test-connection").json()
            assert body["ok"] is False
            assert "API Key" in body["message"]
        finally:
            client.post("/api/ai/config", json={})

    def test_openai_compat_probe_url_gets_slash(self, client, monkeypatch) -> None:
        """base_url without trailing slash must still probe ``.../v1/models``."""
        pytest.importorskip("sqlseed_ai")
        import httpx

        seen: dict[str, object] = {}

        class FakeResp:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"data": []}

        def fake_get(url: str, **kwargs: object) -> FakeResp:
            seen["url"] = url
            return FakeResp()

        monkeypatch.setattr(httpx, "get", fake_get)
        client.post(
            "/api/ai/config",
            json={"backend": "openai_compat", "base_url": "https://openrouter.ai/api/v1", "api_key": "sk-test"},
        )
        try:
            body = client.post("/api/ai/test-connection").json()
            assert body["ok"] is True
            assert seen["url"] == "https://openrouter.ai/api/v1/models"
        finally:
            client.post("/api/ai/config", json={})


class TestPreviewColumnConfig:
    def test_preview_null_ratio_is_fraction(self, client: TestClient, conn_id: str) -> None:
        """Contract the frontend must honor: null_ratio is a 0–1 fraction.

        The genform UI collects a 0–100 percent and must divide by 100
        before sending (ColumnConfig.null_ratio has le=1.0).
        """
        res = client.post(
            f"/api/connections/{conn_id}/preview",
            json={"table": "users", "count": 3, "columns": {"email": {"generator": "email", "null_ratio": 0.5}}},
        )
        assert res.status_code == 200, res.text


@pytest.mark.parametrize("endpoint", ["validate", "repair"])
class TestHeal:
    def test_validate_reports_violations(self, client: TestClient, conn_id: str, endpoint: str) -> None:
        pytest.importorskip("sqlseed_ai")
        yaml_text = (
            "db_path: x.db\ntables:\n  - name: orders\n    count: 10\n"
            "    columns:\n      - name: amount\n        generator: random_float\n        params: {min_value: -10.0, max_value: -5.0}\n"
        )
        res = client.post(f"/api/connections/{conn_id}/heal/{endpoint}", json={"yaml": yaml_text})
        body = res.json()
        assert body["ok"] is True

    def test_validate_clean_config(self, client: TestClient, conn_id: str, endpoint: str) -> None:
        pytest.importorskip("sqlseed_ai")
        yaml_text = "db_path: x.db\ntables:\n  - name: orders\n    count: 10\n"
        res = client.post(f"/api/connections/{conn_id}/heal/{endpoint}", json={"yaml": yaml_text})
        assert res.json()["ok"] is True
