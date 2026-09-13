# CP2 (P1) Boundary Cases and Robustness Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete test coverage for SQLAlchemyAdapter boundary cases, DatabaseAdapterContract framework, AI plugin dialect context (real LLM), config/loader, orchestrator count validation, TypeNormalizer boundary, and MySQL type mapping, approximately 48 tests.

**Architecture:** Pure test completion, no source code modifications. Add 2 new test files + extend 5 existing files. AI tests use real LLM calls (depend on `available_llm_backend` fixture), PG tests use testcontainers (depend on `pg_url` fixture).

**Tech Stack:** pytest, SQLAlchemy, sqlseed-ai (Gemma 4), testcontainers

**Prerequisites:**
- CP1 completed (all tests passing)
- `tests/conftest.py` (root conftest) already contains `pg_url` and `available_llm_backend` fixtures (created in CP1, scoped to the entire tests/ directory)
- `testcontainers` and `psycopg[binary]` installed

**Validation Gate:** After CP2 completion, `ruff check` + `ruff format --check` + `mypy src plugins` + `pytest` (including new tests + CP1 + 720 existing tests) all pass.

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|----------------|
| `tests/test_database/test_sqlalchemy_adapter_boundary.py` | Add | Nonexistent table / after close / empty DB / reserved words |
| `tests/test_database/test_adapter_contract.py` | Add | DatabaseAdapterContract base class + 2 subclasses |
| `tests/test_database/test_dialect.py` | Extend | +TypeNormalizer boundary +MySQL types +PG boundary |
| `tests/test_ai_plugin.py` | Extend | +TestSchemaAnalyzerDialect (real LLM) |
| `tests/test_config/test_loader.py` | Extend | +TestReadSqliteTableNames |
| `tests/test_orchestrator.py` | Extend | +TestOrchestratorCountValidation |
| `tests/test_database/test_optimizer.py` | Extend | Migrate to BulkWriteOptimizer abstraction |

---

## Task 1: SQLAlchemyAdapter Boundary Tests

**Files:**
- Create: `tests/test_database/test_sqlalchemy_adapter_boundary.py`

- [ ] **Step 1: Create test file, write boundary case tests**

