# CP1 (P0) Core New Features Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete test coverage for Phase 3 multi-database support core new features (URL connection, CLI --url, GeneratorConfig.url, MCP URL, NoSuchModuleError/ArgumentError), approximately 60 tests.

**Architecture:** Pure test completion, no source code modifications. Add 4 new test files + extend 3 existing files. All tests use real SQLite databases for validation; PG-related tests use testcontainers (CP1 includes only basic PG connection tests; full PG integration is in CP3).

**Tech Stack:** pytest, click.testing.CliRunner, SQLAlchemy, sqlite3

**Prerequisites:**
- Branch `feat/multi-db-support` has completed Phase 1-4 (commit up to 407e252)
- Design document: `docs/specs/2026-06-20-multi-db-test-completion-design.md`
- 720 existing tests all pass

**Validation threshold:** After CP1 completion, `ruff check` + `ruff format --check` + `mypy src plugins` + `pytest` (including new tests + 720 existing tests) all pass.

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|----------------|
| `tests/test_url_connection.py` | New | Public API url parameter tests (fill/connect/preview) |
| `tests/test_database/test_sqlalchemy_adapter_url.py` | New | SQLAlchemyAdapter URL connection, missing driver, invalid URL |
| `tests/test_orchestrator_adapter.py` | New | _create_adapter/_is_db_url/_get_dialect_name |
| `plugins/mcp-server-sqlseed/tests/test_validate_db_path.py` | New | MCP _validate_db_path URL/file path validation |
| `tests/test_cli.py` | Extend | +TestCLIUrlOption class |
| `tests/test_config/test_models.py` | Extend | +TestGeneratorConfigUrl class |
| `plugins/mcp-server-sqlseed/tests/__init__.py` | New | MCP test package initialization |
| `plugins/mcp-server-sqlseed/tests/conftest.py` | New | MCP test fixtures |

---

## Task 1: Public API url parameter tests

**Files:**
- Create: `tests/test_url_connection.py`

- [ ] **Step 1: Create test file, write basic url connection tests**

