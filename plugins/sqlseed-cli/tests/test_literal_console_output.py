"""Real console output must preserve literal schema names and generated values."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from sqlseed import preview
from tests.cli_helpers import installed_sqlseed_launcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("command", ["preview", "inspect"])
@pytest.mark.parametrize("style", ["balanced", "closing", "emoji", "plain"])
def test_literal_console_output(tmp_path: Path, command: str, style: str) -> None:
    def literal(word: str, color: str) -> str:
        if style == "balanced":
            return f"[{color}]{word}[/{color}]"
        if style == "closing":
            return f"{word}[/{color}]"
        if style == "emoji":
            return f"{word}:smile:"
        return word

    table = literal("表", "red")
    column = literal("值", "blue")
    value = literal("字", "green")
    parent = literal("父", "cyan")
    parent_key = literal("键", "magenta")
    foreign_key = literal("父键", "yellow")
    database = tmp_path / "display.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f'CREATE TABLE "{parent}" ("{parent_key}" INTEGER PRIMARY KEY)')
        connection.execute(f'INSERT INTO "{parent}" VALUES (7)')
        connection.execute(
            f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, '
            f'"{column}" TEXT NOT NULL CHECK ("{column}" IN (\'{value}\')), '
            f'"{foreign_key}" INTEGER NOT NULL REFERENCES "{parent}" ("{parent_key}"))'
        )
        connection.execute(f'INSERT INTO "{table}" VALUES (?, ?, ?)', (901, value, 7))
        connection.commit()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    # Check actual generated objects independently of the CLI renderer.
    rows = preview(str(database), table=table, count=2, provider="base", seed=42)
    assert len(rows) == 2
    assert all(row[column] == value and row[foreign_key] == 7 for row in rows)

    launcher = installed_sqlseed_launcher()
    args = [launcher, command, str(database), "-t", table]
    if command == "preview":
        args += ["-n", "2", "-p", "base", "-s", "42"]
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        NO_COLOR="1",
        TERM="dumb",
        COLUMNS="240",
        SQLSEED_LOG_LEVEL="ERROR",
    )
    result = subprocess.run(args, env=env, capture_output=True, timeout=30, check=False)
    stdout = result.stdout.decode("utf-8")
    stderr = result.stderr.decode("utf-8")
    (tmp_path / "stdout.txt").write_text(stdout, encoding="utf-8")
    (tmp_path / "stderr.txt").write_text(stderr, encoding="utf-8")
    (tmp_path / "result.json").write_text(
        json.dumps({"args": args, "returncode": result.returncode, "generated": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(f'SELECT * FROM "{table}"').fetchall() == [(901, value, 7)]
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert result.returncode == 0, stderr
    assert "Traceback" not in stderr
    assert table in stdout
    assert column in stdout
    assert foreign_key in stdout
    if command == "preview":
        assert stdout.count(value) == 2
    else:
        assert parent in stdout
        assert parent_key in stdout
