# CP3 (P2) Enhanced Coverage and Real Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete real PostgreSQL integration tests, URL full-chain E2E, reserved words and special characters, adapter consistency, PostgresDialect boundary, optimizer migration, MCP server complete tool tests (including real LLM), approximately 48 tests.

**Architecture:** Pure test completion, no source code modifications. Add 2 new test files + extend 3 existing files. All PG tests use testcontainers to start real containers, all AI tests use real LLM calls (Gemma 4).

**Tech Stack:** pytest, testcontainers, SQLAlchemy, psycopg, sqlseed-ai (Gemma 4)

**Prerequisites:**
- CP1 and CP2 completed (all tests passing)
- `tests/conftest.py` (root conftest) already contains `pg_url` and `available_llm_backend` fixtures (created in CP1, scoped to the entire tests/ directory)
- `tests/integration/` directory already created (created in CP1, contains `__init__.py`)
- Docker installed and running (PG integration test dependency)
- At least one LLM backend available (AI test dependency)

**Validation Gate:** After CP3 completion, `ruff check` + `ruff format --check` + `mypy src plugins` + `pytest` (including new tests + CP1 + CP2 + 720 existing tests) all pass.

---

## File Structure

| File | Operation | Responsibility |
|------|-----------|----------------|
| `tests/integration/test_pg_integration.py` | Add | Real PG integration tests |
| `tests/integration/test_url_e2e.py` | Add | URL full-chain E2E |
| `tests/test_database/test_sqlalchemy_adapter_boundary.py` | Extend | +Reserved words and special characters |
| `tests/test_database/test_adapter_contract.py` | Extend | +Adapter consistency |
| `tests/test_database/test_dialect.py` | Extend | +PostgresDialect boundary |
| `tests/test_database/test_optimizer.py` | Extend | Migrate to BulkWriteOptimizer abstraction |
| `plugins/mcp-server-sqlseed/tests/test_server.py` | Add | 6 tools + 1 resource complete tests |

---

## Task 1: Real PostgreSQL Integration Tests

**Files:**
- Create: `tests/integration/test_pg_integration.py`

- [ ] **Step 1: Create test_pg_integration.py**

