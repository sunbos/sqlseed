"""Config-driven CLI execution must make the target and partial failures explicit."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner
from sqlseed_cli.main import cli

import sqlseed

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("target_kind", ["path", "url"])
def test_config_rejects_explicit_target_without_changing_either_database(tmp_path: Path, target_kind: str) -> None:
    configured_db = tmp_path / "configured.db"
    explicit_db = tmp_path / "explicit.db"
    for db_path in (configured_db, explicit_db):
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute("CREATE TABLE items (value INTEGER)")
            conn.execute("INSERT INTO items VALUES (99)")
    config_path = tmp_path / "generate.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "db_path": str(configured_db),
                "provider": "base",
                "tables": [{"name": "items", "count": 2, "clear_before": True}],
            }
        ),
        encoding="utf-8",
    )
    target_args = [str(explicit_db)] if target_kind == "path" else ["--url", f"sqlite:///{explicit_db}"]

    result = CliRunner().invoke(
        cli, ["fill", *target_args, "--config", str(config_path), "--provider", "base", "--no-ai"]
    )

    assert result.exit_code == 2, result.output
    assert "--config" in result.output
    assert "db_path" in result.output
    assert "--url" in result.output
    for db_path in (configured_db, explicit_db):
        with closing(sqlite3.connect(db_path)) as conn, conn:
            assert conn.execute("SELECT value FROM items").fetchall() == [(99,)]


@pytest.mark.parametrize("failed_first", [False, True])
def test_config_partial_failure_reports_committed_rows_and_nonzero_exit(tmp_path: Path, failed_first: bool) -> None:
    db_path = tmp_path / "partial.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE good (value INTEGER)")
        conn.execute("CREATE TABLE bad (value INTEGER)")
        conn.execute("INSERT INTO bad VALUES (99)")
    transform_path = tmp_path / "fail_third.py"
    transform_path.write_text(
        "calls = 0\n"
        "def transform_row(row, ctx):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 3:\n"
        "        raise ValueError('third row failed')\n"
        "    return row\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "generate.yaml"
    columns = [{"name": "value", "generator": "integer", "params": {"min_value": 11, "max_value": 11}}]
    tables = [
        {"name": "good", "count": 2, "columns": columns},
        {"name": "bad", "count": 3, "columns": columns, "transform": str(transform_path)},
    ]
    if failed_first:
        tables.reverse()
    config_path.write_text(
        yaml.safe_dump(
            {
                "db_path": str(db_path),
                "provider": "base",
                "tables": tables,
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli, ["fill", "--config", str(config_path), "--provider", "base", "--batch-size", "1", "--no-ai"]
    )

    assert result.exit_code == 1, result.output
    assert "table=good, count=2," in result.output
    assert "table=bad, count=2," in result.output
    assert "Error: third row failed" in result.stderr
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT value FROM good").fetchall() == [(11,), (11,)]
        assert conn.execute("SELECT value FROM bad ORDER BY value").fetchall() == [(11,), (11,), (99,)]


@pytest.mark.parametrize("explicit_override", [False, True])
@pytest.mark.parametrize("option", ["provider", "locale"])
def test_config_generation_matches_api_option_priority(tmp_path: Path, option: str, explicit_override: bool) -> None:
    db_path = tmp_path / "people.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE people (name TEXT)")
    config_path = tmp_path / "generate.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "db_path": str(db_path),
                "provider": "faker",
                "locale": "zh_CN" if option == "locale" else "en_US",
                "tables": [
                    {
                        "name": "people",
                        "count": 5,
                        "seed": 42,
                        "clear_before": True,
                        "columns": [{"name": "name", "generator": "name"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # Explicit values deliberately equal Click's defaults: equality with a
    # default cannot distinguish a supplied option from an omitted one.
    override = ("mimesis" if option == "provider" else "en_US") if explicit_override else None
    expected = sqlseed.fill_from_config(
        config_path,
        skip_ai=True,
        provider=override if option == "provider" else None,
        locale=override if option == "locale" else None,
    )
    assert expected[0].count == 5
    assert expected[0].errors == []
    with closing(sqlite3.connect(db_path)) as conn, conn:
        expected_rows = conn.execute("SELECT name FROM people ORDER BY rowid").fetchall()
    args = ["fill", "--config", str(config_path), "--no-ai"]
    if option == "locale":
        args += ["--provider", "faker"]
    if override is not None:
        args += [f"--{option}", override]

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT name FROM people ORDER BY rowid").fetchall() == expected_rows


@pytest.mark.parametrize("explicit_override, expected_count", [(False, 2), (True, 0)])
def test_config_batch_size_controls_real_partial_commits(
    tmp_path: Path, explicit_override: bool, expected_count: int
) -> None:
    db_path = tmp_path / "batches.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE items (value INTEGER)")
    transform_path = tmp_path / "fail_third.py"
    transform_path.write_text(
        "calls = 0\n"
        "def transform_row(row, ctx):\n"
        "    global calls\n"
        "    calls += 1\n"
        "    if calls == 3:\n"
        "        raise ValueError('third row failed')\n"
        "    return row\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "generate.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "db_path": str(db_path),
                "provider": "base",
                "tables": [{"name": "items", "count": 3, "batch_size": 1, "transform": str(transform_path)}],
            }
        ),
        encoding="utf-8",
    )
    args = ["fill", "--config", str(config_path), "--no-ai"]
    if explicit_override:
        args += ["--batch-size", "5000"]

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 1, result.output
    assert f"table=items, count={expected_count}," in result.output
    assert "Error: third row failed" in result.stderr
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == expected_count


def test_direct_fill_keeps_default_provider_and_locale(tmp_path: Path) -> None:
    db_path = tmp_path / "direct.db"
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("CREATE TABLE people (name TEXT)")
    expected = sqlseed.fill(
        str(db_path), table="people", count=5, seed=42, provider="mimesis", locale="en_US", skip_ai=True
    )
    assert expected.count == 5
    assert expected.errors == []
    with closing(sqlite3.connect(db_path)) as conn, conn:
        expected_rows = conn.execute("SELECT name FROM people ORDER BY rowid").fetchall()

    result = CliRunner().invoke(
        cli, ["fill", str(db_path), "--table", "people", "--count", "5", "--seed", "42", "--clear", "--no-ai"]
    )

    assert result.exit_code == 0, result.output
    with closing(sqlite3.connect(db_path)) as conn, conn:
        assert conn.execute("SELECT name FROM people ORDER BY rowid").fetchall() == expected_rows