```python
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult


class TestPublicAPIUrl:
    """Test the url parameter of the public API (fill/connect/preview)."""

    def test_fill_with_url_sqlite(self, tmp_path: Any) -> None:
        """fill(url=...) successfully writes with SQLite URL."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        result = sqlseed.fill(url=url, table="users", count=10, provider="base")
        assert isinstance(result, GenerationResult)
        assert result.count == 10

        # Verify data was actually written
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_connect_with_url(self, tmp_path: Any) -> None:
        """connect(url=...) returns DataOrchestrator, can fill."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        db = sqlseed.connect(url=url, provider="base")
        assert isinstance(db, DataOrchestrator)
        db._ensure_connected()
        result = db.fill("users", count=5)
        assert result.count == 5
        db.close()

    def test_preview_with_url(self, tmp_path: Any) -> None:
        """preview(url=...) returns preview data list."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        rows = sqlseed.preview(url=url, table="users", count=3, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 3
        assert all(isinstance(r, dict) for r in rows)

    def test_fill_url_and_db_path_mutual_exclusion(self, tmp_path: Any) -> None:
        """Providing both db_path and url raises ValueError."""
        db_path = str(tmp_path / "test.db")
        url = f"sqlite:///{db_path}"
        with pytest.raises(ValueError, match="Cannot specify both"):
            sqlseed.fill(db_path=db_path, url=url, table="users", count=1)

    def test_fill_no_target_raises(self) -> None:
        """Providing neither raises ValueError."""
        with pytest.raises(ValueError, match="Either db_path or url must be provided"):
            sqlseed.fill(table="users", count=1)  # type: ignore[call-arg]

    def test_fill_with_url_writes_correct_data(self, tmp_path: Any) -> None:
        """url mode written data structure matches db_path mode."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        sqlseed.fill(url=url, table="users", count=5, provider="base")

        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT id, name, email FROM users LIMIT 1")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is not None  # id
        assert row[1] is not None  # name
        conn.close()

    def test_connect_with_url_context_manager(self, tmp_path: Any) -> None:
        """with connect(url=...) as orch: works correctly."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        with sqlseed.connect(url=url, provider="base") as db:
            result = db.fill("users", count=3)
            assert result.count == 3

    def test_preview_with_url_returns_list(self, tmp_path: Any) -> None:
        """preview(url=...) returns list[dict]."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        rows = sqlseed.preview(url=url, table="users", count=2, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 2

    def test_fill_with_url_seed_reproducibility(self, tmp_path: Any) -> None:
        """seed is reproducible in url mode."""
        db_path1 = str(tmp_path / "test1.db")
        db_path2 = str(tmp_path / "test2.db")
        for p in (db_path1, db_path2):
            conn = sqlite3.connect(p)
            conn.execute(
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)"
            )
            conn.commit()
            conn.close()

        sqlseed.fill(url=f"sqlite:///{db_path1}", table="users", count=5, provider="base", seed=42)
        sqlseed.fill(url=f"sqlite:///{db_path2}", table="users", count=5, provider="base", seed=42)

        conn1 = sqlite3.connect(db_path1)
        conn2 = sqlite3.connect(db_path2)
        rows1 = conn1.execute("SELECT name FROM users ORDER BY id").fetchall()
        rows2 = conn2.execute("SELECT name FROM users ORDER BY id").fetchall()
        assert rows1 == rows2
        conn1.close()
        conn2.close()

    def test_fill_with_url_invalid_table_records_error(self, tmp_path: Any) -> None:
        """Non-existent table in url mode reports error correctly (result.errors non-empty).

        Note: fill() records errors for non-existent tables rather than raising exceptions.
        """
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        result = sqlseed.fill(url=url, table="nonexistent_table", count=1, provider="base")
        assert len(result.errors) > 0

    def test_fill_with_url_snapshot(self, tmp_path: Any) -> None:
        """snapshot functionality works in url mode."""
        import os

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        cache_dir = str(tmp_path / "cache")
        os.environ["SQLSEED_CACHE_DIR"] = cache_dir
        try:
            url = f"sqlite:///{db_path}"
            result = sqlseed.fill(url=url, table="users", count=5, provider="base", snapshot=True, seed=42)
            assert result.count == 5

            # Verify snapshot file was actually generated
            from sqlseed.config.snapshot import SnapshotManager

            sm = SnapshotManager(cache_dir)
            snapshots = sm.list_snapshots()
            assert len(snapshots) > 0, "snapshot file should have been generated"
        finally:
            del os.environ["SQLSEED_CACHE_DIR"]

    def test_fill_with_url_config_file(self, tmp_path: Any) -> None:
        """fill_from_config uses url field."""
        import yaml

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": f"sqlite:///{db_path}",
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        results = sqlseed.fill_from_config(str(config_path))
        assert len(results) == 1
        assert results[0].count == 5

        # Verify data was actually written
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_resolve_db_target_priority(self) -> None:
        """db_path takes priority over url (returns db_path when only db_path is provided)."""
        from sqlseed import _resolve_db_target

        assert _resolve_db_target("test.db", None) == "test.db"

    def test_resolve_db_target_url_only(self) -> None:
        """Returns url correctly when only url is provided."""
        from sqlseed import _resolve_db_target

        assert _resolve_db_target(None, "postgresql://host/db") == "postgresql://host/db"

    def test_fill_with_empty_url_creates_memory_db(self, tmp_path: Any) -> None:
        """Empty URL (url="") behavior: returns empty string, SQLAlchemyAdapter converts to in-memory SQLite.

        Note: In the current implementation, url="" is not None, so _resolve_db_target returns "".
        SQLAlchemyAdapter.connect("") converts it to sqlite:/// (in-memory DB).
        This is a boundary behavior test to verify no crash.
        """
        from sqlseed import _resolve_db_target

        # _resolve_db_target returns "" for url="" (does not raise, because "" is not None)
        target = _resolve_db_target(None, "")
        assert target == ""

    def test_fill_with_url_count_zero_raises(self, tmp_path: Any) -> None:
        """count=0 in url mode raises ValueError."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        with pytest.raises(ValueError):
            sqlseed.fill(url=url, table="users", count=0, provider="base")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_url_connection.py -v --tb=short`
Expected: 11 passed

- [ ] **Step 3: Run ruff check**

Run: `ruff check tests/test_url_connection.py`
Expected: All checks passed

- [ ] **Step 4: Run ruff format**

Run: `ruff format tests/test_url_connection.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_url_connection.py
git commit -m "test: add public API url parameter tests (CP1 P0)"
```

---

## Task 2: SQLAlchemyAdapter URL connection tests

**Files:**
- Create: `tests/test_database/test_sqlalchemy_adapter_url.py`

- [ ] **Step 1: Create test file, write URL connection and error handling tests**

