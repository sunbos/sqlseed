"""Real HTTP suggestions must preserve the selected SQLite target in exported YAML."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

from sqlseed import fill_from_config
from sqlseed._utils.sql_safe import quote_identifier
from tests._helpers import clear_llm_env
from tests.sqlite_helpers import sqlite_connection

try:
    from sqlseed_ai.cli.ai_commands import ai_suggest
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai is not installed", allow_module_level=True)

from .test_refiner_json_recovery import _completion_server

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner


@pytest.fixture(name="cli_runner")
def fixture_cli_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """Create a fresh command runner with an isolated OpenAI-compatible backend."""
    from click.testing import CliRunner

    clear_llm_env(monkeypatch)
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "openai_compat")
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "test-key")
    return CliRunner()


def _arguments(database: Path, output: Path, base_url: str, table: str, options: list[str]) -> list[str]:
    return [
        str(database),
        "--table",
        table,
        "--output",
        str(output),
        "--base-url",
        base_url,
        "--model",
        "refiner-format-test",
        "--timeout",
        "5",
        "--no-cache",
        *options,
    ]


@pytest.mark.parametrize("options", [["--no-verify"], ["--max-retries", "0"], ["--max-retries", "1"]])
@pytest.mark.parametrize("prefix", [".", ":"])
def test_export_keeps_real_table_and_column_identifiers(
    tmp_path: Path, prefix: str, options: list[str], cli_runner: CliRunner
) -> None:
    database, output = tmp_path / "names.db", tmp_path / "output.yaml"
    table, column = prefix + "events", prefix + "value"
    with sqlite_connection(database) as db:
        db.execute(
            f"CREATE TABLE {quote_identifier(table)}"
            f"({quote_identifier(column)} INTEGER NOT NULL CHECK ({quote_identifier(column)}=7))"
        )
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("INSERT INTO events VALUES (19)")
    before = database.read_bytes()
    candidate = {
        "name": table,
        "provider": "base",
        "locale": "en_US",
        "count": 2,
        "columns": [{"name": column, "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
    }
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(candidate), "stop")], requests) as base_url:
        result = cli_runner.invoke(ai_suggest, _arguments(database, output, base_url, table, options))
    assert result.exit_code == 0, result.output
    exported = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert exported["tables"][0]["name"] == table
    assert exported["tables"][0]["columns"][0]["name"] == column
    assert database.read_bytes() == before
    filled = fill_from_config(output)
    assert filled[0].count == 2 and not filled[0].errors
    with sqlite_connection(database) as db:
        assert db.execute(f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)}").fetchall() == [
            (7,),
            (7,),
        ]
        assert db.execute("SELECT value FROM events").fetchall() == [(19,)]


@pytest.mark.parametrize("options", [["--no-verify"], ["--max-retries", "0"], ["--max-retries", "1"]])
def test_other_target_is_rejected_without_overwriting_existing_output(
    tmp_path: Path, options: list[str], cli_runner: CliRunner
) -> None:
    database, output = tmp_path / "targets.db", tmp_path / "output.yaml"
    with sqlite_connection(database) as db:
        db.execute('CREATE TABLE ".events"(value INTEGER)')
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("INSERT INTO events VALUES (19)")
    before = database.read_bytes()
    output.write_text("user-owned output", encoding="utf-8")
    candidate = {"name": "events", "columns": [{"name": "value", "generator": "integer"}]}
    requests: list[dict[str, object]] = []
    with _completion_server([(json.dumps(candidate), "stop")], requests) as base_url:
        result = cli_runner.invoke(ai_suggest, _arguments(database, output, base_url, ".events", options))
    assert result.exit_code == 1, result.output
    assert "table" in result.output.lower() and ".events" in result.output
    assert output.read_text(encoding="utf-8") == "user-owned output"
    assert database.read_bytes() == before


@pytest.mark.parametrize("options", [["--no-verify"], ["--max-retries", "0"], ["--max-retries", "1"]])
def test_missing_cli_target_fails_before_model_request(
    tmp_path: Path, options: list[str], cli_runner: CliRunner
) -> None:
    database, output = tmp_path / "missing.db", tmp_path / "output.yaml"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE existing(value INTEGER)")
    before = database.read_bytes()
    requests: list[dict[str, object]] = []
    with _completion_server([('{"name":"missing", "columns":[]}', "stop")], requests) as base_url:
        result = cli_runner.invoke(ai_suggest, _arguments(database, output, base_url, "missing", options))
    assert result.exit_code == 1, result.output
    assert "missing" in result.output and "does not exist" in result.output
    assert not requests
    assert not output.exists()
    assert database.read_bytes() == before
