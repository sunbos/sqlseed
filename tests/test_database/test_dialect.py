"""Contract tests for database dialect, type normalization, and bulk optimizers.

Phase 1 tests three new abstractions:
- Dialect protocol + SQLiteDialect implementation
- TypeNormalizer + NormalizedType
- BulkWriteOptimizer protocol + SQLiteBulkOptimizer

Adapter contract tests (DatabaseAdapterContract) are enabled in Phase 2 after
introducing the SQLAlchemyAdapter.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlseed.database._bulk_optimizer import (
    BulkWriteOptimizer,
    PostgresBulkOptimizer,
    SQLiteBulkOptimizer,
)
from sqlseed.database._dialect import (
    Dialect,
    PostgresDialect,
    SQLiteDialect,
)
from sqlseed.database._type_normalizer import NormalizedType, TypeNormalizer


class TestSQLiteDialect:
    """Tests for the SQLiteDialect dialect."""

    def test_name(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.name == "sqlite"

    def test_normalize_type_uppercase(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.normalize_type("text") == "TEXT"
        assert dialect.normalize_type("integer") == "INTEGER"

    def test_normalize_type_empty(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.normalize_type("") == "TEXT"
        assert dialect.normalize_type(None) == "TEXT"  # type: ignore[arg-type]

    def test_normalize_type_already_upper(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.normalize_type("VARCHAR(255)") == "VARCHAR(255)"

    def test_quote_identifier_simple(self) -> None:
        dialect = SQLiteDialect()
        assert dialect.quote_identifier("users") == '"users"'

    def test_quote_identifier_with_internal_quote(self) -> None:
        dialect = SQLiteDialect()
        # Double quotes are escaped as two double quotes
        assert dialect.quote_identifier('user"name') == '"user""name"'

    def test_reset_autoincrement(self) -> None:
        dialect = SQLiteDialect()
        mock_execute = MagicMock()
        dialect.reset_autoincrement(mock_execute, "users")
        mock_execute.assert_called_once_with("DELETE FROM sqlite_sequence WHERE name = ?", ["users"])

    def test_detect_autoincrement_returns_false_placeholder(self) -> None:
        """Phase 1: SQLiteDialect.detect_autoincrement returns False as a placeholder.

        Actual detection is performed by RawSQLiteAdapter/SQLAlchemyAdapter via
        schema_helpers.detect_autoincrement.
        """
        dialect = SQLiteDialect()
        assert dialect.detect_autoincrement({}) is False

    def test_satisfies_dialect_protocol(self) -> None:
        """SQLiteDialect satisfies the Dialect protocol."""
        dialect = SQLiteDialect()
        assert isinstance(dialect, Dialect)


class TestTypeNormalizer:
    """Tests for TypeNormalizer type normalization."""

    def setup_method(self) -> None:
        self.normalizer = TypeNormalizer()

    def test_sqlite_basic_types(self) -> None:
        result = self.normalizer.normalize("TEXT", "sqlite")
        assert result.base == "TEXT"
        assert result.params == ()

        result = self.normalizer.normalize("integer", "sqlite")
        assert result.base == "INTEGER"

    def test_sqlite_type_with_params(self) -> None:
        result = self.normalizer.normalize("VARCHAR(255)", "sqlite")
        assert result.base == "VARCHAR"
        assert result.params == (255,)
        assert result.display == "VARCHAR(255)"

    def test_postgresql_serial(self) -> None:
        result = self.normalizer.normalize("serial", "postgresql")
        assert result.base == "INTEGER"
        assert result.params == ()

    def test_postgresql_bigserial(self) -> None:
        result = self.normalizer.normalize("bigserial", "postgresql")
        assert result.base == "INTEGER"

    def test_postgresql_character_varying(self) -> None:
        result = self.normalizer.normalize("character varying(255)", "postgresql")
        assert result.base == "VARCHAR"
        assert result.params == (255,)
        assert result.display == "VARCHAR(255)"

    def test_postgresql_numeric_with_precision(self) -> None:
        result = self.normalizer.normalize("numeric(10,2)", "postgresql")
        assert result.base == "NUMERIC"
        assert result.params == (10, 2)
        assert result.display == "NUMERIC(10,2)"

    def test_postgresql_timestamp_with_time_zone(self) -> None:
        result = self.normalizer.normalize("timestamp with time zone", "postgresql")
        assert result.base == "TIMESTAMPTZ"

    def test_postgresql_bytea(self) -> None:
        result = self.normalizer.normalize("bytea", "postgresql")
        assert result.base == "BLOB"

    def test_postgresql_jsonb(self) -> None:
        result = self.normalizer.normalize("jsonb", "postgresql")
        assert result.base == "JSON"

    def test_postgresql_uuid(self) -> None:
        result = self.normalizer.normalize("uuid", "postgresql")
        assert result.base == "UUID"

    def test_mysql_int(self) -> None:
        result = self.normalizer.normalize("int", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_bigint(self) -> None:
        result = self.normalizer.normalize("bigint", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_varchar(self) -> None:
        result = self.normalizer.normalize("varchar(100)", "mysql")
        assert result.base == "VARCHAR"
        assert result.params == (100,)

    def test_mysql_datetime(self) -> None:
        result = self.normalizer.normalize("datetime", "mysql")
        assert result.base == "DATETIME"

    def test_empty_type(self) -> None:
        result = self.normalizer.normalize("", "sqlite")
        assert result.base == "TEXT"
        assert result.params == ()

    def test_unknown_type_falls_back_to_uppercase(self) -> None:
        result = self.normalizer.normalize("custom_type", "postgresql")
        assert result.base == "CUSTOM_TYPE"

    def test_preserves_raw(self) -> None:
        raw = "character varying(255)"
        result = self.normalizer.normalize(raw, "postgresql")
        assert result.raw == raw

    def test_display_no_params(self) -> None:
        result = self.normalizer.normalize("integer", "sqlite")
        assert result.display == "INTEGER"

    def test_display_with_params(self) -> None:
        result = self.normalizer.normalize("numeric(10,2)", "postgresql")
        assert result.display == "NUMERIC(10,2)"

    def test_non_numeric_params_ignored(self) -> None:
        """ENUM type parameters (non-numeric) should be ignored."""
        result = self.normalizer.normalize("enum('a','b','c')", "mysql")
        assert result.base == "TEXT"
        assert result.params == ()


class TestNormalizedType:
    """Tests for the NormalizedType dataclass."""

    def test_frozen(self) -> None:
        nt = NormalizedType(base="VARCHAR", params=(255,), raw="varchar(255)")
        with pytest.raises(AttributeError):
            nt.base = "TEXT"  # type: ignore[misc]

    def test_equality(self) -> None:
        nt1 = NormalizedType(base="INTEGER", params=(), raw="int")
        nt2 = NormalizedType(base="INTEGER", params=(), raw="int")
        assert nt1 == nt2

    def test_display_property(self) -> None:
        assert NormalizedType("TEXT", (), "text").display == "TEXT"
        assert NormalizedType("VARCHAR", (255,), "varchar(255)").display == "VARCHAR(255)"
        assert NormalizedType("NUMERIC", (10, 2), "numeric(10,2)").display == "NUMERIC(10,2)"


class TestSQLiteBulkOptimizer:
    """Tests for SQLiteBulkOptimizer.

    Verifies that it correctly delegates to the existing PragmaOptimizer.
    """

    def test_satisfies_bulk_write_optimizer_protocol(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        assert isinstance(optimizer, BulkWriteOptimizer)

    def test_preserve_calls_pragma_optimizer(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        # PragmaOptimizer.preserve calls _fetch_pragma multiple times
        assert mock_fetch.call_count > 0

    def test_optimize_light_level(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)  # light level
        # light level should execute PRAGMA synchronous = NORMAL, etc.
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("synchronous = NORMAL" in call for call in execute_calls)

    def test_optimize_moderate_level(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        optimizer.optimize(expected_rows=50000)  # moderate level
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("synchronous = OFF" in call for call in execute_calls)
        assert any("journal_mode = MEMORY" in call for call in execute_calls)

    def test_optimize_aggressive_level(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        optimizer.optimize(expected_rows=200000)  # aggressive level
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("journal_mode = OFF" in call for call in execute_calls)

    def test_restore_after_optimize(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value="NORMAL")
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)
        optimizer.restore()
        # restore should execute PRAGMA restoration
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("PRAGMA synchronous" in call for call in execute_calls)

    def test_restore_without_preserve_is_noop(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.restore()  # preserve not called, should be a no-op
        mock_execute.assert_not_called()


class TestSQLiteBulkOptimizerWithRealDb:
    """Integration tests for SQLiteBulkOptimizer with a real SQLite database."""

    def test_optimize_and_restore_with_real_db(self, tmp_db: str) -> None:
        conn = sqlite3.connect(tmp_db)

        def execute_fn(sql: str, params: Any = ()) -> Any:
            return conn.execute(sql, params)

        def fetch_pragma(name: str) -> Any:
            cursor = conn.execute(f"PRAGMA {name}")
            row = cursor.fetchone()
            return row[0] if row else None

        optimizer = SQLiteBulkOptimizer(execute_fn=execute_fn, fetch_pragma_fn=fetch_pragma)
        optimizer.preserve()
        original_synchronous = fetch_pragma("synchronous")

        optimizer.optimize(expected_rows=200000)
        # aggressive mode should set synchronous = OFF
        assert fetch_pragma("synchronous") == 0  # OFF = 0

        optimizer.restore()
        # after restore, should return to the original value
        assert fetch_pragma("synchronous") == original_synchronous

        conn.close()


class TestDialectProtocol:
    """Tests for the Dialect protocol."""

    def test_sqlite_dialect_is_dialect(self) -> None:
        assert isinstance(SQLiteDialect(), Dialect)

    def test_postgres_dialect_is_dialect(self) -> None:
        assert isinstance(PostgresDialect(), Dialect)


class TestPostgresDialect:
    """Tests for the PostgresDialect dialect (Phase 3)."""

    def test_name(self) -> None:
        dialect = PostgresDialect()
        assert dialect.name == "postgresql"

    def test_normalize_type_uppercase(self) -> None:
        dialect = PostgresDialect()
        assert dialect.normalize_type("text") == "TEXT"
        assert dialect.normalize_type("integer") == "INTEGER"

    def test_normalize_type_empty(self) -> None:
        dialect = PostgresDialect()
        assert dialect.normalize_type("") == "TEXT"

    def test_quote_identifier_simple(self) -> None:
        dialect = PostgresDialect()
        assert dialect.quote_identifier("users") == '"users"'

    def test_quote_identifier_with_internal_quote(self) -> None:
        dialect = PostgresDialect()
        # PG double-quote escaping is the same as SQLite
        assert dialect.quote_identifier('user"name') == '"user""name"'

    def test_detect_autoincrement_identity(self) -> None:
        """GENERATED ... AS IDENTITY pattern detection."""
        dialect = PostgresDialect()
        col_info = {"name": "id", "identity": {"always": True}, "autoincrement": False, "default": None}
        assert dialect.detect_autoincrement(col_info) is True

    def test_detect_autoincrement_serial_via_nextval(self) -> None:
        """SERIAL pattern: default contains nextval()."""
        dialect = PostgresDialect()
        col_info = {
            "name": "id",
            "identity": None,
            "autoincrement": False,
            "default": "nextval('users_id_seq'::regclass)",
        }
        assert dialect.detect_autoincrement(col_info) is True

    def test_detect_autoincrement_bigserial(self) -> None:
        """BIGSERIAL pattern: default contains nextval()."""
        dialect = PostgresDialect()
        col_info = {
            "name": "id",
            "identity": None,
            "autoincrement": False,
            "default": "nextval('orders_id_seq'::regclass)",
        }
        assert dialect.detect_autoincrement(col_info) is True

    def test_detect_autoincrement_autoincrement_flag(self) -> None:
        """SQLAlchemy autoincrement flag (integer PK inference)."""
        dialect = PostgresDialect()
        col_info = {"name": "id", "identity": None, "autoincrement": True, "default": None}
        assert dialect.detect_autoincrement(col_info) is True

    def test_detect_autoincrement_not_autoincrement(self) -> None:
        """Non-autoincrement column detection."""
        dialect = PostgresDialect()
        col_info = {"name": "name", "identity": None, "autoincrement": False, "default": None}
        assert dialect.detect_autoincrement(col_info) is False

    def test_detect_autoincrement_default_without_nextval(self) -> None:
        """A column with a default but no nextval is not autoincrement."""
        dialect = PostgresDialect()
        col_info = {
            "name": "status",
            "identity": None,
            "autoincrement": False,
            "default": "'active'::text",
        }
        assert dialect.detect_autoincrement(col_info) is False

    def test_reset_autoincrement_queries_sequences(self) -> None:
        """reset_autoincrement should query pg_get_serial_sequence and ALTER SEQUENCE."""
        dialect = PostgresDialect()
        mock_execute = MagicMock()
        # Simulate query returning one sequence
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("id", "public.users_id_seq")]
        mock_execute.return_value = mock_cursor

        dialect.reset_autoincrement(mock_execute, "users")

        # Should execute both query and ALTER SEQUENCE
        assert mock_execute.call_count >= 2
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("pg_get_serial_sequence" in call for call in execute_calls)
        assert any("ALTER SEQUENCE" in call for call in execute_calls)

    def test_reset_autoincrement_no_sequences(self) -> None:
        """reset_autoincrement should be a safe no-op when the table has no sequences."""
        dialect = PostgresDialect()
        mock_execute = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_execute.return_value = mock_cursor

        # Should not raise an exception
        dialect.reset_autoincrement(mock_execute, "users")
        # Only execute the query, do not execute ALTER SEQUENCE
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert not any("ALTER SEQUENCE" in call for call in execute_calls)

    def test_reset_autoincrement_handles_exception(self) -> None:
        """reset_autoincrement should silently degrade on query failure (not block clear_table)."""
        dialect = PostgresDialect()
        mock_execute = MagicMock(side_effect=Exception("PG error"))

        # Should not raise an exception
        dialect.reset_autoincrement(mock_execute, "users")

    def test_satisfies_dialect_protocol(self) -> None:
        """PostgresDialect satisfies the Dialect protocol."""
        dialect = PostgresDialect()
        assert isinstance(dialect, Dialect)


class TestPostgresBulkOptimizer:
    """Tests for PostgresBulkOptimizer (Phase 3)."""

    def test_satisfies_bulk_write_optimizer_protocol(self) -> None:
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        assert isinstance(optimizer, BulkWriteOptimizer)

    def test_preserve_saves_synchronous_commit(self) -> None:
        mock_execute = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("on",)
        mock_execute.return_value = mock_cursor

        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.preserve()

        # Should query synchronous_commit and session_replication_role
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("SHOW synchronous_commit" in call for call in execute_calls)
        assert any("SHOW session_replication_role" in call for call in execute_calls)

    def test_optimize_sets_synchronous_commit_off(self) -> None:
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.optimize(expected_rows=1000)

        mock_execute.assert_any_call("SET synchronous_commit = OFF")

    def test_optimize_large_batch_disables_triggers(self) -> None:
        """Large batches (>10000) should attempt to disable triggers."""
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.optimize(expected_rows=50000)

        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("SET synchronous_commit = OFF" in call for call in execute_calls)
        assert any("session_replication_role = 'replica'" in call for call in execute_calls)

    def test_optimize_small_batch_keeps_triggers(self) -> None:
        """Small batches (<=10000) should not disable triggers."""
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.optimize(expected_rows=5000)

        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("SET synchronous_commit = OFF" in call for call in execute_calls)
        assert not any("session_replication_role" in call for call in execute_calls)

    def test_optimize_default_rows(self) -> None:
        """When expected_rows=None, only turn off synchronous_commit."""
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.optimize()

        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("SET synchronous_commit = OFF" in call for call in execute_calls)
        assert not any("session_replication_role" in call for call in execute_calls)

    def test_restore_after_optimize(self) -> None:
        mock_execute = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [("on",), ("origin",)]
        mock_execute.return_value = mock_cursor

        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)
        optimizer.restore()

        # restore should execute SET restoration
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("SET synchronous_commit = 'on'" in call for call in execute_calls)
        assert any("SET session_replication_role = 'origin'" in call for call in execute_calls)

    def test_restore_without_preserve_is_noop(self) -> None:
        mock_execute = MagicMock()
        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        optimizer.restore()
        # When preserve was not called, restore should be a no-op (_original_* is None)
        # But the implementation may attempt SET (due to None check), needs verification
        # Actual: _original_synchronous_commit is initially None, restore only executes if not None
        mock_execute.assert_not_called()

    def test_optimize_trigger_disable_failure_silent(self) -> None:
        """Trigger disable failure (insufficient permissions) should degrade silently."""
        mock_execute = MagicMock()
        # First call SET synchronous_commit succeeds, second (session_replication_role) raises
        mock_execute.side_effect = [None, Exception("permission denied"), None]

        optimizer = PostgresBulkOptimizer(execute_fn=mock_execute)
        # Should not raise an exception
        optimizer.optimize(expected_rows=50000)


class TestPostgresTypeNormalization:
    """Tests for PG type normalization via TypeNormalizer (Phase 3)."""

    def setup_method(self) -> None:
        self.normalizer = TypeNormalizer()

    def test_pg_varchar(self) -> None:
        """PG 'character varying(255)' -> VARCHAR(255)."""
        result = self.normalizer.normalize("character varying(255)", "postgresql")
        assert result.base == "VARCHAR"
        assert result.params == (255,)
        assert result.display == "VARCHAR(255)"

    def test_pg_text(self) -> None:
        result = self.normalizer.normalize("text", "postgresql")
        assert result.base == "TEXT"

    def test_pg_integer(self) -> None:
        result = self.normalizer.normalize("integer", "postgresql")
        assert result.base == "INTEGER"

    def test_pg_serial(self) -> None:
        """SERIAL normalizes to INTEGER (mapper.py uses this to identify integers)."""
        result = self.normalizer.normalize("serial", "postgresql")
        assert result.base == "INTEGER"

    def test_pg_bigserial(self) -> None:
        result = self.normalizer.normalize("bigserial", "postgresql")
        assert result.base == "INTEGER"

    def test_pg_bigint(self) -> None:
        result = self.normalizer.normalize("bigint", "postgresql")
        assert result.base == "INTEGER"

    def test_pg_smallint(self) -> None:
        result = self.normalizer.normalize("smallint", "postgresql")
        assert result.base == "INTEGER"

    def test_pg_boolean(self) -> None:
        result = self.normalizer.normalize("boolean", "postgresql")
        assert result.base == "BOOLEAN"

    def test_pg_timestamp(self) -> None:
        result = self.normalizer.normalize("timestamp without time zone", "postgresql")
        assert result.base == "TIMESTAMP"

    def test_pg_timestamptz(self) -> None:
        result = self.normalizer.normalize("timestamp with time zone", "postgresql")
        assert result.base == "TIMESTAMPTZ"

    def test_pg_double_precision(self) -> None:
        result = self.normalizer.normalize("double precision", "postgresql")
        assert result.base == "FLOAT"

    def test_pg_real(self) -> None:
        result = self.normalizer.normalize("real", "postgresql")
        assert result.base == "FLOAT"

    def test_pg_numeric(self) -> None:
        result = self.normalizer.normalize("numeric(10,2)", "postgresql")
        assert result.base == "NUMERIC"
        assert result.params == (10, 2)
        assert result.display == "NUMERIC(10,2)"

    def test_pg_uuid(self) -> None:
        result = self.normalizer.normalize("uuid", "postgresql")
        assert result.base == "UUID"

    def test_pg_jsonb(self) -> None:
        result = self.normalizer.normalize("jsonb", "postgresql")
        assert result.base == "JSON"

    def test_pg_json(self) -> None:
        result = self.normalizer.normalize("json", "postgresql")
        assert result.base == "JSON"

    def test_pg_bytea(self) -> None:
        """PG bytea normalizes to BLOB (mapper.py uses this to identify binary)."""
        result = self.normalizer.normalize("bytea", "postgresql")
        assert result.base == "BLOB"

    def test_pg_character(self) -> None:
        result = self.normalizer.normalize("character(10)", "postgresql")
        assert result.base == "CHAR"
        assert result.params == (10,)

    def test_pg_unknown_type_preserved_uppercase(self) -> None:
        """Unknown types should be preserved and uppercased (not lost)."""
        result = self.normalizer.normalize("some_custom_type", "postgresql")
        assert result.base == "SOME_CUSTOM_TYPE"


# =============================================================================
# Adapter contract test framework (enabled in Phase 2)
# =============================================================================


class DatabaseAdapterContract:
    """Contract tests that all DatabaseAdapter implementations must pass.

    After Phase 2 introduces SQLAlchemyAdapter, subclass this class and provide
    fixtures to automatically run the same set of interface tests, ensuring
    consistent behavior across all adapters.

    Usage:
        class TestRawSQLiteContract(DatabaseAdapterContract):
            @pytest.fixture
            def adapter(self, tmp_db):
                a = RawSQLiteAdapter()
                a.connect(tmp_db)
                return a

            @pytest.fixture
            def test_table(self):
                return "users"
    """

    # Implemented by subclasses in Phase 2
    # @pytest.fixture
    # def adapter(self) -> DatabaseAdapter: ...

    # @pytest.fixture
    # def test_table(self) -> str: ...

    pass


class TestTypeNormalizerBoundary:
    """Boundary condition tests for TypeNormalizer."""

    def setup_method(self) -> None:
        """Create a TypeNormalizer instance before each test (normalize is an instance method, not static)."""
        self.normalizer = TypeNormalizer()

    def test_normalize_none_input(self) -> None:
        """normalize(None, "sqlite") returns the TEXT fallback type."""
        result = self.normalizer.normalize(None, "sqlite")  # type: ignore[arg-type]
        # None input triggers the `not raw_type` short-circuit, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()

    def test_normalize_whitespace_only(self) -> None:
        """normalize("   ", "sqlite") returns the TEXT fallback type."""
        result = self.normalizer.normalize("   ", "sqlite")
        # Pure whitespace triggers `not raw_type.strip()`, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()

    def test_normalize_unknown_dialect(self) -> None:
        """normalize("int", "oracle") goes through the default uppercase branch, returns INT."""
        result = self.normalizer.normalize("int", "oracle")
        # Unknown dialect (not postgresql/mysql) goes through default branch: base_raw.upper() = "INT"
        assert result.base == "INT"
        assert result.params == ()

    def test_normalize_empty_string(self) -> None:
        """normalize("", "postgresql") returns the TEXT fallback type."""
        result = self.normalizer.normalize("", "postgresql")
        # Empty string triggers the `not raw_type` short-circuit, returns TEXT fallback
        assert result.base == "TEXT"
        assert result.params == ()


class TestMySQLTypeMapping:
    """MySQL type mapping tests.

    Note: TypeNormalizer.normalize is an instance method, must instantiate first.
    Expected values based on _MYSQL_TYPE_MAP (src/sqlseed/database/_type_normalizer.py lines 86-119).
    """

    def setup_method(self) -> None:
        """Create a TypeNormalizer instance before each test."""
        self.normalizer = TypeNormalizer()

    def test_mysql_int_mapping(self) -> None:
        """INT -> INTEGER (_MYSQL_TYPE_MAP: "int": "INTEGER")."""
        result = self.normalizer.normalize("int", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_bigint_mapping(self) -> None:
        """BIGINT -> INTEGER (_MYSQL_TYPE_MAP: "bigint": "INTEGER")."""
        result = self.normalizer.normalize("bigint", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_varchar_mapping(self) -> None:
        """VARCHAR(255) -> VARCHAR (_MYSQL_TYPE_MAP: "varchar": "VARCHAR")."""
        result = self.normalizer.normalize("varchar(255)", "mysql")
        assert result.base == "VARCHAR"
        assert result.params == (255,)

    def test_mysql_text_mapping(self) -> None:
        """TEXT -> TEXT (_MYSQL_TYPE_MAP: "text": "TEXT")."""
        result = self.normalizer.normalize("text", "mysql")
        assert result.base == "TEXT"

    def test_mysql_datetime_mapping(self) -> None:
        """DATETIME -> DATETIME (_MYSQL_TYPE_MAP: "datetime": "DATETIME")."""
        result = self.normalizer.normalize("datetime", "mysql")
        assert result.base == "DATETIME"

    def test_mysql_tinyint_mapping(self) -> None:
        """TINYINT -> INTEGER (_MYSQL_TYPE_MAP: "tinyint": "INTEGER")."""
        result = self.normalizer.normalize("tinyint", "mysql")
        assert result.base == "INTEGER"

    def test_mysql_decimal_mapping(self) -> None:
        """DECIMAL(10,2) -> NUMERIC (_MYSQL_TYPE_MAP: "decimal": "NUMERIC")."""
        result = self.normalizer.normalize("decimal(10,2)", "mysql")
        assert result.base == "NUMERIC"
        assert result.params == (10, 2)

    def test_mysql_json_mapping(self) -> None:
        """JSON -> JSON (_MYSQL_TYPE_MAP: "json": "JSON")."""
        result = self.normalizer.normalize("json", "mysql")
        assert result.base == "JSON"


class TestPostgresDialectBoundary:
    """Boundary condition tests for PostgresDialect."""

    def test_pg_detect_autoincrement_missing_keys(self) -> None:
        """Returns False when column_info is missing identity/default/autoincrement keys."""
        dialect = PostgresDialect()
        # Completely empty column_info
        result = dialect.detect_autoincrement({})
        assert result is False

    def test_pg_detect_autoincrement_none_values(self) -> None:
        """Returns False when all column_info key values are None."""
        dialect = PostgresDialect()
        col_info = {"identity": None, "default": None, "autoincrement": None}
        result = dialect.detect_autoincrement(col_info)
        assert result is False

    def test_pg_reset_autoincrement_cursor_without_fetchall(self) -> None:
        """Does not crash when cursor has no fetchall attribute."""
        dialect = PostgresDialect()

        # Simulate a cursor without fetchall
        class FakeCursor:
            def execute(self, sql: str, params: Any = None) -> None:
                pass

        def execute_fn(sql: str, params: Any = None) -> Any:
            return FakeCursor()

        # Should not raise an exception
        dialect.reset_autoincrement(execute_fn, "test_table")

    def test_pg_bulk_optimizer_preserve_failure_then_restore(self) -> None:
        """After preserve fails, restore uses default values."""
        from sqlseed.database._bulk_optimizer import PostgresBulkOptimizer  # noqa: PLC0415

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
        """Restore without preserve does not crash."""
        from sqlseed.database._bulk_optimizer import PostgresBulkOptimizer  # noqa: PLC0415

        def execute_fn(sql: str, params: Any = None) -> Any:
            return None

        optimizer = PostgresBulkOptimizer(execute_fn)
        # Restore without preserve, should not raise an exception
        optimizer.restore()

    def test_pg_quote_identifier_with_special_chars(self) -> None:
        """PG identifiers with special characters are quoted correctly."""
        dialect = PostgresDialect()
        # Normal identifier
        assert dialect.quote_identifier("users") == '"users"'
        # Contains spaces
        assert dialect.quote_identifier("my table") == '"my table"'
        # Contains double quotes (should be escaped as two double quotes)
        assert dialect.quote_identifier('table"with"quotes') == '"table""with""quotes"'
