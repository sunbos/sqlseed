"""Database fill failures are actionable, redacted, and safe to retry."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

main = importlib.import_module("sqlseed_cli.main")


def _args(config: bool) -> list[str]:
    if config:
        return ["fill", "--config", "unused.yaml", "--no-ai"]
    return ["fill", "unused.db", "--table", "items", "--count", "2", "--provider", "base", "--no-ai"]


def _invoke(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    # Invoke the actual console-script callable in a new interpreter so an
    # uncaught exception cannot be hidden by CliRunner's exception capture.
    return subprocess.run(
        [sys.executable, "-c", "from sqlseed_cli.main import main; main()", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("config", [False, True], ids=["direct", "config"])
def test_missing_rw_target_reports_error_and_allows_retry(tmp_path: Path, config: bool) -> None:
    target = tmp_path / "absent %41.db"
    url = f"sqlite:///{target.as_uri()}?uri=true&mode=rw"
    if config:
        config_path = tmp_path / "generate.json"
        config_path.write_text(
            json.dumps({"url": url, "provider": "base", "tables": [{"name": "items", "count": 2}]}),
            encoding="utf-8",
        )
        args = ["fill", "--config", str(config_path), "--no-ai"]
    else:
        args = ["fill", "--url", url, "--table", "items", "--count", "2", "--provider", "base", "--no-ai"]
    before = set(tmp_path.iterdir())

    failed = _invoke(args, tmp_path)

    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "Error: Database fill failed:" in failed.stderr
    assert "unable to open database file" in failed.stderr
    assert "Traceback" not in failed.stdout + failed.stderr
    assert set(tmp_path.iterdir()) == before
    assert not target.exists()

    # Correct only the target and retry exactly the same command.
    with sqlite_connection(target) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
        connection.execute("INSERT INTO items VALUES (1, 99)")
    recovered = _invoke(args, tmp_path)

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    with sqlite_connection(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone() == (3,)
        assert connection.execute("SELECT value FROM items WHERE id = 1").fetchone() == (99,)
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert set(tmp_path.iterdir()) == before | {target}


@pytest.mark.parametrize("config", [False, True], ids=["direct", "config"])
def test_database_diagnostic_redacts_credentials(monkeypatch: pytest.MonkeyPatch, config: bool) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OperationalError(
            None, None, Exception("failed postgresql://synthetic_user:synthetic_secret@localhost/db")
        )

    # Mock only error text; connection behavior is exercised with real SQLite above.
    monkeypatch.setattr(main, "fill_from_config" if config else "api_fill", fail)
    result = CliRunner().invoke(main.cli, _args(config))

    assert result.exit_code == 1
    assert "Error: Database fill failed:" in result.output
    assert "synthetic_user" not in result.output
    assert "synthetic_secret" not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("config", [False, True], ids=["direct", "config"])
@pytest.mark.parametrize("error", [RuntimeError("unrelated"), SystemExit(7), KeyboardInterrupt()])
def test_unrelated_exceptions_are_not_database_errors(
    monkeypatch: pytest.MonkeyPatch, config: bool, error: BaseException
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(main, "fill_from_config" if config else "api_fill", fail)
    result = CliRunner().invoke(main.cli, _args(config))

    assert "Database fill failed:" not in result.output
    if isinstance(error, RuntimeError):
        assert result.exception is error
    elif isinstance(error, SystemExit):
        assert result.exit_code == 7
    else:
        assert result.exit_code == 1
        assert "Aborted!" in result.output


def test_usage_errors_keep_exit_code_two() -> None:
    result = CliRunner().invoke(main.cli, ["fill", "unused.db", "--table", "items", "--no-ai"])

    assert result.exit_code == 2
    assert "--count is required" in result.output
    assert "Database fill failed:" not in result.output