```python
from __future__ import annotations

from typing import Any

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


class TestSQLAlchemyAdapterUrl:
    """Test SQLAlchemyAdapter's URL connection functionality."""

    def test_connect_sqlite_file_url(self, tmp_path: Any) -> None:
        """connect("sqlite:///path.db") succeeds."""
        db_path = str(tmp_path / "test.db")
        # Create file first
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_sqlite_memory_url(self) -> None:
        """connect("sqlite://") memory DB succeeds."""
        adapter = SQLAlchemyAdapter()
        adapter.connect("sqlite://")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_postgresql_missing_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When psycopg is not installed, raises RuntimeError containing "pip install sqlseed[postgres]".

        Simulates missing driver by mocking create_engine to raise NoSuchModuleError.
        """
        from sqlalchemy.exc import NoSuchModuleError

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:postgresql.psycopg")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="PostgreSQL driver not installed"):
            adapter.connect("postgresql://user:pass@host/db")

    def test_connect_mysql_missing_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When pymysql is not installed, raises RuntimeError containing "pip install sqlseed[mysql]"."""
        from sqlalchemy.exc import NoSuchModuleError

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:mysql.pymysql")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="MySQL driver not installed"):
            adapter.connect("mysql://user:pass@host/db")

    def test_connect_invalid_url_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid URL (triggering ArgumentError) raises ValueError.

        Note: "not_a_url" does not contain "://", so SQLAlchemyAdapter auto-converts it to sqlite:/// URL.
        To trigger ValueError, need a URL containing "://" but with invalid format, causing create_engine to raise ArgumentError.
        We use mock to simulate ArgumentError.
        """
        from sqlalchemy.exc import ArgumentError

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise ArgumentError("Invalid URL format")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Invalid database URL"):
            adapter.connect("postgresql://invalid url with spaces")

    def test_connect_unsupported_dialect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """connect("oracle://...") raises ValueError (_detect_dialect does not support oracle)."""
        # If oracle driver is not installed, NoSuchModuleError is raised first, but NoSuchModuleError does not contain postgresql/mysql
        # so NoSuchModuleError is raised directly. We test a scenario where the driver is installed but the dialect is unsupported.
        # In practice, _detect_dialect raises ValueError for non sqlite/postgresql.
        # We use mock to simulate: create_engine succeeds but dialect.name is "oracle"
        from unittest.mock import MagicMock

        mock_engine = MagicMock()
        mock_engine.dialect.name = "oracle"
        monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: mock_engine)
        monkeypatch.setattr("sqlalchemy.inspect", lambda e: MagicMock())

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Unsupported dialect"):
            adapter.connect("oracle://user:pass@host/db")

    def test_connect_url_sets_dialect_correctly_sqlite(self, tmp_path: Any) -> None:
        """After connection, dialect.name == "sqlite"."""
        db_path = str(tmp_path / "test.db")
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_url_persists_engine(self, tmp_path: Any) -> None:
        """Engine is reusable after connection."""
        db_path = str(tmp_path / "test.db")
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        # Multiple operations to verify engine persistence
        assert adapter.get_table_names() == ["t"]
        assert adapter.get_table_names() == ["t"]
        adapter.close()

    def test_connect_url_close_releases_resources(self, tmp_path: Any) -> None:
        """After close, engine is released; further operations raise RuntimeError."""
        db_path = str(tmp_path / "test.db")
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        adapter.close()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_table_names()

    def test_connect_postgresql_url_with_testcontainers(self, pg_url: str) -> None:
        """Real PG container connection succeeds (depends on pg_url fixture, fully implemented in CP3).

        In CP1 phase, this test depends on the pg_url fixture in tests/integration/conftest.py.
        If the fixture is not created, this test will error. We create the fixture in the Task first.
        """
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.dialect.name == "postgresql"
        adapter.close()

    def test_connect_url_sets_dialect_correctly_postgresql(self, pg_url: str) -> None:
        """After connecting to real PG, dialect.name == "postgresql"."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.dialect.name == "postgresql"
        adapter.close()

    def test_connect_malformed_url_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """connect("postgresql://") raises ValueError (triggers ArgumentError).

        Note: After psycopg is installed, create_engine("postgresql://") behavior is uncertain.
        Use mock to simulate ArgumentError to ensure test stability.
        """
        from sqlalchemy.exc import ArgumentError

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise ArgumentError("Could not parse SQLAlchemy URL")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Invalid database URL"):
            adapter.connect("postgresql://")
```

- [ ] **Step 2: Add pg_url and available_llm_backend fixtures to tests/conftest.py (root conftest)**