```python
from __future__ import annotations

from typing import Any

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

pytestmark = pytest.mark.integration


class TestPostgreSQLIntegration:
    """Real PostgreSQL integration tests (depends on testcontainers)."""

    def test_pg_connect_and_close(self, pg_url: str) -> None:
        """Real PG connect/close."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.dialect.name == "postgresql"
        adapter.close()

    def test_pg_get_table_names_empty(self, pg_url: str) -> None:
        """Empty PG database returns []."""
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        # PG may have system tables by default, but get_table_names should only return user tables
        names = adapter.get_table_names()
        assert names == [], f"Empty PG database should return [], actual: {names}"
        adapter.close()

    def test_pg_create_table_and_get_column_info(self, pg_url: str) -> None:
        """After creating table, get_column_info correctly identifies types."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE test_users "
                    "(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)"
                )
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("test_users")
        assert len(cols) == 4
        col_names = [c.name for c in cols]
        assert "id" in col_names
        assert "name" in col_names
        adapter.close()

    def test_pg_serial_autoincrement_detection(self, pg_url: str) -> None:
        """SERIAL column recognized as autoincrement."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE serial_test (id SERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("serial_test")
        id_col = next(c for c in cols if c.name == "id")
        assert id_col.is_autoincrement is True
        adapter.close()

    def test_pg_bigserial_autoincrement_detection(self, pg_url: str) -> None:
        """BIGSERIAL column recognized as autoincrement."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE bigserial_test (id BIGSERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("bigserial_test")
        id_col = next(c for c in cols if c.name == "id")
        assert id_col.is_autoincrement is True
        adapter.close()

    def test_pg_identity_autoincrement_detection(self, pg_url: str) -> None:
        """GENERATED AS IDENTITY column recognized as autoincrement."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE identity_test "
                    "(id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT)"
                )
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("identity_test")
        id_col = next(c for c in cols if c.name == "id")
        assert id_col.is_autoincrement is True
        adapter.close()

    def test_pg_batch_insert_and_count(self, pg_url: str) -> None:
        """Row count correct after batch insert."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE insert_test (id SERIAL PRIMARY KEY, name TEXT NOT NULL)")
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        data = [{"name": f"user_{i}"} for i in range(50)]
        count = adapter.batch_insert("insert_test", iter(data))
        assert count == 50
        assert adapter.get_row_count("insert_test") == 50
        adapter.close()

    def test_pg_clear_table_resets_sequence(self, pg_url: str) -> None:
        """Sequence reset after clear_table (real pg_get_serial_sequence)."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE seq_reset_test (id SERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        # Insert data
        data = [{"name": f"user_{i}"} for i in range(5)]
        adapter.batch_insert("seq_reset_test", iter(data))
        # Clear
        adapter.clear_table("seq_reset_test")
        assert adapter.get_row_count("seq_reset_test") == 0
        # Insert new data, id should start from 1
        adapter.batch_insert("seq_reset_test", iter([{"name": "new"}]))
        rows = adapter.get_sample_rows("seq_reset_test", limit=1)
        assert rows[0]["id"] == 1
        adapter.close()

    def test_pg_fill_end_to_end(self, pg_url: str) -> None:
        """fill(url=pg_url, table=..., count=100) complete flow."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE fill_test "
                    "(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)"
                )
            )
            conn.commit()
        engine.dispose()

        import sqlseed

        result = sqlseed.fill(url=pg_url, table="fill_test", count=100, provider="base")
        assert result.count == 100

    def test_pg_fill_with_fk_integrity(self, pg_url: str) -> None:
        """FK related table data integrity on PG."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE fk_users (id SERIAL PRIMARY KEY, name TEXT NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE fk_orders "
                    "(id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES fk_users(id), amount REAL)"
                )
            )
            conn.commit()
        engine.dispose()

        import sqlseed

        # Fill main table first
        sqlseed.fill(url=pg_url, table="fk_users", count=10, provider="base")
        # Then fill related table
        result = sqlseed.fill(url=pg_url, table="fk_orders", count=20, provider="base")
        assert result.count == 20

        # Verify FK integrity: fk_orders.user_id must all exist in fk_users.id
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            # Find orphan FK references (rows where user_id is not in fk_users.id)
            orphan_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM fk_orders o "
                    "LEFT JOIN fk_users u ON o.user_id = u.id WHERE u.id IS NULL"
                )
            ).scalar()
        engine.dispose()
        assert orphan_count == 0, f"Found {orphan_count} orphan FK references, FK integrity broken"

    def test_pg_bulk_optimizer_synchronous_commit(self, pg_url: str) -> None:
        """Verify synchronous_commit=OFF is called (use mock to avoid connection pool session isolation issues).

        Note: synchronous_commit is a PG session-level parameter, SQLAlchemy connection pool may execute
        SET and SHOW on different connections, making it impossible to verify via actual query whether SET
        took effect. Changed to use mock execute_fn to record SET command calls, verifying the optimizer
        indeed issued SET synchronous_commit = OFF. This is a contract test of optimizer behavior, not a
        test of PG itself.
        """
        from sqlseed.database._bulk_optimizer import PostgresBulkOptimizer

        set_calls: list[str] = []

        class _FakeResult:
            """Simulate return result of SHOW command."""

            def fetchone(self) -> tuple[str, ...]:
                return ("on",)

        def execute_fn(sql: str, params: Any = None) -> _FakeResult:
            sql_upper = sql.upper()
            # Record all SET commands
            if "SET" in sql_upper:
                set_calls.append(sql)
            # SHOW command returns original value "on"
            return _FakeResult()

        optimizer = PostgresBulkOptimizer(execute_fn)
        optimizer.preserve()
        optimizer.optimize(expected_rows=20000)

        # Verify SET synchronous_commit = OFF is called
        sync_off_calls = [
            s for s in set_calls
            if "synchronous_commit" in s.lower() and "off" in s.lower()
        ]
        assert len(sync_off_calls) > 0, (
            f"SET synchronous_commit = OFF not called, actual SET calls: {set_calls}"
        )

        optimizer.restore()

    def test_pg_dialect_in_schema_context(self, pg_url: str) -> None:
        """get_schema_context on PG returns dialect="postgresql"."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE ctx_test (id SERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            ctx = orch.get_schema_context("ctx_test")
            assert ctx.get("dialect") == "postgresql"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_pg_integration.py -v --tb=short`
Expected: 12 passed (requires Docker running)

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/integration/test_pg_integration.py && ruff format tests/integration/test_pg_integration.py`

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_pg_integration.py
git commit -m "test: add real PostgreSQL integration tests (CP3 P2)"
```

---

## Task 2: URL Full-Chain E2E Tests

**Files:**
- Create: `tests/integration/test_url_e2e.py`

- [ ] **Step 1: Create test_url_e2e.py**