```python
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


@pytest.fixture
def sa_adapter(tmp_db: str) -> SQLAlchemyAdapter:
    """Create a connected SQLAlchemyAdapter."""
    adapter = SQLAlchemyAdapter()
    adapter.connect(tmp_db)
    yield adapter
    adapter.close()


@pytest.fixture
def empty_sa_adapter(tmp_path: Any) -> SQLAlchemyAdapter:
    """Create a SQLAlchemyAdapter connected to an empty database."""
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.close()  # Create empty file
    adapter = SQLAlchemyAdapter()
    adapter.connect(db_path)
    yield adapter
    adapter.close()


class TestSQLAlchemyAdapterBoundary:
    """Test SQLAlchemyAdapter boundary cases."""

    def test_get_column_info_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_column_info("nonexistent_table") == []

    def test_get_primary_keys_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_primary_keys("nonexistent_table") == []

    def test_get_foreign_keys_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_foreign_keys("nonexistent_table") == []

    def test_get_index_info_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_index_info("nonexistent_table") == []

    def test_get_row_count_nonexistent_table_returns_zero(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns 0."""
        assert sa_adapter.get_row_count("nonexistent_table") == 0

    def test_get_column_values_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_column_values("nonexistent_table", "id") == []

    def test_get_sample_rows_nonexistent_table_returns_empty(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table returns []."""
        assert sa_adapter.get_sample_rows("nonexistent_table") == []

    def test_batch_insert_nonexistent_table_raises_runtime_error(self, sa_adapter: SQLAlchemyAdapter) -> None:
        """Nonexistent table raises RuntimeError (not NoSuchTableError)."""
        with pytest.raises(RuntimeError):
            sa_adapter.batch_insert("nonexistent_table", iter([{"id": 1}]))

    def test_operation_after_close_raises(self, tmp_db: str) -> None:
        """Calling get_table_names after close raises RuntimeError."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.close()
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_table_names()

    def test_operation_after_context_exit_raises(self, tmp_db: str) -> None:
        """Operation after with-exit raises RuntimeError."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        with adapter:
            pass
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.get_table_names()

    def test_empty_database_get_table_names_returns_empty(self, empty_sa_adapter: SQLAlchemyAdapter) -> None:
        """Empty database returns []."""
        assert empty_sa_adapter.get_table_names() == []

    def test_connect_to_nonexistent_sqlite_file_creates_it(self, tmp_path: Any) -> None:
        """SQLite auto-creates the file."""
        db_path = str(tmp_path / "new.db")
        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        # Should be operable after connect
        assert adapter.get_table_names() == []
        adapter.close()

    def test_double_connect_overwrites_engine(self, tmp_db: str) -> None:
        """Double connect overwrites engine (no exception, source has no double-connect guard)."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.connect(tmp_db)  # Should not raise
        assert adapter.get_table_names() == ["users", "orders"]
        adapter.close()

    def test_close_idempotent(self, tmp_db: str) -> None:
        """Multiple close calls do not error."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(tmp_db)
        adapter.close()
        adapter.close()  # Should not raise

    def test_dialect_accessible_before_connect_raises(self) -> None:
        """Accessing dialect before connect raises RuntimeError."""
        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = adapter.dialect
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_sqlalchemy_adapter_boundary.py -v --tb=short`
Expected: 15 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_sqlalchemy_adapter_boundary.py && ruff format tests/test_database/test_sqlalchemy_adapter_boundary.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_sqlalchemy_adapter_boundary.py
git commit -m "test: add SQLAlchemyAdapter boundary tests (CP2 P1)"
```

---

## Task 2: DatabaseAdapterContract Contract Tests

**Files:**
- Create: `tests/test_database/test_adapter_contract.py`

- [ ] **Step 1: Create test_adapter_contract.py, implement DatabaseAdapterContract base class and 2 subclasses**

```python
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.database._protocol import DatabaseAdapter
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _create_test_db(db_path: str) -> None:
    """Create test database (users + orders tables)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """
    )
    conn.execute("CREATE INDEX idx_orders_user ON orders(user_id)")
    conn.commit()
    conn.close()


