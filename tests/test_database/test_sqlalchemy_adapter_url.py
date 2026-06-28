from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import ArgumentError, NoSuchModuleError

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


class TestSQLAlchemyAdapterUrl:
    """测试 SQLAlchemyAdapter 的 URL 连接功能。"""

    def test_connect_sqlite_file_url(self, tmp_path: Any) -> None:
        """connect("sqlite:///path.db") 成功。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_sqlite_memory_url(self) -> None:
        """connect("sqlite://") 内存库成功。"""
        adapter = SQLAlchemyAdapter()
        adapter.connect("sqlite://")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_postgresql_missing_driver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """psycopg 未装时抛 RuntimeError 含 "pip install sqlseed[postgres]"。

        通过 mock create_engine 抛出 NoSuchModuleError 模拟驱动缺失。
        """

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:postgresql.psycopg")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(RuntimeError, match="PostgreSQL driver not installed"):
            adapter.connect("postgresql://user:pass@host/db")

    def test_connect_invalid_url_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无效 URL（触发 ArgumentError）抛 ValueError。

        注意："not_a_url" 不含 "://"，会被 SQLAlchemyAdapter 自动转为 sqlite:/// URL。
        要触发 ValueError，需要用含 "://" 但格式无效的 URL，使 create_engine 抛 ArgumentError。
        我们用 mock 模拟 ArgumentError。
        """

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise ArgumentError("Invalid URL format")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Invalid database URL"):
            adapter.connect("postgresql://invalid url with spaces")

    def test_connect_unsupported_dialect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """connect("oracle://...") 抛 ValueError（_detect_dialect 不支持 oracle）。"""
        mock_engine = MagicMock()
        mock_engine.dialect.name = "oracle"
        monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: mock_engine)
        monkeypatch.setattr("sqlalchemy.inspect", lambda e: MagicMock())

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Unsupported dialect"):
            adapter.connect("oracle://user:pass@host/db")

    def test_connect_url_sets_dialect_correctly_sqlite(self, tmp_path: Any) -> None:
        """连接后 dialect.name == "sqlite"。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        assert adapter.dialect.name == "sqlite"
        adapter.close()

    def test_connect_url_persists_engine(self, tmp_path: Any) -> None:
        """连接后 engine 可重复使用。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

        adapter = SQLAlchemyAdapter()
        adapter.connect(f"sqlite:///{db_path}")
        # 多次操作验证 engine 持久
        assert adapter.get_table_names() == ["t"]
        assert adapter.get_table_names() == ["t"]
        adapter.close()

    def test_connect_url_close_releases_resources(self, tmp_path: Any) -> None:
        """close 后 engine 释放，再操作抛 RuntimeError。"""
        db_path = str(tmp_path / "test.db")
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
        """真实 PG 容器连接成功（依赖 pg_url fixture）。"""
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.dialect.name == "postgresql"
        adapter.close()

    def test_connect_url_sets_dialect_correctly_postgresql(self, pg_url: str) -> None:
        """连接真实 PG 后 dialect.name == "postgresql"。"""
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.dialect.name == "postgresql"
        adapter.close()

    def test_connect_malformed_url_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """connect("postgresql://") 抛 ValueError（触发 ArgumentError）。

        注意：psycopg 安装后 create_engine("postgresql://") 行为不确定。
        用 mock 模拟 ArgumentError 确保测试稳定。
        """

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise ArgumentError("Could not parse SQLAlchemy URL")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        adapter = SQLAlchemyAdapter()
        with pytest.raises(ValueError, match="Invalid database URL"):
            adapter.connect("postgresql://")