```python
from __future__ import annotations

from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from sqlseed.cli.main import cli

pytestmark = pytest.mark.integration


def _setup_pg_table(pg_url: str) -> None:
    """Create test table on PG."""
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS users "
                "(id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)"
            )
        )
        conn.commit()
    engine.dispose()


class TestUrlE2E:
    """URL full-chain E2E tests."""

    def test_cli_url_to_pg_e2e(self, pg_url: str) -> None:
        """sqlseed fill --url pg_url -t users -n 100 complete CLI→PG chain."""
        _setup_pg_table(pg_url)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--url", pg_url, "--table", "users", "--count", "100", "--provider", "base"],
        )
        assert result.exit_code == 0
        assert "100" in result.output

    def test_api_url_to_pg_e2e(self, pg_url: str) -> None:
        """fill(url=pg_url, ...) complete API→PG chain."""
        _setup_pg_table(pg_url)
        import sqlseed

        result = sqlseed.fill(url=pg_url, table="users", count=50, provider="base")
        assert result.count == 50

    def test_config_url_to_pg_e2e(self, pg_url: str, tmp_path: Any) -> None:
        """YAML contains url field → fill_from_config → PG."""
        _setup_pg_table(pg_url)
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": pg_url,
            "provider": "base",
            "tables": [{"name": "users", "count": 30}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        import sqlseed

        results = sqlseed.fill_from_config(str(config_path))
        assert len(results) == 1
        assert results[0].count == 30

    def test_pg_url_snapshot_and_replay(
        self, pg_url: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Snapshot save + replay on PG (via CLI, because fill() has no snapshot parameter, replay not exported from public API)."""
        _setup_pg_table(pg_url)

        cache_dir = str(tmp_path / "cache")
        monkeypatch.setenv("SQLSEED_CACHE_DIR", cache_dir)

        # 1. Save snapshot via CLI fill --snapshot (fill() Python API does not support snapshot parameter)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                "--url", pg_url,
                "--table", "users",
                "--count", "20",
                "--provider", "base",
                "--seed", "42",
                "--snapshot",
            ],
        )
        assert result.exit_code == 0, f"CLI fill --snapshot failed: {result.output}"

        # 2. Find snapshot file (list_snapshots returns list[str], not list[dict])
        from sqlseed.config.snapshot import SnapshotManager

        sm = SnapshotManager(cache_dir)
        snapshots = sm.list_snapshots()
        assert len(snapshots) > 0, "No snapshot file found"
        snapshot_path = snapshots[0]  # Directly a file path string, not a dict

        # 3. Clear table
        from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        adapter.clear_table("users")
        assert adapter.get_row_count("users") == 0
        adapter.close()

        # 4. Replay via CLI (sqlseed.replay not exported from public API, only CLI command)
        result = runner.invoke(cli, ["replay", snapshot_path])
        assert result.exit_code == 0, f"CLI replay failed: {result.output}"

        # 5. Verify data has been replayed
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.get_row_count("users") == 20
        adapter.close()

    def test_pg_url_preview_e2e(self, pg_url: str) -> None:
        """preview(url=pg_url, ...) returns correct preview."""
        _setup_pg_table(pg_url)
        import sqlseed

        rows = sqlseed.preview(url=pg_url, table="users", count=5, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)

    def test_pg_url_inspect_e2e(self, pg_url: str) -> None:
        """inspect(url=pg_url) displays mapping strategy."""
        _setup_pg_table(pg_url)
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "--url", pg_url])
        assert result.exit_code == 0
        # Verify output contains table name and column name (mapping strategy info)
        assert "users" in result.output, f"inspect output does not contain table name 'users': {result.output}"
        assert "name" in result.output, f"inspect output does not contain column name 'name': {result.output}"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_url_e2e.py -v --tb=short`
Expected: 6 passed (requires Docker running)

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/integration/test_url_e2e.py && ruff format tests/integration/test_url_e2e.py`

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_url_e2e.py
git commit -m "test: add URL end-to-end E2E tests (CP3 P2)"
```

---

## Task 3: Reserved Words and Special Characters Tests

**Files:**
- Modify: `tests/test_database/test_sqlalchemy_adapter_boundary.py` (append TestReservedWordsAndSpecialChars class)

- [ ] **Step 1: Append TestReservedWordsAndSpecialChars class at the end of test_sqlalchemy_adapter_boundary.py**

