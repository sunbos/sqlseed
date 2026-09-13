"""Integration tests for PostgreSQL with sqlseed."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, text

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database._bulk_optimizer import PostgresBulkOptimizer
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

pytestmark = pytest.mark.integration


class TestPostgreSQLIntegration:
    """Real PostgreSQL integration tests (depend on testcontainers)."""

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
        assert names == [], f"Empty PG database should return [], got: {names}"
        adapter.close()

    def test_pg_create_table_and_get_column_info(self, pg_url: str) -> None:
        """After creating a table, get_column_info correctly identifies types."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE test_users (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)")
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
        """SERIAL column is detected as autoincrement."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE serial_test (id SERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("serial_test")
        id_col = next(c for c in cols if c.name == "id")
        assert id_col.is_autoincrement is True
        adapter.close()

    def test_pg_bigserial_autoincrement_detection(self, pg_url: str) -> None:
        """BIGSERIAL column is detected as autoincrement."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE bigserial_test (id BIGSERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        cols = adapter.get_column_info("bigserial_test")
        id_col = next(c for c in cols if c.name == "id")
        assert id_col.is_autoincrement is True
        adapter.close()

    def test_pg_identity_autoincrement_detection(self, pg_url: str) -> None:
        """GENERATED AS IDENTITY column is detected as autoincrement."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE identity_test (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT)")
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
        """After batch insert, the row count is correct."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE insert_test (id SERIAL PRIMARY KEY, name TEXT NOT NULL)"))
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
        """After clear_table, the sequence is reset (real pg_get_serial_sequence)."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE seq_reset_test (id SERIAL PRIMARY KEY, name TEXT)"))
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
        """fill(url=pg_url, table=..., count=100) full flow."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(
                text("CREATE TABLE fill_test (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)")
            )
            conn.commit()
        engine.dispose()

        result = sqlseed.fill(url=pg_url, table="fill_test", count=100, provider="base")
        assert result.count == 100

    def test_pg_fill_with_fk_integrity(self, pg_url: str) -> None:
        """FK-related table data integrity on PG."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE fk_users (id SERIAL PRIMARY KEY, name TEXT NOT NULL)"))
            conn.execute(
                text(
                    "CREATE TABLE fk_orders "
                    "(id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES fk_users(id), amount REAL)"
                )
            )
            conn.commit()
        engine.dispose()

        # Fill the parent table first
        sqlseed.fill(url=pg_url, table="fk_users", count=10, provider="base")
        # Then fill the child table
        result = sqlseed.fill(url=pg_url, table="fk_orders", count=20, provider="base")
        assert result.count == 20

        # Verify FK integrity: fk_orders.user_id must all exist in fk_users.id
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            # Find orphaned FK references (rows where user_id is not in fk_users.id)
            orphan_count = conn.execute(
                text("SELECT COUNT(*) FROM fk_orders o LEFT JOIN fk_users u ON o.user_id = u.id WHERE u.id IS NULL")
            ).scalar()
        engine.dispose()
        assert orphan_count == 0, f"Found {orphan_count} orphaned FK references, FK integrity broken"

    def test_pg_bulk_optimizer_synchronous_commit(self, pg_url: str) -> None:
        """Verify synchronous_commit=OFF is called (using mock to avoid connection pool session isolation issues).

        Note: synchronous_commit is a PG session-level parameter. The SQLAlchemy connection
        pool may execute SET and SHOW on different connections, making it impossible to verify
        via actual queries whether SET took effect. Instead, we use a mock execute_fn to
        record SET command calls and verify that the optimizer did issue SET synchronous_commit = OFF.
        This is a contract test of optimizer behavior, not a test of PG itself.
        """
        del pg_url
        set_calls: list[str] = []

        class _FakeResult:
            """Mock result of the SHOW command."""

            def fetchone(self) -> tuple[str, ...]:
                return ("on",)

        def execute_fn(sql: str, _params: Any = None) -> _FakeResult:
            sql_upper = sql.upper()
            # Record all SET commands
            if "SET" in sql_upper:
                set_calls.append(sql)
            # SHOW command returns the original value "on"
            return _FakeResult()

        optimizer = PostgresBulkOptimizer(execute_fn)
        optimizer.preserve()
        optimizer.optimize(expected_rows=20000)

        # Verify that SET synchronous_commit = OFF was called
        sync_off_calls = [s for s in set_calls if "synchronous_commit" in s.lower() and "off" in s.lower()]
        assert len(sync_off_calls) > 0, f"SET synchronous_commit = OFF was not called, actual SET calls: {set_calls}"

        optimizer.restore()

    def test_pg_dialect_in_schema_context(self, pg_url: str) -> None:
        """On PG, get_schema_context returns dialect="postgresql"."""
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE ctx_test (id SERIAL PRIMARY KEY, name TEXT)"))
            conn.commit()
        engine.dispose()

        with DataOrchestrator(pg_url, provider_name="base") as orch:
            orch._ensure_connected()
            ctx = orch.get_schema_context("ctx_test")
            assert ctx.get("dialect") == "postgresql"
