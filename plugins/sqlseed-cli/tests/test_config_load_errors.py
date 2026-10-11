"""Users can diagnose and correct configuration errors without changing data."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner
from sqlseed_cli.main import cli

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("missing.yaml", None),
        ("broken.yaml", b"tables: [\n"),
        ("broken.json", b'{"tables": ['),
        ("invalid.yaml", b"db_path: demo.db\ntables: wrong-type\n"),
        ("numeric-key.yaml", b"1: value\n"),
        ("encoding.yaml", b"db_path: \xff\n"),
        ("tag.yaml", b"db_path: !unsupported {}\n"),
        ("empty.yaml", b""),
    ],
)
def test_config_load_error_preserves_rows_and_allows_retry(
    tmp_path: Path, filename: str, contents: bytes | None
) -> None:
    database = tmp_path / "demo.db"
    with sqlite_connection(database) as connection:
        connection.execute("CREATE TABLE items (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO items VALUES (99)")
    config = tmp_path / filename
    if contents is not None:
        config.write_bytes(contents)
    runner = CliRunner()
    args = ["fill", "--config", str(config), "--clear", "--no-ai"]

    failed = runner.invoke(cli, args)

    assert failed.exit_code == 2, repr(failed.exception)
    assert "Configuration fill failed:" in failed.output
    assert "Traceback" not in failed.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(99,)]

    # Correct the file and retry through the same CLI, with real SQLite writes.
    document = {
        "db_path": str(database),
        "provider": "base",
        "tables": [
            {
                "name": "items",
                "count": 2,
                "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
            }
        ],
    }
    if config.suffix == ".json":
        config.write_text(json.dumps(document), encoding="utf-8")
    else:
        config.write_text(yaml.safe_dump(document), encoding="utf-8")
    recovered = runner.invoke(cli, args)

    assert recovered.exit_code == 0, recovered.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]


def test_config_directory_reports_actionable_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["fill", "--config", str(tmp_path), "--no-ai"])

    assert result.exit_code == 2, repr(result.exception)
    assert "Configuration fill failed:" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("change", ["replace", "remove"])
def test_config_file_change_after_read_cannot_redirect_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """A path replaced after its first read must not select a different database."""
    database = tmp_path / "requested.db"
    replacement_database = tmp_path / "replacement.db"
    for target in (database, replacement_database):
        with sqlite_connection(target) as connection:
            connection.execute("CREATE TABLE items (value INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (99)")
    document = {
        "db_path": str(database),
        "provider": "base",
        "tables": [
            {
                "name": "items",
                "count": 2,
                "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
            }
        ],
    }
    config = tmp_path / "generate.yaml"
    config.write_text(yaml.safe_dump(document), encoding="utf-8")
    original_open = open
    changed = False

    @contextmanager
    def open_then_change(file: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
        nonlocal changed
        with original_open(file, *args, **kwargs) as handle:
            yield handle
        if file == config and not changed:
            changed = True
            if change == "remove":
                config.unlink()
            else:
                document["db_path"] = str(replacement_database)
                config.write_text(yaml.safe_dump(document), encoding="utf-8")

    monkeypatch.setattr("builtins.open", open_then_change)
    result = CliRunner().invoke(cli, ["fill", "--config", str(config), "--clear", "--no-ai"])

    assert changed
    assert result.exit_code == 0, result.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]
    with sqlite_connection(replacement_database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(99,)]