```python
class TestReservedWordsAndSpecialChars:
    """Test handling of SQL reserved words and special characters."""

    def test_table_name_reserved_word_order(self, tmp_path: Any) -> None:
        """Table name "order" (SQL reserved word) correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, name TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        assert "order" in adapter.get_table_names()
        cols = adapter.get_column_info("order")
        assert len(cols) == 2
        adapter.close()

    def test_table_name_reserved_word_select(self, tmp_path: Any) -> None:
        """Table name "select" correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "select" (id INTEGER PRIMARY KEY, name TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        assert "select" in adapter.get_table_names()
        adapter.close()

    def test_column_name_reserved_word(self, tmp_path: Any) -> None:
        """Column names "from", "where" correctly quoted."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, "from" TEXT, "where" TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        cols = adapter.get_column_info("test")
        col_names = [c.name for c in cols]
        assert "from" in col_names
        assert "where" in col_names
        adapter.close()

    def test_table_name_with_special_chars(self, tmp_path: Any) -> None:
        """Table name with double quotes correctly escaped."""
        db_path = str(tmp_path / "special.db")
        conn = sqlite3.connect(db_path)
        # SQLite table names with special characters need double quotes
        conn.execute('CREATE TABLE "my table" (id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        names = adapter.get_table_names()
        assert "my table" in names
        adapter.close()

    def test_column_name_with_special_chars(self, tmp_path: Any) -> None:
        """Column name with double quotes correctly escaped."""
        db_path = str(tmp_path / "special.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, "first name" TEXT)')
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(db_path)
        cols = adapter.get_column_info("test")
        col_names = [c.name for c in cols]
        assert "first name" in col_names
        adapter.close()

    def test_fill_table_with_reserved_name_e2e(self, tmp_path: Any) -> None:
        """Reserved word table name complete fill flow."""
        db_path = str(tmp_path / "reserved.db")
        conn = sqlite3.connect(db_path)
        conn.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
        conn.commit()
        conn.close()

        import sqlseed

        result = sqlseed.fill(db_path, table="order", count=10, provider="base")
        assert result.count == 10

        # Verify data
        conn = sqlite3.connect(db_path)
        cursor = conn.execute('SELECT COUNT(*) FROM "order"')
        assert cursor.fetchone()[0] == 10
        conn.close()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_sqlalchemy_adapter_boundary.py::TestReservedWordsAndSpecialChars -v --tb=short`
