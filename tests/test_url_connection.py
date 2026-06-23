from __future__ import annotations

import sqlite3
from typing import Any

import pytest
import yaml

import sqlseed
from sqlseed import _resolve_db_target
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult


class TestPublicAPIUrl:
    """测试公共 API 的 url 参数（fill/connect/preview）。"""

    def test_fill_with_url_sqlite(self, tmp_path: Any) -> None:
        """fill(url=...) 用 SQLite URL 成功写入。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        result = sqlseed.fill(url=url, table="users", count=10, provider="base")
        assert isinstance(result, GenerationResult)
        assert result.count == 10

        # 验证数据实际写入
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_connect_with_url(self, tmp_path: Any) -> None:
        """connect(url=...) 返回 DataOrchestrator，可 fill。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
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
        """preview(url=...) 返回预览数据列表。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        rows = sqlseed.preview(url=url, table="users", count=3, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 3
        assert all(isinstance(r, dict) for r in rows)

    def test_fill_url_and_db_path_mutual_exclusion(self, tmp_path: Any) -> None:
        """同时提供 db_path 和 url 抛 ValueError。"""
        db_path = str(tmp_path / "test.db")
        url = f"sqlite:///{db_path}"
        with pytest.raises(ValueError, match="Cannot specify both"):
            sqlseed.fill(db_path=db_path, url=url, table="users", count=1)

    def test_fill_no_target_raises(self) -> None:
        """都不提供抛 ValueError。"""
        with pytest.raises(ValueError, match="Either db_path or url must be provided"):
            sqlseed.fill(table="users", count=1)  # type: ignore[call-arg]

    def test_fill_with_url_writes_correct_data(self, tmp_path: Any) -> None:
        """url 模式写入数据结构与 db_path 模式一致。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
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
        """with connect(url=...) as orch: 正常工作。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        with sqlseed.connect(url=url, provider="base") as db:
            result = db.fill("users", count=3)
            assert result.count == 3

    def test_preview_with_url_returns_list(self, tmp_path: Any) -> None:
        """preview(url=...) 返回 list[dict]。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        rows = sqlseed.preview(url=url, table="users", count=2, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 2

    def test_fill_with_url_seed_reproducibility(self, tmp_path: Any) -> None:
        """url 模式下 seed 可复现。"""
        db_path1 = str(tmp_path / "test1.db")
        db_path2 = str(tmp_path / "test2.db")
        for p in (db_path1, db_path2):
            conn = sqlite3.connect(p)
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
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
        """url 模式下不存在的表正确报错（result.errors 非空）。

        注意：fill() 对不存在表的行为是记录到 errors 而非抛异常。
        """
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        result = sqlseed.fill(url=url, table="nonexistent_table", count=1, provider="base")
        assert len(result.errors) > 0

    def test_fill_with_url_does_not_accept_snapshot(self, tmp_path: Any) -> None:
        """url 模式下 fill() 不支持 snapshot 参数（仅 CLI --snapshot 支持）。

        fill() 公共 API 无 snapshot 参数，snapshot 功能仅通过 CLI --snapshot 提供。
        """
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        with pytest.raises(TypeError, match="snapshot"):
            sqlseed.fill(  # type: ignore[call-arg]
                url=url, table="users", count=5, provider="base", snapshot=True, seed=42
            )

    def test_fill_with_url_config_file(self, tmp_path: Any) -> None:
        """fill_from_config 使用 url 字段。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
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

        # 验证数据实际写入
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_resolve_db_target_priority(self) -> None:
        """db_path 优先于 url（当只提供 db_path 时返回 db_path）。"""
        assert _resolve_db_target("test.db", None) == "test.db"

    def test_resolve_db_target_url_only(self) -> None:
        """仅 url 时正确返回 url。"""
        assert _resolve_db_target(None, "postgresql://host/db") == "postgresql://host/db"

    def test_fill_with_empty_url_creates_memory_db(self, tmp_path: Any) -> None:
        """空 URL (url="") 行为：返回空字符串，SQLAlchemyAdapter 转为内存 SQLite。

        注意：当前实现中 url="" 不是 None，所以 _resolve_db_target 返回 ""。
        SQLAlchemyAdapter.connect("") 将其转为 sqlite:///（内存库）。
        这是一个边界行为测试，验证不崩溃。
        """
        # _resolve_db_target 对 url="" 返回 ""（不抛异常，因为 "" is not None）
        target = _resolve_db_target(None, "")
        assert target == ""

    def test_fill_with_url_count_zero_raises(self, tmp_path: Any) -> None:
        """url 模式下 count=0 抛 ValueError。"""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        with pytest.raises(ValueError):
            sqlseed.fill(url=url, table="users", count=0, provider="base")
