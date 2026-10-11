"""Unreadable snapshots should produce actionable CLI errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner
from sqlseed_cli.main import cli

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


@pytest.mark.parametrize(
    "contents",
    [
        b"config: [\n",
        b"config: !unsupported {}\n",
        b"config: \xff\n",
    ],
    ids=["malformed-yaml", "unsupported-tag", "invalid-utf8"],
)
def test_replay_invalid_snapshot_reports_format_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: bytes
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    snapshot = tmp_path / "invalid.yaml"
    snapshot.write_bytes(contents)

    result = CliRunner().invoke(cli, ["replay", str(snapshot)])

    assert result.exit_code == 2, repr(result.exception)
    assert "Invalid snapshot file format:" in result.output
    assert "Traceback" not in result.output
    assert snapshot.read_bytes() == contents


def test_replay_directory_reports_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.mkdir()

    result = CliRunner().invoke(cli, ["replay", str(snapshot)])

    assert result.exit_code == 2, repr(result.exception)
    assert "Cannot read snapshot file:" in result.output
    assert "Traceback" not in result.output


def test_replay_missing_snapshot_keeps_specific_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    snapshot = tmp_path / "missing.yaml"

    result = CliRunner().invoke(cli, ["replay", str(snapshot)])

    assert result.exit_code == 2
    assert "Snapshot file not found:" in result.output


def _snapshot_for_database(database: Path) -> dict[str, Any]:
    return {
        "table_name": "items",
        "count": 2,
        "seed": None,
        "config": {
            "db_path": str(database),
            "provider": "base",
            "tables": [
                {
                    "name": "items",
                    "count": 2,
                    "clear_before": True,
                    "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
                }
            ],
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("table_name", None),
        ("table_name", False),
        ("table_name", 1),
        ("table_name", []),
        ("table_name", {}),
        ("table_name", ""),
        ("table_name", "  "),
        ("count", None),
        ("count", False),
        ("count", True),
        ("count", "many"),
        ("count", "2"),
        ("count", 2.5),
        ("count", 0),
        ("count", -1),
        ("count", []),
        ("seed", True),
        ("seed", False),
        ("seed", "42"),
        ("seed", 2.5),
        ("seed", {}),
        ("seed", []),
    ],
)
def test_replay_invalid_metadata_preserves_rows_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "demo.db"
    with sqlite_connection(database) as connection:
        connection.execute("CREATE TABLE items (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO items VALUES (99)")
    valid = _snapshot_for_database(database)
    invalid = {**valid, field: value}
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(yaml.safe_dump(invalid), encoding="utf-8")
    runner = CliRunner()
    args = ["replay", str(snapshot)]

    failed = runner.invoke(cli, args)

    assert failed.exit_code == 2, repr(failed.exception)
    assert "Invalid snapshot file format:" in failed.output
    assert field in failed.output
    assert "Traceback" not in failed.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(99,)]

    snapshot.write_text(yaml.safe_dump(valid), encoding="utf-8")
    recovered = runner.invoke(cli, args)

    assert recovered.exit_code == 0, recovered.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]


@pytest.mark.parametrize("seed", ["omitted", None, 0, -7])
def test_replay_preserves_optional_and_integer_seed_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seed: str | int | None
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "demo.db"
    with sqlite_connection(database) as connection:
        connection.execute("CREATE TABLE items (value INTEGER NOT NULL)")
    document = _snapshot_for_database(database)
    if seed == "omitted":
        del document["seed"]
    else:
        document["seed"] = seed
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(yaml.safe_dump(document), encoding="utf-8")

    result = CliRunner().invoke(cli, ["replay", str(snapshot)])

    assert result.exit_code == 0, result.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]


@pytest.mark.parametrize("field", ["table_name", "count"])
def test_replay_missing_metadata_is_rejected_before_database_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
    database = tmp_path / "not-created.db"
    document = _snapshot_for_database(database)
    del document[field]
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(yaml.safe_dump(document), encoding="utf-8")

    result = CliRunner().invoke(cli, ["replay", str(snapshot)])

    assert result.exit_code == 2, result.output
    assert "Invalid snapshot file format:" in result.output
    assert field in result.output
    assert not database.exists()
