"""数据库方言、类型归一化、批量优化器的契约测试。

阶段 1 测试新增的三个抽象：
- Dialect 协议 + SQLiteDialect 实现
- TypeNormalizer + NormalizedType
- BulkWriteOptimizer 协议 + SQLiteBulkOptimizer

适配器契约测试（DatabaseAdapterContract）在阶段 2 引入 SQLAlchemyAdapter 后启用。
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from sqlseed.database._bulk_optimizer import BulkWriteOptimizer, SQLiteBulkOptimizer
from sqlseed.database._dialect import BatchInserter, Dialect, SQLiteDialect
from sqlseed.database._type_normalizer import NormalizedType, TypeNormalizer


class TestSQLiteDialect:
    """SQLiteDialect 方言测试。"""

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
        # 双引号转义为两个双引号
        assert dialect.quote_identifier('user"name') == '"user""name"'

    def test_reset_autoincrement(self) -> None:
        dialect = SQLiteDialect()
        mock_execute = MagicMock()
        dialect.reset_autoincrement(mock_execute, "users")
        mock_execute.assert_called_once_with("DELETE FROM sqlite_sequence WHERE name = ?", ["users"])

    def test_detect_autoincrement_returns_false_placeholder(self) -> None:
        """阶段 1 SQLiteDialect.detect_autoincrement 返回 False 占位。

        实际检测由 RawSQLiteAdapter/SQLAlchemyAdapter 通过
        schema_helpers.detect_autoincrement 完成。
        """
        dialect = SQLiteDialect()
        assert dialect.detect_autoincrement({}) is False

    def test_create_batch_inserter_not_implemented(self) -> None:
        """阶段 1 不实现 batch_inserter，阶段 2 引入 SQLAlchemyAdapter 后实现。"""
        dialect = SQLiteDialect()
        with pytest.raises(NotImplementedError):
            dialect.create_batch_inserter(None, "users")  # type: ignore[arg-type]

    def test_satisfies_dialect_protocol(self) -> None:
        """SQLiteDialect 满足 Dialect 协议。"""
        dialect = SQLiteDialect()
        assert isinstance(dialect, Dialect)


class TestTypeNormalizer:
    """TypeNormalizer 类型归一化测试。"""

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
        """ENUM 类型参数（非数字）应被忽略。"""
        result = self.normalizer.normalize("enum('a','b','c')", "mysql")
        assert result.base == "TEXT"
        assert result.params == ()


class TestNormalizedType:
    """NormalizedType 数据类测试。"""

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
    """SQLiteBulkOptimizer 测试。

    验证它正确委托给现有的 PragmaOptimizer。
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
        # PragmaOptimizer.preserve 会调用 _fetch_pragma 多次
        assert mock_fetch.call_count > 0

    def test_optimize_light_level(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)  # light level
        # light level 应执行 PRAGMA synchronous = NORMAL 等
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
        # restore 应执行 PRAGMA 恢复
        execute_calls = [call.args[0] for call in mock_execute.call_args_list]
        assert any("PRAGMA synchronous" in call for call in execute_calls)

    def test_restore_without_preserve_is_noop(self) -> None:
        mock_execute = MagicMock()
        mock_fetch = MagicMock(return_value=None)
        optimizer = SQLiteBulkOptimizer(execute_fn=mock_execute, fetch_pragma_fn=mock_fetch)
        optimizer.restore()  # 未调用 preserve，应无操作
        mock_execute.assert_not_called()


class TestSQLiteBulkOptimizerWithRealDb:
    """SQLiteBulkOptimizer 与真实 SQLite 数据库的集成测试。"""

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
        # aggressive 模式应设置 synchronous = OFF
        assert fetch_pragma("synchronous") == 0  # OFF = 0

        optimizer.restore()
        # 恢复后应回到原值
        assert fetch_pragma("synchronous") == original_synchronous

        conn.close()


class TestDialectProtocol:
    """Dialect 协议测试。"""

    def test_sqlite_dialect_is_dialect(self) -> None:
        assert isinstance(SQLiteDialect(), Dialect)

    def test_batch_inserter_protocol(self) -> None:
        """BatchInserter 协议存在且可被 isinstance 检查。"""

        class DummyInserter:
            def insert(self, rows: list[dict[str, Any]]) -> int:
                return len(rows)

        assert isinstance(DummyInserter(), BatchInserter)


# =============================================================================
# 适配器契约测试框架（阶段 2 启用）
# =============================================================================


class DatabaseAdapterContract:
    """所有 DatabaseAdapter 实现必须通过的契约测试。

    阶段 2 引入 SQLAlchemyAdapter 后，子类化此类并提供 fixture 即可自动
    跑同一套接口测试，确保所有适配器行为一致。

    使用方式：
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

    # 阶段 2 后由子类实现
    # @pytest.fixture
    # def adapter(self) -> DatabaseAdapter: ...

    # @pytest.fixture
    # def test_table(self) -> str: ...

    pass
