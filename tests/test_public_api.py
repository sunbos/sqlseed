from __future__ import annotations

import sqlite3

import yaml

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult
from tests._helpers import assert_fk_integrity


class TestPublicAPI:
    def test_fill(self, tmp_db) -> None:
        result = sqlseed.fill(tmp_db, table="users", count=50, provider="base")
        assert isinstance(result, GenerationResult)
        assert result.count == 50

    def test_fill_with_clear(self, tmp_db) -> None:
        sqlseed.fill(tmp_db, table="users", count=10, provider="base")
        result = sqlseed.fill(tmp_db, table="users", count=20, provider="base", clear_before=True)
        assert result.count == 20

    def test_fill_with_columns(self, tmp_db) -> None:
        result = sqlseed.fill(
            tmp_db,
            table="users",
            count=10,
            columns={"name": "name", "email": "email"},
            provider="base",
        )
        assert result.count == 10

    def test_fill_with_seed(self, tmp_db) -> None:
        result = sqlseed.fill(tmp_db, table="users", count=5, provider="base", seed=42)
        assert result.count == 5

    def test_connect(self, tmp_db) -> None:
        db = sqlseed.connect(tmp_db, provider="base")
        assert isinstance(db, DataOrchestrator)
        db._ensure_connected()
        db.close()

    def test_connect_exposes_fill_alias(self, tmp_db) -> None:
        with sqlseed.connect(tmp_db, provider="base") as db:
            result = db.fill("users", count=7, seed=42)

        assert isinstance(result, GenerationResult)
        assert result.count == 7

    def test_fill_from_config(self, tmp_db, tmp_path) -> None:
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "db_path": tmp_db,
            "provider": "base",
            "locale": "en_US",
            "tables": [
                {
                    "name": "users",
                    "count": 15,
                    "columns": [
                        {"name": "name", "generator": "name"},
                    ],
                }
            ],
        }
        config_path.write_text(yaml.dump(config_data))
        results = sqlseed.fill_from_config(str(config_path))
        assert len(results) == 1
        assert results[0].count == 15

    def test_preview(self, tmp_db) -> None:
        rows = sqlseed.preview(tmp_db, table="users", count=3, provider="base")
        assert len(rows) == 3
        assert "name" in rows[0]

    def test_fill_from_config_respects_fk_order(self, tmp_path) -> None:
        db_path = str(tmp_path / "fk_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER REFERENCES departments(id))"
        )
        conn.close()

        config_data = {
            "db_path": db_path,
            "provider": "base",
            "tables": [
                {
                    "name": "employees",
                    "count": 5,
                    "columns": [
                        {"name": "name", "generator": "string"},
                        {
                            "name": "dept_id",
                            "generator": "foreign_key",
                            "params": {"ref_table": "departments", "ref_column": "id"},
                        },
                    ],
                },
                {
                    "name": "departments",
                    "count": 3,
                    "columns": [
                        {"name": "name", "generator": "string"},
                    ],
                },
            ],
        }
        config_path = str(tmp_path / "config.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        results = sqlseed.fill_from_config(config_path)
        assert len(results) == 2

        assert_fk_integrity(
            db_path,
            "SELECT dept_id FROM employees",
            "SELECT id FROM departments",
        )

    def test_preview_with_seed(self, tmp_db) -> None:
        rows1 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        rows2 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        assert rows1 == rows2
