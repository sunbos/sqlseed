"""AI CLI inputs must reach the real schema, repair and output pipeline."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner

from tests._helpers import clear_llm_env
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("sqlseed_ai")

ai_commands = import_module("sqlseed_ai.cli.ai_commands")


@pytest.fixture(autouse=True)
def offline_client(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")

    class NoNetworkClient:
        def chat_completions_create(self, **_kwargs: object) -> None:
            pytest.fail("deterministic CLI regression unexpectedly requested a model")

        def close(self) -> None:
            pass

    monkeypatch.setattr(ai_commands, "_build_llm_client", lambda config: NoNetworkClient())


@pytest.fixture(name="schema")
def fixture_schema(tmp_path: Path) -> Path:
    path = tmp_path / "input.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE grandparent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE parent(id INTEGER PRIMARY KEY, grandparent_id INTEGER REFERENCES grandparent(id));"
            "CREATE TABLE requested(value INTEGER NOT NULL, label TEXT, parent_id INTEGER REFERENCES parent(id));"
            "CREATE TABLE unrelated(value INTEGER NOT NULL);"
        )
    return path


def test_auto_heal_repairs_supplied_config_and_preserves_unrelated_settings(schema: Path, tmp_path: Path) -> None:
    source, output = tmp_path / "source.yaml", tmp_path / "healed.yaml"
    initial = {
        "provider": "base",
        "locale": "zh_CN",
        "optimize_pragma": False,
        "tables": [
            {
                "name": "requested",
                "count": 7,
                "seed": 19,
                "batch_size": 3,
                "columns": [
                    {"name": "value", "generator": "string"},
                    {"name": "label", "generator": "choice", "params": {"choices": ["keep-rule"]}},
                ],
            }
        ],
    }
    source.write_text(yaml.safe_dump(initial), encoding="utf-8")
    original = source.read_bytes()
    result = CliRunner().invoke(
        ai_commands.auto_heal,
        [
            "--db",
            str(schema),
            "--config",
            str(source),
            "--output",
            str(output),
            "--model",
            "fixed",
        ],
    )
    assert result.exit_code == 0, result.output
    healed = yaml.safe_load(output.read_text())
    assert healed["provider"] == "base"
    assert healed["locale"] == "zh_CN"
    assert healed["optimize_pragma"] is False
    assert [table["name"] for table in healed["tables"]] == ["requested"]
    table = healed["tables"][0]
    assert (table["count"], table["seed"], table["batch_size"]) == (7, 19, 3)
    columns = {column["name"]: column for column in table["columns"]}
    assert columns["value"]["generator"] == "integer"
    assert columns["label"] == initial["tables"][0]["columns"][1]
    assert source.read_bytes() == original


@pytest.mark.parametrize("text", ["not: [valid YAML", "tables: null", "tables:\n- name: missing\n"])
def test_auto_heal_rejects_invalid_input_without_overwriting_output(schema: Path, tmp_path: Path, text: str) -> None:
    source, output = tmp_path / "source.yaml", tmp_path / "existing.yaml"
    source.write_text(text, encoding="utf-8")
    output.write_text("keep original output", encoding="utf-8")
    result = CliRunner().invoke(
        ai_commands.auto_heal,
        [
            "--db",
            str(schema),
            "--config",
            str(source),
            "--output",
            str(output),
            "--model",
            "fixed",
        ],
    )
    assert result.exit_code != 0
    assert output.read_text() == "keep original output"


@pytest.mark.parametrize(
    ("options", "names"),
    [
        ([], {"requested", "parent", "grandparent"}),
        (["--no-dependencies"], {"requested"}),
        (["--max-depth", "0"], {"requested"}),
        (["--max-depth", "1"], {"requested", "parent"}),
    ],
)
def test_ai_analyze_filters_tables_and_dependency_depth(
    schema: Path,
    tmp_path: Path,
    options: list[str],
    names: set[str],
) -> None:
    output = tmp_path / "selected.yaml"
    result = CliRunner().invoke(
        ai_commands.ai_analyze,
        [
            "--db",
            str(schema),
            "--tables",
            "requested",
            "--output",
            str(output),
            "--model",
            "fixed",
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    assert {table["name"] for table in yaml.safe_load(output.read_text())["tables"]} == names


def test_ai_analyze_merge_keeps_existing_root_and_unselected_table_rules(schema: Path, tmp_path: Path) -> None:
    output = tmp_path / "merged.yaml"
    keep = {
        "name": "unrelated",
        "count": 41,
        "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 8, "max_value": 8}}],
    }
    original = {"provider": "base", "locale": "zh_CN", "tables": [keep, {"name": "requested", "count": 9}]}
    output.write_text(yaml.safe_dump(original), encoding="utf-8")
    result = CliRunner().invoke(
        ai_commands.ai_analyze,
        [
            "--db",
            str(schema),
            "--tables",
            "requested",
            "--no-dependencies",
            "--merge",
            "--output",
            str(output),
            "--model",
            "fixed",
        ],
    )
    assert result.exit_code == 0, result.output
    merged = yaml.safe_load(output.read_text())
    assert merged["provider"] == "base"
    assert merged["locale"] == "zh_CN"
    assert {table["name"] for table in merged["tables"]} == {"requested", "unrelated"}
    assert next(table for table in merged["tables"] if table["name"] == "unrelated") == keep


def test_ai_analyze_unknown_table_does_not_replace_output(schema: Path, tmp_path: Path) -> None:
    output = tmp_path / "existing.yaml"
    output.write_text("keep original output", encoding="utf-8")
    result = CliRunner().invoke(
        ai_commands.ai_analyze,
        [
            "--db",
            str(schema),
            "--tables",
            "missing",
            "--output",
            str(output),
            "--model",
            "fixed",
        ],
    )
    assert result.exit_code != 0
    assert output.read_text() == "keep original output"


def test_ai_analyze_merge_requires_an_output_file(schema: Path) -> None:
    result = CliRunner().invoke(ai_commands.ai_analyze, ["--db", str(schema), "--merge", "--model", "fixed"])
    assert result.exit_code == 2
    assert "--output" in result.output


def test_auto_heal_preserves_explicit_native_derived_and_constraint_rules(tmp_path: Path) -> None:
    from sqlseed import fill_from_config

    path = tmp_path / "explicit.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE entries(value INTEGER, doubled INTEGER, token_uuid TEXT, native_text TEXT)")
    columns = [
        {"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}},
        {"name": "doubled", "derive_from": "value", "expression": "value * 2"},
        {
            "name": "token_uuid",
            "generator": "choice",
            "params": {"choices": ["explicit-rule"]},
            "constraints": {"max_retries": 9},
        },
        {"name": "native_text", "generator": "string", "faker_method": "lexify", "native_params": {"text": "??"}},
    ]
    source, output = tmp_path / "explicit.yaml", tmp_path / "healed.yaml"
    source.write_text(
        yaml.safe_dump({"provider": "faker", "tables": [{"name": "entries", "count": 2, "columns": columns}]})
    )
    result = CliRunner().invoke(
        ai_commands.auto_heal, ["--db", str(path), "--config", str(source), "-o", str(output), "--model", "fixed"]
    )
    assert result.exit_code == 0, result.output
    healed = yaml.safe_load(output.read_text())
    assert healed["tables"][0]["columns"] == columns
    outcome = fill_from_config(output)
    assert len(outcome) == 1
    assert outcome[0].errors == []
    assert outcome[0].count == 2
    with sqlite_connection(path) as db:
        rows = db.execute("SELECT value, doubled, token_uuid, native_text FROM entries").fetchall()
    assert all(row[:3] == (7, 14, "explicit-rule") and len(row[3]) == 2 for row in rows)