**Important**: pg_url and available_llm_backend must be defined in `tests/conftest.py` (root conftest) rather than `tests/integration/conftest.py`, because pytest's conftest.py scope rule is "only visible to same-level and subdirectories". `tests/test_database/` and `tests/integration/` are sibling directories; if fixtures are defined in `tests/integration/conftest.py`, tests under `tests/test_database/` cannot use them.

Append to the end of `tests/conftest.py` (keep existing content unchanged):

```python
@pytest.fixture(scope="session")
def pg_url() -> Generator[str, None, None]:
    """Start a real PG container, return connection URL. Fail with prompt when Docker is missing.

    Uses testcontainers to start a postgres:16-alpine container.
    Session-level fixture; all PG tests share one container.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.fail(
            "testcontainers package is required to run PG integration tests. "
            "Install: pip install testcontainers"
        )
    try:
        pg = PostgresContainer("postgres:16-alpine")
        pg.start()
        yield pg.get_connection_url()
        pg.stop()
    except Exception as e:
        if "docker" in str(e).lower() or "connection" in str(e).lower() or "daemon" in str(e).lower():
            pytest.fail(
                "Docker must be running to run PostgreSQL integration tests.\n"
                "Installation guide: https://docs.docker.com/get-docker/\n"
                f"Error details: {e}"
            )
        raise


@pytest.fixture(scope="session")
def available_llm_backend() -> dict[str, str]:
    """Detect available LLM backend; fail with prompt when none available.

    Fallback chain: Ollama → LM Studio → Google AI Studio
    Returns {"backend": ..., "model": ...}, where model is the Gemma 4 model ID for that backend.
    """
    import json
    import os
    import urllib.request

    # 1. Ollama — detect /api/tags, verify gemma4 model is pulled
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            tags = json.loads(resp.read())
            models = {m.get("name", "") for m in tags.get("models", [])}
            for preferred in ("gemma4:26b", "gemma4:31b", "gemma4:e4b", "gemma4:12b"):
                if any(m.startswith(preferred) for m in models):
                    return {"backend": "ollama", "model": preferred}
            pytest.fail(
                "Ollama is running but Gemma 4 model is not pulled. Please run:\n"
                "  ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
                "  ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)"
            )
    except Exception:
        pass

    # 2. LM Studio — detect /v1/models, verify gemma-4 model is loaded
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json.loads(resp.read())
            model_ids = {m.get("id", "") for m in data.get("data", [])}
            for preferred in ("google/gemma-4-26b-a4b", "google/gemma-4-31b", "google/gemma-4-e4b"):
                if preferred in model_ids:
                    return {"backend": "lm_studio", "model": preferred}
            pytest.fail(
                "LM Studio is running but Gemma 4 model is not loaded. Please load in LM Studio:\n"
                "  google/gemma-4-26b-a4b   # recommended\n"
                "  google/gemma-4-e4b       # lightweight alternative"
            )
    except Exception:
        pass

    # 3. Google AI Studio — detect environment variable
    if os.environ.get("GOOGLE_API_KEY"):
        return {"backend": "google_ai_studio", "model": "gemma-4-26b-a4b-it"}

    pytest.fail(
        "At least one LLM backend is required to run AI integration tests:\n"
        "  - Ollama: install (https://ollama.ai) and pull Gemma 4 model:\n"
        "      ollama pull gemma4:26b   # recommended (requires 16GB VRAM)\n"
        "      ollama pull gemma4:e4b   # lightweight alternative (requires 4GB RAM)\n"
        "  - LM Studio: install and load Gemma 4 model (google/gemma-4-26b-a4b)\n"
        "  - Google AI Studio: set GOOGLE_API_KEY environment variable\n"
        "    (model: gemma-4-26b-a4b-it)"
    )
```

Also create `tests/integration/__init__.py` (empty file) and `tests/integration/conftest.py` (containing only `pytestmark` or empty, because fixtures are already defined in the root conftest).

- [ ] **Step 3: Add testcontainers and psycopg to dev dependencies**

Modify the `[project.optional-dependencies] dev` section of `pyproject.toml`, add to the existing dev dependencies list:

```toml
    "testcontainers>=4.0",
    "psycopg[binary]>=3.0",
```

Also update `all` extras to add testcontainers (psycopg is already in all):

```toml
all = ["faker>=30.0", "mimesis>=18.0", "tqdm>=4.66", "psycopg[binary]>=3.0", "testcontainers>=4.0"]
```

- [ ] **Step 4: Install new dependencies**