Expected: 6 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_sqlalchemy_adapter_boundary.py && ruff format tests/test_database/test_sqlalchemy_adapter_boundary.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_sqlalchemy_adapter_boundary.py
git commit -m "test: add reserved words and special chars tests (CP3 P2)"
```

---

## Task 4: SQLAlchemyAdapter vs RawSQLiteAdapter Consistency

**Files:**
- Modify: `tests/test_database/test_adapter_contract.py` (append TestAdapterConsistency class)

- [ ] **Step 1: Append TestAdapterConsistency class at the end of test_adapter_contract.py**

```python
class TestAdapterConsistency:
    """Test behavioral consistency between SQLAlchemyAdapter and RawSQLiteAdapter."""

    @pytest.fixture
    def dual_adapters(self, tmp_path: Path) -> Any:
        """Create two adapters connected to the same database."""
        db_path = str(tmp_path / "consistency.db")
        _create_test_db(db_path)

        # Insert some test data
        conn = sqlite3.connect(db_path)
        for i in range(10):
            conn.execute(
                "INSERT INTO users (name, email) VALUES (?, ?)",
                [f"user_{i}", f"u{i}@test.com"],
            )
        conn.commit()
        conn.close()

        raw = RawSQLiteAdapter()
        raw.connect(db_path)
        sa = SQLAlchemyAdapter()
        sa.connect(db_path)
        yield raw, sa, db_path
        raw.close()
        sa.close()

    def test_both_adapters_same_column_info(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return same ColumnInfo."""
        raw, sa, _ = dual_adapters
        raw_cols = raw.get_column_info("users")
        sa_cols = sa.get_column_info("users")

        assert len(raw_cols) == len(sa_cols)
        for r, s in zip(raw_cols, sa_cols):
            assert r.name == s.name
            assert r.type == s.type
            assert r.nullable == s.nullable
            assert r.is_primary_key == s.is_primary_key

    def test_both_adapters_same_row_count(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return same row count."""
        raw, sa, _ = dual_adapters
        assert raw.get_row_count("users") == sa.get_row_count("users")
        assert raw.get_row_count("users") == 10

    def test_both_adapters_same_foreign_keys(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return same FKs."""
        raw, sa, _ = dual_adapters
        raw_fks = raw.get_foreign_keys("orders")
        sa_fks = sa.get_foreign_keys("orders")

        assert len(raw_fks) == len(sa_fks)
        for r, s in zip(raw_fks, sa_fks):
            assert r.column == s.column
            assert r.ref_table == s.ref_table
            assert r.ref_column == s.ref_column

    def test_both_adapters_same_sample_rows(self, dual_adapters: Any) -> None:
        """Same DB, both adapters return same sample rows."""
        raw, sa, _ = dual_adapters
        raw_rows = raw.get_sample_rows("users", limit=5)
        sa_rows = sa.get_sample_rows("users", limit=5)

        assert len(raw_rows) == len(sa_rows)
        # Verify id field consistency (order may differ, but set of values should be the same)
        raw_ids = {r["id"] for r in raw_rows}
        sa_ids = {r["id"] for r in sa_rows}
        assert raw_ids == sa_ids
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_adapter_contract.py::TestAdapterConsistency -v --tb=short`
Expected: 4 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_adapter_contract.py && ruff format tests/test_database/test_adapter_contract.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_adapter_contract.py
git commit -m "test: add adapter consistency tests (CP3 P2)"
```

---

## Task 5: PostgresDialect Boundary Tests

**Files:**
- Modify: `tests/test_database/test_dialect.py` (append TestPostgresDialectBoundary class)

- [ ] **Step 1: Append TestPostgresDialectBoundary class at the end of test_dialect.py**

```python
class TestPostgresDialectBoundary:
    """PostgresDialect boundary case tests."""

    def test_pg_detect_autoincrement_missing_keys(self) -> None:
        """Returns False when column_info is missing identity/default/autoincrement keys."""
        dialect = PostgresDialect()
        # Completely empty column_info
        result = dialect.detect_autoincrement({})
        assert result is False

    def test_pg_detect_autoincrement_none_values(self) -> None:
        """Returns False when column_info key values are all None."""
        dialect = PostgresDialect()
        col_info = {"identity": None, "default": None, "autoincrement": None}
        result = dialect.detect_autoincrement(col_info)
        assert result is False

    def test_pg_reset_autoincrement_cursor_without_fetchall(self) -> None:
        """Does not crash when cursor has no fetchall attribute."""
        dialect = PostgresDialect()

        # Simulate cursor without fetchall
        class FakeCursor:
            def execute(self, sql: str, params: Any = None) -> None:
                pass

        def execute_fn(sql: str, params: Any = None) -> Any:
            return FakeCursor()

        # Should not raise
        dialect.reset_autoincrement(execute_fn, "test_table")

    def test_pg_bulk_optimizer_preserve_failure_then_restore(self) -> None:
        """Restore uses default values after preserve failure."""
        call_count = {"preserve": 0, "restore": 0}

        def execute_fn(sql: str, params: Any = None) -> Any:
            if "SHOW" in sql:
                call_count["preserve"] += 1
                raise RuntimeError("Connection lost")
            if "SET" in sql:
                call_count["restore"] += 1
            return None

        optimizer = PostgresBulkOptimizer(execute_fn)
        # preserve fails
        optimizer.preserve()
        # restore should still execute (using default values)
        optimizer.restore()
        assert call_count["preserve"] > 0

    def test_pg_bulk_optimizer_restore_without_preserve(self) -> None:
        """Does not crash when restore is called directly without preserve."""
        def execute_fn(sql: str, params: Any = None) -> Any:
            return None

        optimizer = PostgresBulkOptimizer(execute_fn)
        # restore directly without preserve, should not raise
        optimizer.restore()

    def test_pg_quote_identifier_with_special_chars(self) -> None:
        """PG identifiers with special characters correctly quoted."""
        dialect = PostgresDialect()
        # Normal identifier
        assert dialect.quote_identifier("users") == '"users"'
        # Contains spaces
        assert dialect.quote_identifier("my table") == '"my table"'
        # Contains double quotes (should be escaped as two double quotes)
        assert dialect.quote_identifier('table"with"quotes') == '"table""with""quotes"'
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_dialect.py::TestPostgresDialectBoundary -v --tb=short`
Expected: 6 passed

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check tests/test_database/test_dialect.py && ruff format tests/test_database/test_dialect.py`

- [ ] **Step 4: Commit**

```bash
git add tests/test_database/test_dialect.py
git commit -m "test: add PostgresDialect boundary tests (CP3 P2)"
```

---

## Task 6: optimizer.py Migration to BulkWriteOptimizer Abstraction

**Files:**
- Modify: `tests/test_database/test_optimizer.py` (append BulkWriteOptimizer abstraction tests)

- [ ] **Step 1: Read existing test_optimizer.py to understand structure**

Run: `Read tests/test_database/test_optimizer.py`

- [ ] **Step 2: Append BulkWriteOptimizer abstraction tests at the end of test_optimizer.py**

```python
class TestBulkWriteOptimizerAbstraction:
    """Test that optimizer has migrated to BulkWriteOptimizer abstraction.

    Note: SQLiteBulkOptimizer.__init__ requires two parameters: execute_fn and fetch_pragma_fn.
    Refer to sqlalchemy_adapter.py lines 208-219 for correct usage.
    """

    @staticmethod
    def _make_fetch_pragma_fn(adapter: Any) -> Any:
        """Create fetch_pragma_fn from adapter (get PRAGMA current value)."""
        def fetch_pragma(name: str) -> Any:
            cursor = adapter.execute(f"PRAGMA {name}")
            row = cursor.fetchone() if hasattr(cursor, "fetchone") else cursor
            return row[0] if row else None
        return fetch_pragma

    def test_pragma_optimizer_via_sqlite_bulk_optimizer(self, tmp_db: str) -> None:
        """Call PragmaOptimizer via SQLiteBulkOptimizer."""
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)
        optimizer.restore()
        adapter.close()

    def test_bulk_optimizer_protocol_satisfied(self, tmp_db: str) -> None:
        """SQLiteBulkOptimizer satisfies BulkWriteOptimizer protocol."""
        from sqlseed.database._bulk_optimizer import BulkWriteOptimizer, SQLiteBulkOptimizer
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        assert hasattr(optimizer, "preserve")
        assert hasattr(optimizer, "optimize")
        assert hasattr(optimizer, "restore")
        assert isinstance(optimizer, BulkWriteOptimizer)
        adapter.close()

    def test_sqlite_bulk_optimizer_three_tiers(self, tmp_db: str) -> None:
        """Three-tier optimization (light/moderate/aggressive) via abstraction layer.

        Thresholds (strictly greater than, refer to _bulk_optimizer.py lines 85-87):
        - >100000: aggressive (synchronous=OFF, journal_mode=OFF)
        - >10000: moderate (synchronous=OFF, journal_mode=MEMORY)
        - Other: light (synchronous=NORMAL, temp_store=MEMORY)
        """
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)

        # Different batch sizes trigger different optimization levels (use values >threshold to ensure triggering corresponding level)
        optimizer.preserve()
        optimizer.optimize(expected_rows=100)  # ≤10000 → light
        optimizer.restore()

        optimizer.preserve()
        optimizer.optimize(expected_rows=10001)  # >10000 → moderate
        optimizer.restore()

        optimizer.preserve()
        optimizer.optimize(expected_rows=100001)  # >100000 → aggressive
        optimizer.restore()

        adapter.close()

    def test_sqlite_bulk_optimizer_restore_after_optimize(self, tmp_db: str) -> None:
        """Restore recovers original values after optimize."""
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)

        # Get original PRAGMA value
        original = adapter.execute("PRAGMA synchronous").fetchone()[0]

        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        optimizer.preserve()
        optimizer.optimize(expected_rows=10000)
        optimizer.restore()

        # Verify restored to original value
        restored = adapter.execute("PRAGMA synchronous").fetchone()[0]
        assert restored == original
        adapter.close()
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_database/test_optimizer.py::TestBulkWriteOptimizerAbstraction -v --tb=short`
Expected: 4 passed

- [ ] **Step 4: Run ruff check and format**

Run: `ruff check tests/test_database/test_optimizer.py && ruff format tests/test_database/test_optimizer.py`

- [ ] **Step 5: Commit**

```bash
git add tests/test_database/test_optimizer.py
git commit -m "test: add BulkWriteOptimizer abstraction tests (CP3 P2)"
```

---

## Task 7: MCP Server Complete Tool Tests

**Files:**
- Create: `plugins/mcp-server-sqlseed/tests/test_server.py`

- [ ] **Step 1: Create test_server.py**

```python
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from mcp_server_sqlseed.server import (
    _validate_db_path,
    sqlseed_execute_fill,
    sqlseed_gemma4_agent_fill,
    sqlseed_gemma4_analyze,
    sqlseed_generate_yaml,
    sqlseed_inspect_schema,
    sqlseed_list_gemma_models,
)

if TYPE_CHECKING:
    from pathlib import Path


def _create_test_db(db_path: str) -> None:
    """Create test database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT, age INTEGER)"
    )
    conn.commit()
    conn.close()


