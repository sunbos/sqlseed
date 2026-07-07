"""Tests for the ``ai-analyze`` CLI command.

Covers the v4 AutoHealOrchestrator default path (Phase 3 Task 3.1 of the
v4 default migration) and the absence of the legacy ``--staged-pipeline``
flag (removed in the same task). Legacy tests that mocked
``SchemaSemanticAnalyzer`` were deleted in Phase 4 Task 4.1 along with the
legacy analyzer itself.

The ``cli_runner`` fixture is defined locally because the rootdir
``conftest.py`` does not provide one — CLI tests in this repo instantiate
``CliRunner()`` inline (see ``plugins/sqlseed-cli/tests/test_cli_ai_commands.py``).
Defining it here keeps the plan's test signatures intact while remaining
self-contained.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a fresh ``CliRunner`` for invoking Click commands."""
    return CliRunner()


class TestAiAnalyzeCommand:
    """Test the ai-analyze CLI command."""

    def test_ai_analyze_help(self, cli_runner: CliRunner) -> None:
        from sqlseed_ai.cli.ai_commands import ai_analyze

        result = cli_runner.invoke(ai_analyze, ["--help"])
        assert result.exit_code == 0
        assert "ai-analyze" in result.output
        assert "--tables" in result.output
        assert "--output" in result.output


def test_ai_analyze_defaults_to_v4_path(monkeypatch, tmp_path):
    """ai-analyze without --staged-pipeline should use AutoHealOrchestrator (v4)."""
    import sqlite3

    from click.testing import CliRunner
    from sqlseed_ai.cli.ai_commands import ai_analyze

    # Create a minimal SQLite db
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()

    captured: dict = {}

    def _fake_run_auto_heal_v4(*, db_path=None, db_url=None, **kwargs):
        captured["called"] = True
        captured["db_path"] = db_path
        captured["db_url"] = db_url
        return "tables: []\n"  # Return a minimal YAML string

    monkeypatch.setattr("sqlseed_ai.cli.ai_commands._run_auto_heal_v4", _fake_run_auto_heal_v4)

    runner = CliRunner()
    result = runner.invoke(
        ai_analyze,
        ["--db", str(db_path), "-o", str(tmp_path / "out.yaml")],
        env={"SQLSEED_AI_API_KEY": "test"},
    )
    assert result.exit_code == 0, f"exit_code={result.exit_code}, output={result.output}"
    assert captured.get("called") is True
    assert captured.get("db_path") == str(db_path)


def test_ai_analyze_no_longer_has_staged_pipeline_flag():
    """ai-analyze should NOT have --staged-pipeline flag after migration."""
    from sqlseed_ai.cli.ai_commands import ai_analyze

    option_names = [opt.name for opt in ai_analyze.params]
    assert "staged_pipeline" not in option_names
