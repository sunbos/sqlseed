"""Unreadable snapshots should produce actionable CLI errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner
from sqlseed_cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path


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
