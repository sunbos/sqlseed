from __future__ import annotations

import sqlite3
from typing import Any

import pytest
import yaml

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult
from tests._helpers import fill_from_config_and_verify_fk
from tests.sqlite_helpers import sqlite_connection


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

    @pytest.mark.parametrize("provider", ["base", "faker"])
    def test_fill_options_preserve_keyword_results(self, tmp_path, provider: str) -> None:
        paths = [tmp_path / "keywords.db", tmp_path / "options.db"]
        for path in paths:
            with sqlite_connection(path) as connection:
                connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        settings = sqlseed.FillOptions(provider=provider, seed=42, batch_size=2, optimize_pragma=False)

        keyword_result = sqlseed.fill(
            str(paths[0]), table="users", count=5, provider=provider, seed=42, batch_size=2, optimize_pragma=False
        )
        options_result = sqlseed.fill(str(paths[1]), table="users", count=5, options=settings)

        assert not keyword_result.errors
        assert not options_result.errors
        assert keyword_result.count == options_result.count == 5
        with sqlite_connection(paths[0]) as first, sqlite_connection(paths[1]) as second:
            assert (
                first.execute("SELECT * FROM users ORDER BY id").fetchall()
                == second.execute("SELECT * FROM users ORDER BY id").fetchall()
            )

    def test_fill_options_explicit_overrides_preserve_shared_settings(self, tmp_path) -> None:
        path = tmp_path / "overrides.db"
        with sqlite_connection(path) as connection:
            connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
        transform = tmp_path / "transform.py"
        transform.write_text(
            "def transform_row(row, ctx):\n    row['name'] += '-transformed'\n    return row\n", encoding="utf-8"
        )
        settings = sqlseed.FillOptions(
            provider="base",
            columns={"name": {"type": "choice", "choices": ["shared"]}},
            seed=42,
            clear_before=True,
            transform=str(transform),
        )
        first = sqlseed.fill(str(path), table="users", count=2, options=settings)
        second = sqlseed.fill(
            str(path),
            table="users",
            count=1,
            options=settings,
            clear_before=False,
            columns=None,
            seed=None,
            transform=None,
        )

        assert not first.errors
        assert not second.errors
        with sqlite_connection(path) as connection:
            names = [row[0] for row in connection.execute("SELECT name FROM users ORDER BY id")]
        assert names[:2] == ["shared-transformed", "shared-transformed"]
        assert len(names) == 3
        assert names[-1] != "shared-transformed"
        assert settings.clear_before is True
        assert settings.seed == 42
        assert settings.columns == {"name": {"type": "choice", "choices": ["shared"]}}
        assert settings.transform == str(transform)

    def test_fill_rejects_unknown_keyword_before_opening_database(self, tmp_path) -> None:
        path = tmp_path / "must-not-create.db"
        unsupported: dict[str, Any] = {"snapshot": True}
        with pytest.raises(TypeError, match="snapshot"):
            sqlseed.fill(str(path), table="users", **unsupported)
        assert not path.exists()

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

    def test_fill_from_config(self, tmp_db, tmp_path: Any) -> None:
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

    def test_fill_from_config_respects_fk_order(self, tmp_path: Any) -> None:
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
        results = fill_from_config_and_verify_fk(
            db_path,
            config_data,
            str(tmp_path),
            "SELECT dept_id FROM employees",
            "SELECT id FROM departments",
        )
        assert len(results) == 2

    def test_preview_with_seed(self, tmp_db) -> None:
        rows1 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        rows2 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        assert rows1 == rows2