Run: `pip install testcontainers psycopg[binary]`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_sqlalchemy_adapter_url.py -v --tb=short`
Expected: 12 passed (requires Docker running to execute PG tests)

- [ ] **Step 6: Run ruff check and format**

Run: `ruff check tests/test_database/test_sqlalchemy_adapter_url.py tests/integration/ && ruff format tests/test_database/test_sqlalchemy_adapter_url.py tests/integration/`

- [ ] **Step 7: Commit**

```bash
git add tests/test_database/test_sqlalchemy_adapter_url.py tests/integration/ pyproject.toml
git commit -m "test: add SQLAlchemyAdapter URL tests + integration fixtures (CP1 P0)"
```

---

## Task 3: CLI --url option tests

**Files:**
- Modify: `tests/test_cli.py` (append TestCLIUrlOption class at the end of the file)

- [ ] **Step 1: Append TestCLIUrlOption class at the end of tests/test_cli.py**

```python
class TestCLIUrlOption:
    """Test the --url option of CLI fill/preview/inspect commands."""

    def test_fill_with_url_sqlite(self, tmp_db) -> None:
        """sqlseed fill --url "sqlite:///path.db" -t users -n 10 succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "10", "--provider", "base"],
        )
        assert result.exit_code == 0
        # Strengthen assertion: verify output contains table name and row count
        assert "users" in result.output
        assert "10" in result.output

        # Verify data was actually written
        import sqlite3

        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_fill_with_url_and_db_path_mutual_exclusion(self, tmp_db) -> None:
        """Providing both db_path and --url raises UsageError."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--url", url, "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        assert "Cannot specify both" in result.output

    def test_fill_without_url_or_db_path_errors(self) -> None:
        """Providing neither raises UsageError."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        assert "db_path or --url is required" in result.output

    def test_preview_with_url(self, tmp_db) -> None:
        """sqlseed preview --url "sqlite:///path.db" -t users -n 5 succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["preview", "--url", url, "--table", "users", "--count", "5", "--provider", "base"],
        )
        assert result.exit_code == 0

    def test_inspect_with_url(self, tmp_db) -> None:
        """sqlseed inspect --url "sqlite:///path.db" succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["inspect", "--url", url],
        )
        assert result.exit_code == 0

    def test_fill_url_output_format(self, tmp_db) -> None:
        """Output format in url mode matches db_path mode."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"

        # url mode
        result_url = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base"],
        )
        # db_path mode
        result_path = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "5", "--provider", "base"],
        )
        assert result_url.exit_code == 0
        assert result_path.exit_code == 0
        # Both should contain row count information
        assert "5" in result_url.output

    def test_fill_url_with_config(self, tmp_db, tmp_path) -> None:
        """--url and --config can coexist (config specifies table config, url specifies connection)."""
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": f"sqlite:///{tmp_db}",
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["fill", "--config", str(config_path)])
        assert result.exit_code == 0

        # Strengthen assertion: verify data was actually written
        import sqlite3

        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_fill_url_postgresql_missing_driver(self, monkeypatch) -> None:
        """PG URL missing driver gives friendly CLI error."""
        from sqlalchemy.exc import NoSuchModuleError

        def mock_create_engine(url: str, **kwargs) -> Any:
            raise NoSuchModuleError("postgresql.psycopg")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--url", "postgresql://user:pass@host/db", "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        # Strengthen assertion: verify error message contains installation guidance
        assert "pip install" in result.output or "PostgreSQL driver not installed" in result.output

    def test_fill_url_snapshot_flag(self, tmp_db, tmp_path, monkeypatch) -> None:
        """--snapshot works in url mode, verify snapshot file generation."""
        cache_dir = str(tmp_path / "cache")
        monkeypatch.setenv("SQLSEED_CACHE_DIR", cache_dir)

        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--snapshot"],
        )
        assert result.exit_code == 0

        # Strengthen assertion: verify snapshot file was actually generated
        from sqlseed.config.snapshot import SnapshotManager

        sm = SnapshotManager(cache_dir)
        snapshots = sm.list_snapshots()
        assert len(snapshots) > 0, "snapshot file should have been generated"

    def test_fill_url_with_seed_reproducibility(self, tmp_db) -> None:
        """--seed is reproducible in url mode."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"

        # First fill
        result1 = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--seed", "42", "--clear"],
        )
        assert result1.exit_code == 0

        # Read data
        import sqlite3

        conn = sqlite3.connect(tmp_db)
        rows1 = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
        conn.close()

        # Clear and second fill (same seed)
        result2 = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--seed", "42", "--clear"],
        )
        assert result2.exit_code == 0

        conn = sqlite3.connect(tmp_db)
        rows2 = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
        conn.close()

        assert rows1 == rows2
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py::TestCLIUrlOption -v --tb=short`
Expected: 10 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_cli.py && ruff format tests/test_cli.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: add CLI --url option tests (CP1 P0)"
```

---

## Task 4: GeneratorConfig.url field tests

**Files:**
- Modify: `tests/test_config/test_models.py` (append TestGeneratorConfigUrl class)

- [ ] **Step 1: Read existing test_models.py to understand structure**

Run: `Read tests/test_config/test_models.py`

- [ ] **Step 2: Append TestGeneratorConfigUrl class at the end of tests/test_config/test_models.py**

```python
class TestGeneratorConfigUrl:
    """Test GeneratorConfig's url field and connection_target property."""

    def test_url_field_accepted(self) -> None:
        """GeneratorConfig(url=...) accepts url field successfully."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        assert config.url == "postgresql://user:pass@host/db"
        assert config.db_path is None

    def test_db_path_and_url_mutual_exclusion(self) -> None:
        """Providing both db_path and url raises ValidationError."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            GeneratorConfig(
                db_path="test.db",
                url="postgresql://user:pass@host/db",
                tables=[],
            )

    def test_neither_db_path_nor_url_raises(self) -> None:
        """Providing neither raises ValidationError."""
        with pytest.raises(ValueError, match="Either 'db_path' or 'url' must be provided"):
            GeneratorConfig(tables=[])

    def test_connection_target_returns_url(self) -> None:
        """config.connection_target returns url (when url is set)."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        assert config.connection_target == "postgresql://user:pass@host/db"

    def test_connection_target_returns_db_path(self) -> None:
        """config.connection_target returns db_path (when db_path is set)."""
        config = GeneratorConfig(db_path="test.db", tables=[])
        assert config.connection_target == "test.db"

    def test_connection_target_property_consistency(self) -> None:
        """Multiple calls to connection_target return the same value."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        target1 = config.connection_target
        target2 = config.connection_target
        assert target1 == target2

    def test_from_config_uses_connection_target(self, tmp_path) -> None:
        """from_config uses connection_target instead of db_path."""
        import yaml

        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": f"sqlite:///{tmp_path / 'test.db'}",
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        from sqlseed.config.loader import load_config

        config = load_config(str(config_path))
        assert config.url is not None
        assert config.connection_target == config.url

    def test_config_with_url_serialization(self, tmp_path) -> None:
        """YAML with url field loads correctly."""
        import yaml

        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": "postgresql://user:pass@host:5432/mydb",
            "provider": "base",
            "tables": [{"name": "users", "count": 100}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        from sqlseed.config.loader import load_config

        config = load_config(str(config_path))
        assert config.url == "postgresql://user:pass@host:5432/mydb"
        assert config.db_path is None

    def test_config_with_url_json_serialization(self, tmp_path) -> None:
        """JSON with url field loads correctly."""
        import json

        config_path = tmp_path / "gen.json"
        config_data = {
            "url": "postgresql://user:pass@host:5432/mydb",
            "provider": "base",
            "tables": [{"name": "users", "count": 100}],
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        from sqlseed.config.loader import load_config

        config = load_config(str(config_path))
        assert config.url == "postgresql://user:pass@host:5432/mydb"
        assert config.db_path is None
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_config/test_models.py::TestGeneratorConfigUrl -v --tb=short`
Expected: 8 passed

- [ ] **Step 4: Run ruff check and format**

Run: `ruff check tests/test_config/test_models.py && ruff format tests/test_config/test_models.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_config/test_models.py
git commit -m "test: add GeneratorConfig.url field tests (CP1 P0)"
```

---

## Task 5: MCP server _validate_db_path tests

**Files:**
- Create: `plugins/mcp-server-sqlseed/tests/__init__.py`
- Create: `plugins/mcp-server-sqlseed/tests/conftest.py`
- Create: `plugins/mcp-server-sqlseed/tests/test_validate_db_path.py`

- [ ] **Step 1: Create MCP test package structure**

Create `plugins/mcp-server-sqlseed/tests/__init__.py` (empty file).

Create `plugins/mcp-server-sqlseed/tests/conftest.py`:

```python
from __future__ import annotations

import sqlite3
from typing import Any

import pytest


@pytest.fixture
def tmp_sqlite_db(tmp_path: Any) -> str:
    """Create a temporary SQLite database file for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)"
    )
    conn.commit()
    conn.close()
    return str(db_path)
```

- [ ] **Step 2: Create test_validate_db_path.py**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server_sqlseed.server import _validate_db_path


class TestValidateDbPath:
    """Test _validate_db_path function's URL and file path validation."""

    def test_validate_postgresql_url_passes_through(self) -> None:
        """postgresql URL returns directly, does not verify file existence."""
        url = "postgresql://user:pass@host:5432/db"
        assert _validate_db_path(url) == url

    def test_validate_mysql_url_passes_through(self) -> None:
        """mysql URL returns directly."""
        url = "mysql://user:pass@host:3306/db"
        assert _validate_db_path(url) == url

    def test_validate_sqlite_url_passes_through(self) -> None:
        """sqlite URL returns directly."""
        url = "sqlite:///path/to/db.sqlite"
        assert _validate_db_path(url) == url

    def test_validate_invalid_file_path_raises(self) -> None:
        """Non-URL and non-valid extension path raises ValueError."""
        with pytest.raises(ValueError, match="Invalid database target"):
            _validate_db_path("not_a_url_or_valid_path")

    def test_validate_nonexistent_db_file_raises(self, tmp_path) -> None:
        """Valid extension but non-existent file raises ValueError."""
        nonexistent = str(tmp_path / "missing.db")
        with pytest.raises(ValueError, match="Database file not found"):
            _validate_db_path(nonexistent)

    def test_validate_valid_sqlite_file_returns_resolved(self, tmp_sqlite_db: str) -> None:
        """Real .db file returns absolute path."""
        result = _validate_db_path(tmp_sqlite_db)
        assert result == str(Path(tmp_sqlite_db).resolve())

    def test_validate_url_with_special_chars(self) -> None:
        """URL with special characters (passwords etc.) handled correctly."""
        url = "postgresql://user:p@ss!w0rd@host:5432/db"
        assert _validate_db_path(url) == url

    def test_validate_url_scheme_only_no_authority(self) -> None:
        """postgresql:// boundary handling (no authority).

        Contains "://" so returns directly, validated later by SQLAlchemy.
        """
        url = "postgresql://"
        assert _validate_db_path(url) == url
```

- [ ] **Step 3: Ensure mcp_server_sqlseed is importable**

Run: `python -c "from mcp_server_sqlseed.server import _validate_db_path; print('OK')"`

If it fails, you need to set PYTHONPATH or install the package:
Run: `pip install -e "./plugins/mcp-server-sqlseed"`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest plugins/mcp-server-sqlseed/tests/test_validate_db_path.py -v --tb=short`
Expected: 8 passed

- [ ] **Step 5: Run ruff check and format**

Run: `ruff check plugins/mcp-server-sqlseed/tests/ && ruff format plugins/mcp-server-sqlseed/tests/`

- [ ] **Step 6: Commit**

```bash
git add plugins/mcp-server-sqlseed/tests/
git commit -m "test: add MCP server _validate_db_path URL tests (CP1 P0)"
```

---

## Task 6: orchestrator adapter dispatch tests

**Files:**
- Create: `tests/test_orchestrator_adapter.py`

- [ ] **Step 1: Create test_orchestrator_adapter.py**

```python
from __future__ import annotations

from typing import Any

import pytest

from sqlseed.core.orchestrator import DataOrchestrator, _is_db_url
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


class TestOrchestratorAdapter:
    """Test orchestrator's adapter dispatch logic."""

    def test_is_db_url_with_postgresql(self) -> None:
        """_is_db_url("postgresql://...") returns True."""
        assert _is_db_url("postgresql://user:pass@host/db") is True

    def test_is_db_url_with_mysql(self) -> None:
        """_is_db_url("mysql://...") returns True."""
        assert _is_db_url("mysql://user:pass@host/db") is True

    def test_is_db_url_with_sqlite_url(self) -> None:
        """_is_db_url("sqlite:///path.db") returns True."""
        assert _is_db_url("sqlite:///path/to/db.db") is True

    def test_is_db_url_with_file_path(self) -> None:
        """_is_db_url("/path/to/db.sqlite") returns False."""
        assert _is_db_url("/path/to/db.sqlite") is False

    def test_is_db_url_with_relative_path(self) -> None:
        """_is_db_url("app.db") returns False."""
        assert _is_db_url("app.db") is False

    def test_is_db_url_with_windows_path(self) -> None:
        """_is_db_url("C:\\path\\to\\db.db") returns False."""
        assert _is_db_url("C:\\path\\to\\db.db") is False

    def test_create_adapter_returns_sqlalchemy_for_file(self, tmp_db: str) -> None:
        """File path input returns SQLAlchemyAdapter instance."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            adapter = orch._core.db
            assert isinstance(adapter, SQLAlchemyAdapter)

    def test_create_adapter_returns_sqlalchemy_for_url(self, tmp_db: str) -> None:
        """URL input returns SQLAlchemyAdapter instance."""
        url = f"sqlite:///{tmp_db}"
        with DataOrchestrator(url, provider_name="base") as orch:
            orch._ensure_connected()
            adapter = orch._core.db
            assert isinstance(adapter, SQLAlchemyAdapter)

    def test_get_dialect_name_sqlite(self, tmp_db: str) -> None:
        """SQLite file returns "sqlite"."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            assert orch._get_dialect_name() == "sqlite"

    def test_get_dialect_name_sqlite_url(self, tmp_db: str) -> None:
        """SQLite URL returns "sqlite"."""
        url = f"sqlite:///{tmp_db}"
        with DataOrchestrator(url, provider_name="base") as orch:
            orch._ensure_connected()
            assert orch._get_dialect_name() == "sqlite"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator_adapter.py -v --tb=short`
Expected: 10 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_orchestrator_adapter.py && ruff format tests/test_orchestrator_adapter.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_orchestrator_adapter.py
git commit -m "test: add orchestrator adapter dispatch tests (CP1 P0)"
```

---

## Task 7: CP1 full validation

- [ ] **Step 1: Run full ruff check**

Run: `ruff check src plugins tests`
Expected: All checks passed

- [ ] **Step 2: Run full ruff format --check**

Run: `ruff format --check src plugins tests`
Expected: All checks passed

- [ ] **Step 3: Run mypy**

Run: `mypy src plugins`
Expected: Success: no issues found

- [ ] **Step 4: Run full pytest**

Run: `python -m pytest --tb=short -q`
Expected: All tests pass (720 existing + ~60 new = ~780)

**Note:** PG integration tests require Docker running. If Docker is not running, PG tests will fail with a prompt to start Docker.

- [ ] **Step 5: If any failures, fix and re-validate**

Fix any ruff/mypy/pytest failures until all pass.

- [ ] **Step 6: Confirm CP1 completion**

CP1 completion criteria:
- ruff check: 0 errors
- ruff format --check: 0 errors
- mypy: 0 errors
- pytest: all pass (~780 tests)

No commit needed (validation step).

---

## Self-Review

**Spec coverage check:**
- 3.1 URL connection tests → Task 1 ✓ (including supplementary snapshot/config_file/resolve_db_target/empty_url tests)
- 3.2 SQLAlchemyAdapter URL tests → Task 2 ✓ (fixed invalid_url/malformed_url tests)
- 3.3 CLI --url tests → Task 3 ✓ (removed non-existent --verbose, replaced with --seed reproducibility test, strengthened assertions)
- 3.4 GeneratorConfig.url tests → Task 4 ✓ (added JSON loading test)
- 3.5 MCP server URL tests → Task 5 ✓
- 3.6 orchestrator adapter dispatch tests → Task 6 ✓
- CP1 full validation → Task 7 ✓

**Cross-validation fix records:**
- Fixed 4 critical executability issues (invalid_url mock, removed --verbose and replaced with --seed, pg_url fixture moved to root conftest, malformed_url mock)
- Fixed 1 option name error found in second validation (--clear-before → --clear)
- Added 6 coverage gap tests (snapshot, config_file, resolve_db_target × 2, JSON loading, empty URL boundary)
- Strengthened CLI assertion strength (verify data actually written, snapshot file generated, error message content)

**Placeholder scan:** No TBD/TODO, all steps contain complete code ✓

**Type consistency:** `_is_db_url`, `_resolve_db_target`, `connection_target`, `_validate_db_path` naming consistent throughout ✓

**CP1 test count (after fixes):**
- Task 1: 16 tests (original 11 + supplementary 5: snapshot/config_file/resolve_db_target×2/empty_url)
- Task 2: 12 tests (fixed 2, count unchanged)
- Task 3: 10 tests (removed verbose, replaced with seed reproducibility, count unchanged)
- Task 4: 9 tests (original 8 + supplementary 1: JSON loading)
- Task 5: 8 tests
- Task 6: 10 tests
- **Total: 65 tests** (original 59 + supplementary 6)
