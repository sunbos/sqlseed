from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def simple_db(tmp_path: Path) -> Path:
    path = tmp_path / "simple.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    return path


def test_ai_suggest_has_auto_heal_flag(simple_db: Path):
    """`ai-suggest --help` mentions --auto-heal."""
    from sqlseed_ai.cli.ai_commands import ai_suggest

    runner = CliRunner()
    result = runner.invoke(ai_suggest, ["--help"])
    assert result.exit_code == 0
    assert "--auto-heal" in result.output


def test_ai_suggest_auto_heal_invokes_orchestrator(simple_db: Path):
    """`ai-suggest --auto-heal` calls AutoHealOrchestrator.run()."""
    from sqlseed_ai.cli.ai_commands import ai_suggest

    runner = CliRunner()
    with patch("sqlseed_ai.auto_heal.orchestrator.AutoHealOrchestrator") as mock_orch_class:
        mock_orch = MagicMock()
        mock_orch.run.return_value = "tables: []"
        mock_orch_class.return_value = mock_orch
        result = runner.invoke(
            ai_suggest,
            [str(simple_db), "--auto-heal"],
        )
    assert result.exit_code == 0
    mock_orch.run.assert_called_once()
