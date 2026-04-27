from __future__ import annotations

import sqlite3
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

import sqlseed
from sqlseed.cli.main import cli


def _make_db(
    tmp_path,
    table_ddl=("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, age INTEGER, email TEXT)"),
) -> str:
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(table_ddl)
    conn.commit()
    conn.close()
    return db_path


def _make_config(tmp_path: Any, db_path: str, **overrides) -> str:
    config_data = {
        "db_path": db_path,
        "provider": "base",
        "locale": "en_US",
        "tables": [{"name": "users", "count": 100, "columns": []}],
    }
    config_data.update(overrides)
    config_path = str(tmp_path / "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)
    return config_path


def _count_rows(db_path: str, table: str = "users") -> int:
    conn = sqlite3.connect(db_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return int(count)


def _min_max_id(db_path: str, table: str = "users") -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    row = conn.execute(f"SELECT MIN(id), MAX(id) FROM {table}").fetchone()
    conn.close()
    return row[0], row[1]


def _min_max_age(db_path: str) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT MIN(age), MAX(age) FROM users").fetchone()
    conn.close()
    return row[0], row[1]


class TestCLIOverridesYAMLCount:
    def test_yaml_count_no_cli_override(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        results = sqlseed.fill_from_config(config_path, skip_ai=True)
        assert results[0].count == 100
        assert _count_rows(db_path) == 100

    def test_cli_count_overrides_yaml(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        results = sqlseed.fill_from_config(config_path, skip_ai=True, count=5)
        assert results[0].count == 5
        assert _count_rows(db_path) == 5

    def test_cli_count_overrides_yaml_large(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[{"name": "users", "count": 5, "columns": []}],
        )
        results = sqlseed.fill_from_config(config_path, skip_ai=True, count=50)
        assert results[0].count == 50
        assert _count_rows(db_path) == 50


class TestCLIOverridesYAMLClearBefore:
    def test_no_clear_appends_data(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        assert _count_rows(db_path) == 20

    def test_clear_before_resets_data(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10, clear_before=True)
        assert _count_rows(db_path) == 10

    def test_clear_before_resets_autoincrement_id(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        _, max_id_1 = _min_max_id(db_path)
        assert max_id_1 == 10

        sqlseed.fill_from_config(config_path, skip_ai=True, count=5, clear_before=True)
        min_id, max_id_2 = _min_max_id(db_path)
        assert min_id == 1
        assert max_id_2 == 5

    def test_yaml_clear_before_true_no_cli(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[{"name": "users", "count": 10, "clear_before": True, "columns": []}],
        )
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=5)
        assert _count_rows(db_path) == 5

    def test_yaml_clear_false_cli_clear_true(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=5, clear_before=True)
        assert _count_rows(db_path) == 5
        min_id, _ = _min_max_id(db_path)
        assert min_id == 1

    def test_no_clear_id_continues(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=10)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=5)
        min_id, max_id = _min_max_id(db_path)
        assert min_id == 1
        assert max_id == 15


class TestCLIOverridesYAMLSeed:
    def test_cli_seed_overrides_yaml(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[{"name": "users", "count": 10, "seed": 1, "columns": []}],
        )
        results_a = sqlseed.fill_from_config(
            config_path,
            skip_ai=True,
            seed=42,
            clear_before=True,
        )
        results_b = sqlseed.fill_from_config(
            config_path,
            skip_ai=True,
            seed=42,
            clear_before=True,
        )
        assert results_a[0].count == results_b[0].count

    def test_different_seeds_different_data(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, seed=1, clear_before=True)
        conn = sqlite3.connect(db_path)
        data_a = conn.execute("SELECT username FROM users ORDER BY id").fetchall()
        conn.close()

        sqlseed.fill_from_config(config_path, skip_ai=True, seed=999, clear_before=True)
        conn = sqlite3.connect(db_path)
        data_b = conn.execute("SELECT username FROM users ORDER BY id").fetchall()
        conn.close()

        assert data_a != data_b


class TestCLIOverridesYAMLBatchSize:
    def test_cli_batch_size_overrides_yaml(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[{"name": "users", "count": 100, "batch_size": 5000, "columns": []}],
        )
        results = sqlseed.fill_from_config(config_path, skip_ai=True, batch_size=50)
        assert results[0].count == 100
        assert _count_rows(db_path) == 100


class TestCLIOverridesYAMLProvider:
    def test_cli_provider_overrides_yaml(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path, provider="base")
        results = sqlseed.fill_from_config(
            config_path,
            skip_ai=True,
            provider="mimesis",
        )
        assert results[0].count == 100
        assert _count_rows(db_path) == 100


class TestCLIOverridesYAMLLocale:
    def test_cli_locale_overrides_yaml(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path, locale="en_US")
        results = sqlseed.fill_from_config(config_path, skip_ai=True, locale="en_US")
        assert results[0].count == 100


class TestAgeNoHardConstraint:
    @pytest.mark.parametrize("max_value,expected_above_65", [(100, True), (65, False)])
    def test_age_respects_yaml_max(self, tmp_path: Any, max_value: int, expected_above_65: bool) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[
                {
                    "name": "users",
                    "count": 500,
                    "columns": [
                        {
                            "name": "age",
                            "generator": "integer",
                            "params": {"min_value": 18, "max_value": max_value},
                        },
                    ],
                }
            ],
        )
        sqlseed.fill_from_config(config_path, skip_ai=True, clear_before=True)
        _, max_age = _min_max_age(db_path)
        if expected_above_65:
            assert max_age > 65
        else:
            assert max_age <= 65


class TestCLIConfigPriorityIntegration:
    def test_count_and_clear_combined(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        sqlseed.fill_from_config(config_path, skip_ai=True, count=50)
        assert _count_rows(db_path) == 50

        sqlseed.fill_from_config(config_path, skip_ai=True, count=5, clear_before=True)
        assert _count_rows(db_path) == 5
        min_id, _ = _min_max_id(db_path)
        assert min_id == 1

    def test_all_overrides_combined(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[
                {
                    "name": "users",
                    "count": 100,
                    "seed": 1,
                    "batch_size": 5000,
                    "columns": [],
                }
            ],
        )
        results = sqlseed.fill_from_config(
            config_path,
            skip_ai=True,
            count=10,
            seed=42,
            batch_size=50,
            clear_before=True,
        )
        assert results[0].count == 10
        assert _count_rows(db_path) == 10

    def test_cli_fill_config_with_count_override(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--config", config_path, "--count", "5", "--no-ai"],
        )
        assert result.exit_code == 0
        assert _count_rows(db_path) == 5

    def test_cli_fill_config_with_clear(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        runner = CliRunner()
        runner.invoke(cli, ["fill", "--config", config_path, "--no-ai"])
        runner.invoke(cli, ["fill", "--config", config_path, "--clear", "--no-ai"])
        min_id, _ = _min_max_id(db_path)
        assert min_id == 1

    def test_cli_fill_config_note_when_no_clear(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--config", config_path, "--no-ai"],
        )
        assert "Data will be appended" in result.output

    def test_cli_fill_config_no_note_when_clear(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(tmp_path, db_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--config", config_path, "--clear", "--no-ai"],
        )
        assert "Data will be appended" not in result.output

    def test_cli_fill_config_no_note_when_yaml_clear(self, tmp_path: Any) -> None:
        db_path = _make_db(tmp_path)
        config_path = _make_config(
            tmp_path,
            db_path,
            tables=[{"name": "users", "count": 10, "clear_before": True, "columns": []}],
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--config", config_path, "--no-ai"],
        )
        assert "Data will be appended" not in result.output