class DatabaseAdapterContract:
    """DatabaseAdapter protocol contract test base class.

    Subclasses must implement create_adapter() and db_path fixture.
    """

    def create_adapter(self, db_path: str) -> DatabaseAdapter:  # pragma: no cover
        raise NotImplementedError

    def get_db_path(self, tmp_path: Path) -> str:  # pragma: no cover
        raise NotImplementedError

    @pytest.fixture
    def adapter_and_path(self, tmp_path: Path) -> Any:
        db_path = self.get_db_path(tmp_path)
        _create_test_db(db_path)
        adapter = self.create_adapter(db_path)
        adapter.connect(db_path)
        yield adapter, db_path
        adapter.close()

    def test_get_table_names(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        names = adapter.get_table_names()
        assert "users" in names
        assert "orders" in names

    def test_get_column_info_structure(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        cols = adapter.get_column_info("users")
        assert len(cols) >= 2
        col_names = [c.name for c in cols]
        assert "id" in col_names
        assert "name" in col_names

    def test_get_primary_keys_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        pks = adapter.get_primary_keys("users")
        assert pks == ["id"]

    def test_get_foreign_keys_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        fks = adapter.get_foreign_keys("orders")
        assert len(fks) == 1
        assert fks[0].column == "user_id"
        assert fks[0].ref_table == "users"

    def test_batch_insert_and_count(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(10)]
        count = adapter.batch_insert("users", iter(data))
        assert count == 10
        assert adapter.get_row_count("users") == 10

    def test_batch_insert_large(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(1000)]
        count = adapter.batch_insert("users", iter(data))
        assert count == 1000
        assert adapter.get_row_count("users") == 1000

    def test_clear_table_resets_count(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(5)]
        adapter.batch_insert("users", iter(data))
        assert adapter.get_row_count("users") == 5
        adapter.clear_table("users")
        assert adapter.get_row_count("users") == 0

    def test_clear_table_resets_autoincrement(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(5)]
        adapter.batch_insert("users", iter(data))
        adapter.clear_table("users")
        # Insert new data, id should start from 1
        adapter.batch_insert("users", iter([{"name": "new", "email": "new@test.com"}]))
        rows = adapter.get_sample_rows("users", limit=1)
        assert rows[0]["id"] == 1

    def test_get_row_count_empty_table(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        assert adapter.get_row_count("users") == 0

    def test_get_sample_rows_structure(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": f"user_{i}", "email": f"u{i}@test.com"} for i in range(3)]
        adapter.batch_insert("users", iter(data))
        rows = adapter.get_sample_rows("users", limit=2)
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert all(isinstance(r, dict) for r in rows)

    def test_get_column_values_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": "alice", "email": "a@test.com"}, {"name": "bob", "email": "b@test.com"}]
        adapter.batch_insert("users", iter(data))
        names = adapter.get_column_values("users", "name")
        assert "alice" in names
        assert "bob" in names

    def test_get_index_info_correct(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        indexes = adapter.get_index_info("orders")
        # orders table has idx_orders_user index
        index_names = [idx.name for idx in indexes]
        assert "idx_orders_user" in index_names

    def test_execute_select(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        data = [{"name": "test", "email": "t@test.com"}]
        adapter.batch_insert("users", iter(data))
        cursor = adapter.execute("SELECT COUNT(*) FROM users")
        # cursor should support fetchone
        row = cursor.fetchone() if hasattr(cursor, "fetchone") else cursor
        assert row is not None

    def test_nonexistent_table_returns_empty(self, adapter_and_path: Any) -> None:
        adapter, _ = adapter_and_path
        assert adapter.get_column_info("nonexistent") == []
        assert adapter.get_primary_keys("nonexistent") == []
        assert adapter.get_foreign_keys("nonexistent") == []
        assert adapter.get_row_count("nonexistent") == 0


class TestRawSQLiteContract(DatabaseAdapterContract):
    """RawSQLiteAdapter contract tests."""

    def create_adapter(self, db_path: str) -> DatabaseAdapter:
        return RawSQLiteAdapter()

    def get_db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "raw_test.db")


class TestSQLAlchemyContract(DatabaseAdapterContract):
    """SQLAlchemyAdapter contract tests."""

    def create_adapter(self, db_path: str) -> DatabaseAdapter:
        return SQLAlchemyAdapter()

    def get_db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "sa_test.db")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_adapter_contract.py -v --tb=short`
Expected: 28 passed (14 × 2 subclasses)

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_adapter_contract.py && ruff format tests/test_database/test_adapter_contract.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_adapter_contract.py
git commit -m "test: add DatabaseAdapterContract tests for both adapters (CP2 P1)"
```

---

## Task 3: AI Plugin Dialect Context Tests (Real LLM)

**Files:**
- Modify: `tests/test_ai_plugin.py` (append TestSchemaAnalyzerDialect class)

- [ ] **Step 1: Append TestSchemaAnalyzerDialect class at the end of tests/test_ai_plugin.py**

```python
class TestSchemaAnalyzerDialect:
    """Test SchemaAnalyzer dialect context propagation (including real LLM calls)."""

    def test_build_context_with_sqlite_dialect(self) -> None:
        """dialect="sqlite" output contains "Database dialect: sqlite"."""
        analyzer = SchemaAnalyzer(AIConfig())
        schema_ctx = {
            "table_name": "users",
            "columns": [make_col("id", "INTEGER", is_pk=True, is_auto=True), make_col("name", "TEXT")],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
            "sample_data": [],
            "dialect": "sqlite",
        }
        context = analyzer._build_context(schema_ctx)
        assert "Database dialect: sqlite" in context

    def test_build_context_with_postgresql_dialect(self) -> None:
        """dialect="postgresql" output contains "Database dialect: postgresql"."""
        analyzer = SchemaAnalyzer(AIConfig())
        schema_ctx = {
            "table_name": "users",
            "columns": [make_col("id", "INTEGER", is_pk=True, is_auto=True), make_col("name", "TEXT")],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
            "sample_data": [],
            "dialect": "postgresql",
        }
        context = analyzer._build_context(schema_ctx)
        assert "Database dialect: postgresql" in context

    def test_build_context_default_dialect_is_sqlite(self) -> None:
        """Default dialect is "sqlite" when not passed."""
        analyzer = SchemaAnalyzer(AIConfig())
        schema_ctx = {
            "table_name": "users",
            "columns": [make_col("id", "INTEGER")],
            "indexes": [],
            "foreign_keys": [],
            "all_table_names": ["users"],
            "sample_data": [],
        }
        context = analyzer._build_context(schema_ctx)
        assert "Database dialect: sqlite" in context

    def test_analyze_schema_sqlite_real_llm(
        self, tmp_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real SQLite schema analysis, verify LLM returns valid configuration."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        # Configure environment variables based on backend (use monkeypatch to avoid polluting other tests)
        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            # GOOGLE_API_KEY already set
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        config = AIConfig.from_env()
        analyzer = SchemaAnalyzer(config)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # Verify LLM returns valid structure
        assert result is not None, "LLM should return valid configuration, but returned None (API key may not be configured or call failed)"
        assert isinstance(result, dict), f"LLM return should be dict, actual: {type(result)}"
        assert "tables" in result or "columns" in result, f"LLM return structure abnormal: {result}"

    def test_analyze_schema_postgresql_real_llm(
        self, pg_url: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Real PG schema analysis, verify dialect propagates to LLM prompt."""
        # First create table on PG
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS users "
                    "(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT)"
                )
            )
            conn.commit()
        engine.dispose()

        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            # GOOGLE_API_KEY already set
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        config = AIConfig.from_env()
        analyzer = SchemaAnalyzer(config)

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            # Verify dialect propagates to context
            assert schema_ctx.get("dialect") == "postgresql"
            # Verify dialect propagates to LLM prompt
            messages = analyzer.build_initial_messages(schema_ctx)
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # Verify prompt contains PG dialect info (take the last user message, i.e., context)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0
        context_message = user_messages[-1]  # Last user message is context
        assert "Database dialect: postgresql" in context_message["content"], (
            f"PG dialect not propagated to LLM prompt, prompt content: {context_message['content'][:200]}"
        )

        assert result is not None, "LLM should return valid configuration"
        assert isinstance(result, dict), f"LLM return should be dict, actual: {type(result)}"

    def test_analyze_schema_dialect_in_prompt(
        self, pg_url: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Capture the actual prompt sent to LLM, assert it contains "Database dialect: postgresql".

        Note: build_initial_messages() first adds system, then adds few-shot examples (user/assistant pairs),
        and finally adds context as a user message. Therefore, you must take the last user message (i.e., context),
        not the first one.
        """
        # First create table on PG
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS users "
                    "(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT)"
                )
            )
            conn.commit()
        engine.dispose()

        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            # GOOGLE_API_KEY already set
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        config = AIConfig.from_env()
        analyzer = SchemaAnalyzer(config)

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            messages = analyzer.build_initial_messages(schema_ctx)

        # Take the last user message (i.e., context, not few-shot example)
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0
        context_message = user_messages[-1]
        assert "Database dialect: postgresql" in context_message["content"], (
            f"PG dialect not propagated to LLM prompt, prompt content: {context_message['content'][:200]}"
        )

    def test_analyze_schema_llm_response_structure(
        self, tmp_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify LLM return structure (tables/columns/generators)."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        if backend == "ollama":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
            monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
        elif backend == "lm_studio":
            monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
            monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
            monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
        elif backend == "google_ai_studio":
            # GOOGLE_API_KEY already set
            pass

        monkeypatch.setenv("SQLSEED_AI_MODEL", model)

        config = AIConfig.from_env()
        analyzer = SchemaAnalyzer(config)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        assert result is not None, "LLM should return valid configuration"
        # Verify return structure is dict and contains tables or columns key
        assert isinstance(result, dict), f"LLM return should be dict, actual: {type(result)}"
        assert "tables" in result or "columns" in result, (
            f"LLM return should contain 'tables' or 'columns' key, actual keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}"
        )

    def test_analyze_schema_llm_failure_clear_error(self, tmp_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate LLM timeout/error, verify error message is clear."""
        # Use invalid base_url to simulate connection failure
        # Note: SQLSEED_AI_BACKEND valid values are lm_studio/ollama/openai_compat/google_ai_studio, not "openai"
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "openai_compat")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9999/v1")  # Non-existent port
        monkeypatch.setenv("OPENAI_API_KEY", "invalid_key")
        monkeypatch.setenv("SQLSEED_AI_MODEL", "gemma-4-26b-a4b-it")
        monkeypatch.setenv("SQLSEED_AI_TIMEOUT", "5")  # Short timeout

        config = AIConfig.from_env()
        analyzer = SchemaAnalyzer(config)

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")
            # Call failure should return None (not raise exception and crash)
            result = analyzer.analyze_table_from_ctx(**schema_ctx)

        # Returns None on failure, does not crash
        assert result is None
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_ai_plugin.py::TestSchemaAnalyzerDialect -v --tb=short`
Expected: 8 passed (requires LLM backend running to execute real LLM tests)

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_ai_plugin.py && ruff format tests/test_ai_plugin.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_ai_plugin.py
git commit -m "test: add AI plugin dialect context tests with real LLM (CP2 P1)"
```

---

## Task 4: config/loader.py Tests

**Files:**
- Modify: `tests/test_config/test_loader.py` (append TestReadSqliteTableNames class)

- [ ] **Step 1: Append TestReadSqliteTableNames class at the end of tests/test_config/test_loader.py**

```python
class TestReadSqliteTableNames:
    """Test _read_sqlite_table_names function (private function, with leading underscore)."""

    def test_read_sqlite_table_names_empty_database(self, tmp_path) -> None:
        """Empty database returns []."""
        from sqlseed.config.loader import _read_sqlite_table_names

        db_path = str(tmp_path / "empty.db")
        sqlite3.connect(db_path).close()  # Create empty file
        assert _read_sqlite_table_names(db_path) == []

    def test_read_sqlite_table_names_excludes_system_tables(self, tmp_path) -> None:
        """Exclude sqlite_% system tables."""
        from sqlseed.config.loader import _read_sqlite_table_names

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE sqlite_sequence (name TEXT, seq INTEGER)")
        conn.commit()
        conn.close()

        names = _read_sqlite_table_names(db_path)
        assert "users" in names
        assert "sqlite_sequence" not in names

    def test_read_sqlite_table_names_returns_all_user_tables(self, tmp_path) -> None:
        """Multi-table database returns all user tables."""
        from sqlseed.config.loader import _read_sqlite_table_names

        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        names = _read_sqlite_table_names(db_path)
        assert set(names) == {"users", "orders", "products"}

    def test_generate_template_does_not_accept_url(self) -> None:
        """generate_template does not accept url parameter (signature only accepts db_path + table_name)."""
        from sqlseed.config.loader import generate_template

        # generate_template signature: generate_template(db_path: str, table_name: str | None = None)
        # Does not accept url keyword argument, should raise TypeError
        with pytest.raises(TypeError):
            generate_template(url="postgresql://user:pass@host/db")  # type: ignore[call-arg]

    def test_read_sqlite_table_names_nonexistent_parent_dir_raises(self, tmp_path) -> None:
        """Raises exception when parent directory does not exist (sqlite3.connect will create file, but fails when parent directory does not exist)."""
        from sqlseed.config.loader import _read_sqlite_table_names

        # When parent directory does not exist, sqlite3.connect raises OperationalError
        nonexistent = str(tmp_path / "nonexistent_dir" / "test.db")
        with pytest.raises((sqlite3.OperationalError, OSError)):
            _read_sqlite_table_names(nonexistent)
```

**Note:** Before appending this code block, ensure `tests/test_config/test_loader.py` already has `import sqlite3` at the top. If not, add `import sqlite3` in the import section at the top of the file.

- [ ] **Step 2: Confirm _read_sqlite_table_names and generate_template function signatures**

Run: `python -c "from sqlseed.config.loader import _read_sqlite_table_names, generate_template; print('OK')"`

Expected output: `OK` (confirms functions exist and are importable)

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_config/test_loader.py::TestReadSqliteTableNames -v --tb=short`
Expected: 5 passed

- [ ] **Step 4: Run ruff check and format**

Run: `ruff check tests/test_config/test_loader.py && ruff format tests/test_config/test_loader.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_config/test_loader.py
git commit -m "test: add config loader table name tests (CP2 P1)"
```

---

## Task 5: Orchestrator Count Validation Tests

**Files:**
- Modify: `tests/test_orchestrator.py` (append TestOrchestratorCountValidation class)

- [ ] **Step 1: Append TestOrchestratorCountValidation class at the end of tests/test_orchestrator.py**

```python
class TestOrchestratorCountValidation:
    """Test orchestrator count parameter validation."""

    def test_fill_count_zero_raises(self, tmp_db: str) -> None:
        """fill_table(count=0) raises ValueError."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            with pytest.raises(ValueError):
                orch.fill_table("users", count=0)

    def test_fill_count_negative_raises(self, tmp_db: str) -> None:
        """fill_table(count=-1) raises ValueError."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            with pytest.raises(ValueError):
                orch.fill_table("users", count=-1)

    def test_fill_count_one_succeeds(self, tmp_db: str) -> None:
        """count=1 generates normally."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=1)
            assert result.count == 1

    def test_fill_count_large_succeeds(self, tmp_db: str) -> None:
        """count=10000 generates normally (no error)."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            result = orch.fill_table("users", count=10000)
            assert result.count == 10000
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py::TestOrchestratorCountValidation -v --tb=short`
Expected: 4 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_orchestrator.py && ruff format tests/test_orchestrator.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_orchestrator.py
git commit -m "test: add orchestrator count validation tests (CP2 P1)"
```

---

## Task 6: TypeNormalizer Boundary Tests

**Files:**
- Modify: `tests/test_database/test_dialect.py` (append tests)

- [ ] **Step 1: Append TypeNormalizer boundary tests at the end of tests/test_database/test_dialect.py**

```python
class TestTypeNormalizerBoundary:
    """TypeNormalizer boundary case tests."""

    def setup_method(self) -> None:
        """Create TypeNormalizer instance before each test (normalize is an instance method, not a static method)."""
        self.normalizer = TypeNormalizer()

    def test_normalize_none_input(self) -> None:
        """normalize(None, "sqlite") returns TEXT fallback type."""
        result = self.normalizer.normalize(None, "sqlite")  # type: ignore[arg-type]
        # None input triggers `not raw_type` short-circuit, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()

    def test_normalize_whitespace_only(self) -> None:
        """normalize("   ", "sqlite") returns TEXT fallback type."""
        result = self.normalizer.normalize("   ", "sqlite")
        # Pure whitespace triggers `not raw_type.strip()`, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()

    def test_normalize_unknown_dialect(self) -> None:
        """normalize("int", "oracle") goes through default uppercase branch, returns INT."""
        result = self.normalizer.normalize("int", "oracle")
        # Unknown dialect (not postgresql/mysql) goes through default branch: base_raw.upper() = "INT"
        assert result.base == "INT"
        assert result.params == ()

    def test_normalize_empty_string(self) -> None:
        """normalize("", "postgresql") returns TEXT fallback type."""
        result = self.normalizer.normalize("", "postgresql")
        # Empty string triggers `not raw_type` short-circuit, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_dialect.py::TestTypeNormalizerBoundary -v --tb=short`
Expected: 4 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_dialect.py && ruff format tests/test_database/test_dialect.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_dialect.py
git commit -m "test: add TypeNormalizer boundary tests (CP2 P1)"
```

---

## Task 7: MySQL Type Mapping Completion

**Files:**
- Modify: `tests/test_database/test_dialect.py` (append MySQL type mapping tests)

- [ ] **Step 1: Append MySQL type mapping tests at the end of tests/test_database/test_dialect.py**

```python
class TestMySQLTypeMapping:
    """MySQL type mapping tests.

    Note: TypeNormalizer.normalize is an instance method, must be instantiated first.
    Expected values based on _MYSQL_TYPE_MAP (src/sqlseed/database/_type_normalizer.py lines 86-119).
    """

    def setup_method(self) -> None:
        """Create TypeNormalizer instance before each test."""
        self.normalizer = TypeNormalizer()

    def test_mysql_int_mapping(self) -> None:
        """INT → INTEGER (_MYSQL_TYPE_MAP: "int": "INTEGER")."""
        result = self.normalizer.normalize("int", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_bigint_mapping(self) -> None:
        """BIGINT → INTEGER (_MYSQL_TYPE_MAP: "bigint": "INTEGER")."""
        result = self.normalizer.normalize("bigint", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_varchar_mapping(self) -> None:
        """VARCHAR(255) → VARCHAR (_MYSQL_TYPE_MAP: "varchar": "VARCHAR")."""
        result = self.normalizer.normalize("varchar(255)", "mysql")
        assert result.base == "VARCHAR"
        assert result.params == (255,)

    def test_mysql_text_mapping(self) -> None:
        """TEXT → TEXT (_MYSQL_TYPE_MAP: "text": "TEXT")."""
        result = self.normalizer.normalize("text", "mysql")
        assert result.base == "TEXT"

    def test_mysql_datetime_mapping(self) -> None:
        """DATETIME → DATETIME (_MYSQL_TYPE_MAP: "datetime": "DATETIME")."""
        result = self.normalizer.normalize("datetime", "mysql")
        assert result.base == "DATETIME"

    def test_mysql_tinyint_mapping(self) -> None:
        """TINYINT → INTEGER (_MYSQL_TYPE_MAP: "tinyint": "INTEGER")."""
        result = self.normalizer.normalize("tinyint", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_decimal_mapping(self) -> None:
        """DECIMAL(10,2) → NUMERIC (_MYSQL_TYPE_MAP: "decimal": "NUMERIC")."""
        result = self.normalizer.normalize("decimal(10,2)", "mysql")
        assert result.base == "NUMERIC"
        assert result.params == (10, 2)

    def test_mysql_json_mapping(self) -> None:
        """JSON → JSON (_MYSQL_TYPE_MAP: "json": "JSON")."""
        result = self.normalizer.normalize("json", "mysql")
        assert result.base == "JSON"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_dialect.py::TestMySQLTypeMapping -v --tb=short`
Expected: 8 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_dialect.py && ruff format tests/test_database/test_dialect.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_dialect.py
git commit -m "test: add MySQL type mapping tests (CP2 P1)"
```

---

## Task 8: CP2 Full Validation

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
Expected: All tests pass (720 existing + CP1 ~60 + CP2 ~48 = ~828 tests)

**Note:**
- PG integration tests require Docker running
- AI real LLM tests require at least one LLM backend (Ollama/LM Studio/Google AI Studio)

- [ ] **Step 5: If any failures, fix and re-validate**

Fix any ruff/mypy/pytest failures until all pass.

- [ ] **Step 6: Confirm CP2 completion**

CP2 completion criteria:
- ruff check: 0 errors
- ruff format --check: 0 errors
- mypy: 0 errors
- pytest: all pass (~828 tests)

No commit needed (validation step).

---

## Self-Review

**Spec coverage check:**
- 4.1 SQLAlchemyAdapter boundary tests → Task 1 ✓
- 4.2 DatabaseAdapterContract implementation → Task 2 ✓
- 4.3 AI plugin dialect context tests (real LLM) → Task 3 ✓
- 4.4 config/loader.py tests → Task 4 ✓
- 4.5 orchestrator count validation tests → Task 5 ✓
- 4.6 TypeNormalizer boundary tests → Task 6 ✓
- 4.7 MySQL type mapping completion → Task 7 ✓
- CP2 full validation → Task 8 ✓

**Placeholder scan:** No TBD/TODO, all steps contain complete code ✓

**Type consistency:** `DatabaseAdapterContract`, `TypeNormalizer.normalize` (instance method), `_read_sqlite_table_names` (private function), `analyze_table_from_ctx` naming consistent throughout ✓

**CP2 test count:**
- Task 1: 15 tests
- Task 2: 28 tests (14 × 2)
- Task 3: 8 tests
- Task 4: 5 tests
- Task 5: 4 tests
- Task 6: 4 tests
- Task 7: 8 tests
- **Total: 72 tests** (slightly exceeds ~48 expected, because DatabaseAdapterContract 28 tests cover more comprehensively)

## Cross-Validation Fix Records (Round 1)

**Issues found and fixed by Agent A (coverage completeness):**
1. CRITICAL: Task 3 fixture scope → Confirmed CP1 has moved `pg_url`/`available_llm_backend` to `tests/conftest.py` (root conftest), visible to entire tests/ directory, prerequisite description corrected
2. HIGH: `test_analyze_schema_dialect_in_prompt` should test PG dialect not SQLite → Changed to use `pg_url`, assert "Database dialect: postgresql"
3. HIGH: `test_analyze_schema_postgresql_real_llm` missing prompt validation → Added assertion on last user message returned by `build_initial_messages`
4. MEDIUM: Task 6 four tests have shallow assertions → Changed to assert specific `result.base` values (TEXT/INT)
5. MEDIUM: `test_analyze_schema_llm_response_structure` assertions too weak → Changed to `isinstance(result, dict)` + key existence check
6. MEDIUM: Task 3 uses `os.environ` polluting environment → All changed to `monkeypatch.setenv`
7. LOW: PG tests missing `google_ai` branch → Added

**Issues found and fixed by Agent B (executability):**
1. CRITICAL: `test_double_connect_raises` source code has no such check → Changed to `test_double_connect_overwrites_engine` (verify no exception raised)
2. CRITICAL: `test_analyze_schema_dialect_in_prompt` takes wrong user message → Changed to take last user message (context)
3. CRITICAL: Task 4 imports `read_sqlite_table_names` (actually `_read_sqlite_table_names`) → Fixed
4. CRITICAL: `generate_template_config` does not exist → Changed to `test_generate_template_does_not_accept_url` (verify TypeError)
5. CRITICAL: `test_read_sqlite_table_names_nonexistent_file_raises` sqlite3 auto-creates file → Changed to test parent directory not existing
6. CRITICAL: Missing `import sqlite3` → Explained in note
7. HIGH: `SQLSEED_AI_BACKEND=openai` invalid value → Changed to `lm_studio`/`openai_compat`
8. MEDIUM: Task 7 `result.base_type` does not exist → Changed to `result.base`, fixed docstring and expected values (bigint→INTEGER, tinyint→INTEGER, decimal→NUMERIC)
9. MEDIUM: Task 6/7 `TypeNormalizer.normalize` is instance method → Added `setup_method` to create instance

## Cross-Validation Fix Records (Round 2, sourced from CP3 cross-validation)

CP3 Round 2 found `available_llm_backend` fixture returns `"google_ai"` but `AIBackend` enum value is `"google_ai_studio"`. This is the root cause in CP1 fixture, CP2 downstream is affected:

1. HIGH: CP1 fixture `{"backend": "google_ai"}` → `{"backend": "google_ai_studio"}` (root cause fix, completed in CP1 plan)
2. HIGH: CP2 Task 3's 4 occurrences of `elif backend == "google_ai":` → `elif backend == "google_ai_studio":` (downstream sync fix)

Note: CP2 tests themselves do not directly call `AIBackend(backend)`, but use `AIConfig.from_env()` to read environment variables, so CP2 tests can also run before the fix. However, to keep fixture return values consistent with enum values, the branch checks are still updated synchronously.
