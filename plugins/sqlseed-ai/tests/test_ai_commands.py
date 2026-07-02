"""Tests for the ``ai-analyze`` CLI command.

These tests cover the ``ai-analyze`` subcommand added in Stage 6 of the
schema-driven architecture refactor: full-database mode, partial-tables
mode, and the ``--no-dependencies`` flag.

The ``cli_runner`` fixture is defined locally because the rootdir
``conftest.py`` does not provide one — CLI tests in this repo instantiate
``CliRunner()`` inline (see ``plugins/sqlseed-cli/tests/test_cli_ai_commands.py``).
Defining it here keeps the plan's test signatures intact while remaining
self-contained.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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

    def test_ai_analyze_full_database(self, cli_runner: CliRunner, tmp_db_full: str) -> None:
        from sqlseed_ai.cli.ai_commands import ai_analyze

        with patch("sqlseed_ai.cli.ai_commands.SchemaSemanticAnalyzer") as mock_analyzer:
            mock_inst = mock_analyzer.return_value
            mock_inst.analyze.return_value = {"tables": [{"name": "users"}]}
            result = cli_runner.invoke(
                ai_analyze,
                ["--db", str(tmp_db_full), "--output", str(Path(tmp_db_full).parent / "out.yaml")],
            )
            assert result.exit_code == 0
            mock_inst.analyze.assert_called_once()

    def test_ai_analyze_partial_tables(self, cli_runner: CliRunner, tmp_db_full: str) -> None:
        from sqlseed_ai.cli.ai_commands import ai_analyze

        with patch("sqlseed_ai.cli.ai_commands.SchemaSemanticAnalyzer") as mock_analyzer:
            mock_inst = mock_analyzer.return_value
            mock_inst.analyze.return_value = {"tables": []}
            result = cli_runner.invoke(
                ai_analyze,
                ["--db", str(tmp_db_full), "--tables", "orders", "--output", "out.yaml"],
            )
            assert result.exit_code == 0
            call_kwargs = mock_inst.analyze.call_args.kwargs
            assert call_kwargs.get("tables") == ["orders"]

    def test_ai_analyze_no_dependencies_flag(self, cli_runner: CliRunner, tmp_db_full: str) -> None:
        from sqlseed_ai.cli.ai_commands import ai_analyze

        with patch("sqlseed_ai.cli.ai_commands.SchemaSemanticAnalyzer") as mock_analyzer:
            mock_inst = mock_analyzer.return_value
            mock_inst.analyze.return_value = {"tables": []}
            result = cli_runner.invoke(
                ai_analyze,
                ["--db", str(tmp_db_full), "--no-dependencies", "--output", "out.yaml"],
            )
            assert result.exit_code == 0
            call_kwargs = mock_inst.analyze.call_args.kwargs
            assert call_kwargs.get("include_dependencies") is False


def test_ai_analyze_command_accepts_staged_pipeline_flag() -> None:
    """ai-analyze command accepts --staged-pipeline flag."""
    from sqlseed_ai.cli.ai_commands import ai_analyze

    runner = CliRunner()
    # Use --help to verify the flag exists without invoking the LLM
    result = runner.invoke(ai_analyze, ["--help"])
    assert result.exit_code == 0
    assert "--staged-pipeline" in result.output


def test_ai_analyze_command_staged_pipeline_flag_sets_config() -> None:
    """--staged-pipeline flag flips AIConfig.use_staged_pipeline to True."""
    from sqlseed_ai.cli.ai_commands import _build_ai_config

    config = _build_ai_config(
        api_key="test",
        model="gemma-4-e2b-it",
        staged_pipeline=True,
    )
    assert config.use_staged_pipeline is True

    config2 = _build_ai_config(
        api_key="test",
        model="gemma-4-e2b-it",
        staged_pipeline=False,
    )
    assert config2.use_staged_pipeline is False
