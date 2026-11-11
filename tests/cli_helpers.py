"""Shared real-console discovery and config retry helpers for CLI regressions."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from click.testing import CliRunner


def installed_sqlseed_launcher() -> str:
    """Find the installed entry point without substituting an in-process runner."""
    if (launcher := shutil.which("sqlseed")) is not None:
        return launcher
    local = Path(sys.executable).with_name("sqlseed.exe" if os.name == "nt" else "sqlseed")
    if not local.is_file():
        pytest.skip("An installed SQLSeed console entry point is required")
    return str(local)


def fixed_items_config(database: Path) -> dict[str, Any]:
    """Build a fresh config that writes two deterministic values to items."""
    return {
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


def retry_items_document(
    path: Path, document: dict[str, Any], runner: CliRunner, arguments: list[str], database: Path
) -> None:
    """Correct an invalid document, retry the CLI, and verify real persisted rows."""
    from sqlseed_cli.main import cli

    serialized = json.dumps(document) if path.suffix == ".json" else yaml.safe_dump(document)
    path.write_text(serialized, encoding="utf-8")
    recovered = runner.invoke(cli, arguments)
    assert recovered.exit_code == 0, recovered.output
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,)]