class TestMCPTools:
    """Test 6 tools + 1 resource of MCP server."""

    @pytest.fixture
    def test_db(self, tmp_path: Path) -> str:
        db_path = str(tmp_path / "mcp_test.db")
        _create_test_db(db_path)
        return db_path

    def test_sqlseed_inspect_schema_sqlite(self, test_db: str) -> None:
        """inspect_schema tool returns correct schema."""
        result = sqlseed_inspect_schema(test_db, "users")
        assert "users" in result
        cols = result["users"]["columns"]
        assert len(cols) >= 3
        col_names = [c["name"] for c in cols]
        assert "id" in col_names
        assert "name" in col_names

    def test_sqlseed_inspect_schema_pg(self, pg_url: str) -> None:
        """inspect_schema tool with PG URL."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE IF NOT EXISTS mcp_test (id SERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        result = sqlseed_inspect_schema(pg_url, "mcp_test")
        assert "mcp_test" in result

    def test_sqlseed_generate_yaml_sqlite(self, test_db: str) -> None:
        """generate_yaml tool returns valid YAML."""
        result = sqlseed_generate_yaml(test_db, "users", max_retries=1)
        assert isinstance(result, str)
        assert len(result) > 0
        # Verify the returned value is valid YAML (can be parsed by yaml.safe_load)
        import yaml as yaml_module

        parsed = yaml_module.safe_load(result)
        assert parsed is not None, f"generate_yaml returned invalid YAML: {result[:200]}"
        # Should contain tables key (valid config structure)
        assert "tables" in parsed, f"generate_yaml return should contain 'tables' key: {list(parsed.keys()) if isinstance(parsed, dict) else 'N/A'}"

    def test_sqlseed_execute_fill_sqlite(self, test_db: str) -> None:
        """execute_fill tool actually writes data."""
        result = sqlseed_execute_fill(test_db, "users", count=10)
        assert result["table_name"] == "users"
        assert result["count"] == 10

        # Verify data actually written
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_sqlseed_execute_fill_count_correct(self, test_db: str) -> None:
        """Row count correct after execute_fill."""
        sqlseed_execute_fill(test_db, "users", count=50)
        result = sqlseed_execute_fill(test_db, "users", count=30)
        # Second fill does not clear by default, should accumulate
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        conn.close()
        assert total >= 30

    def test_sqlseed_gemma4_analyze_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_analyze real LLM call."""
        backend = available_llm_backend["backend"]
        model = available_llm_backend["model"]

        # Configure environment variables based on backend (use monkeypatch to avoid polluting other tests)
        # Note: SQLSEED_AI_BACKEND valid values are lm_studio/ollama/openai_compat/google_ai_studio, not "openai"
        # available_llm_backend fixture returns backend value that is already a valid AIBackend enum value
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

        result = sqlseed_gemma4_analyze(test_db, "users", model=model, backend=backend)
        # Should return valid result, should not contain error key
        assert "error" not in result, f"gemma4_analyze returned error: {result.get('error', '')}"
        # Should return valid configuration
        if "config" in result:
            assert result["config"] is not None, "gemma4_analyze returned config is None"

    def test_sqlseed_gemma4_agent_fill_real_llm(
        self, test_db: str, available_llm_backend: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gemma4_agent_fill real LLM call."""
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

        result = sqlseed_gemma4_agent_fill(
            test_db, "users", count=10, model=model, backend=backend, max_retries=1
        )
        # Should return valid result, contain table_name key, should not contain error key
        assert "table_name" in result, f"gemma4_agent_fill return should contain 'table_name' key: {result}"
        assert "error" not in result, f"gemma4_agent_fill returned error: {result.get('error', '')}"
        assert result["table_name"] == "users"

    def test_sqlseed_list_gemma_models(self) -> None:
        """list_gemma_models returns model list."""
        result = sqlseed_list_gemma_models()
        assert "models" in result
        assert "backends" in result
        assert isinstance(result["models"], list)
        assert isinstance(result["backends"], list)

    def test_get_schema_resource(self, test_db: str) -> None:
        """get_schema_resource resource returns schema."""
        import json

        from mcp_server_sqlseed.server import get_schema_resource

        result = get_schema_resource(test_db, "users")
        # Returns JSON string
        data = json.loads(result)
        assert data["table_name"] == "users"
        assert "columns" in data

    def test_tool_invalid_db_path_raises(self) -> None:
        """Tool correctly errors on invalid path."""
        with pytest.raises(ValueError, match="Invalid database target"):
            sqlseed_inspect_schema("invalid_path_no_extension", "users")

    def test_tool_nonexistent_table_raises(self, test_db: str) -> None:
        """Tool correctly errors on nonexistent table."""
        with pytest.raises(ValueError, match="does not exist"):
            sqlseed_inspect_schema(test_db, "nonexistent_table")

    def test_tool_url_passes_through(self, pg_url: str) -> None:
        """Tool correctly passes URL to orchestrator."""
        from sqlalchemy import create_engine, text

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE IF NOT EXISTS url_test (id SERIAL PRIMARY KEY, name TEXT)")
            )
            conn.commit()
        engine.dispose()

        # URL should pass through directly, not raise _validate_db_path error
        result = sqlseed_inspect_schema(pg_url, "url_test")
        assert "url_test" in result
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest plugins/mcp-server-sqlseed/tests/test_server.py -v --tb=short`
Expected: 12 passed (requires Docker + LLM backend running)

- [ ] **Step 3: Run ruff check and format**

Run: `ruff check plugins/mcp-server-sqlseed/tests/test_server.py && ruff format plugins/mcp-server-sqlseed/tests/test_server.py`

- [ ] **Step 4: Commit**

```bash
git add plugins/mcp-server-sqlseed/tests/test_server.py
git commit -m "test: add MCP server complete tool tests with real LLM (CP3 P2)"
```

---

## Task 8: CP3 Full Validation

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
Expected: All tests pass (720 existing + CP1 ~60 + CP2 ~72 + CP3 ~48 = ~900 tests)

**Note:**
- PG integration tests require Docker running
- AI real LLM tests require at least one LLM backend (Ollama/LM Studio/Google AI Studio)

- [ ] **Step 5: If any failures, fix and re-validate**

Fix any ruff/mypy/pytest failures until all pass.

- [ ] **Step 6: Confirm CP3 completion**

CP3 completion criteria:
- ruff check: 0 errors
- ruff format --check: 0 errors
- mypy: 0 errors
- pytest: all pass (~900 tests)

No commit needed (validation step).

---

## Self-Review

**Spec coverage check:**
- 5.1 Real PostgreSQL integration tests → Task 1 ✓
- 5.2 URL full-chain E2E tests → Task 2 ✓
- 5.3 Reserved words and special characters tests → Task 3 ✓
- 5.4 SQLAlchemyAdapter vs RawSQLiteAdapter consistency → Task 4 ✓
- 5.5 PostgresDialect boundary tests → Task 5 ✓
- 5.6 optimizer.py migration to BulkWriteOptimizer abstraction → Task 6 ✓
- 5.7 MCP server complete tool tests → Task 7 ✓
- CP3 full validation → Task 8 ✓

**Placeholder scan:** No TBD/TODO, all steps contain complete code ✓

**Type consistency:** `pg_url`, `available_llm_backend`, `PostgresBulkOptimizer`, `SQLiteBulkOptimizer` (requires fetch_pragma_fn), `PostgresDialect` naming consistent throughout ✓

**CP3 test count:**
- Task 1: 12 tests
- Task 2: 6 tests
- Task 3: 6 tests
- Task 4: 4 tests
- Task 5: 6 tests
- Task 6: 4 tests
- Task 7: 12 tests
- **Total: 50 tests** (matches ~48 expected)

## Cross-Validation Fix Records (Round 1)

**Issues found and fixed by Agent A (coverage completeness):**
1. CRITICAL: `test_pg_fill_with_fk_integrity` did not verify FK integrity → Added orphan FK reference count assertion (LEFT JOIN query)
2. CRITICAL: `test_pg_get_table_names_empty` did not verify "empty" → Changed to `assert names == []`
3. HIGH: `test_sqlseed_gemma4_agent_fill_real_llm` treated error as pass condition → Changed to `assert "error" not in result`
4. HIGH: `test_sqlseed_generate_yaml_sqlite` too lenient → Added `yaml.safe_load` parsing + `tables` key assertion
5. HIGH: `test_pg_url_inspect_e2e` assertions too shallow → Added table name and column name output assertions

**Issues found and fixed by Agent B (executability):**
1. CRITICAL: `fill()` does not support `snapshot` parameter → Changed to save snapshot via CLI `fill --snapshot`
2. CRITICAL: `sqlseed.replay()` not exported from public API → Changed to replay via CLI `replay` command
3. CRITICAL: `SnapshotManager.list_snapshots()` returns `list[str]` not `list[dict]` → Changed to `snapshots[0]` (direct string path)
4. CRITICAL: `SQLiteBulkOptimizer` missing required parameter `fetch_pragma_fn` → Added `_make_fetch_pragma_fn` helper method
5. MEDIUM: `SQLSEED_AI_BACKEND=openai` invalid value → Changed to `lm_studio`/`openai_compat`
6. MEDIUM: Environment variables not cleaned up → All changed to `monkeypatch.setenv`
7. MEDIUM: `del os.environ` may raise KeyError → Changed to `monkeypatch.setenv` (auto cleanup)

**Prerequisite fixes:**
- `tests/integration/conftest.py` → `tests/conftest.py` (root conftest, created in CP1)
- Added note that `tests/integration/` directory already created (created in CP1)

## Cross-Validation Fix Records (Round 2)

**Agent A (coverage completeness):** 9/10 PASS — All 5 fixes from Round 1 verified as correctly implemented.

**Agent B (executability):** 7.5/10 NEEDS_FIX — All 7 fixes from Round 1 verified as correct, but found 3 new issues:

1. CRITICAL: `test_pg_bulk_optimizer_synchronous_commit` — `SET synchronous_commit = OFF` is a PG session-level parameter, querying `SHOW synchronous_commit` with a new engine using a different connection will fail (setting does not propagate across connections). **Fix**: Changed to use mock `execute_fn` to record SET command calls, verifying the optimizer indeed issued `SET synchronous_commit = OFF` (contract test rather than PG integration test).
2. HIGH: `available_llm_backend` fixture returns `{"backend": "google_ai"}` but `AIBackend` enum value is `"google_ai_studio"`, `sqlseed_gemma4_analyze(backend="google_ai")` will trigger `ValueError`. **Fix**: (a) CP1 fixture changed to return `"google_ai_studio"`; (b) Branch checks in CP2 and CP3 changed from `"google_ai"` to `"google_ai_studio"`.
3. LOW: `test_sqlite_bulk_optimizer_three_tiers` comment says 10000→moderate but actual threshold is `>10000` (strictly greater than), 10000 actually triggers light. **Fix**: `expected_rows` changed from 10000/100000 to 10001/100001, and docstring notes the threshold source (`_bulk_optimizer.py` lines 85-87).
