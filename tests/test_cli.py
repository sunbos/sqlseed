from __future__ import annotations

import sqlite3
from importlib.metadata import version as pkg_version

import pytest
import yaml
from click.testing import CliRunner

from sqlseed.cli.main import cli
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager

_AI_PLUGIN_AVAILABLE: bool = False
try:
    import importlib

    importlib.import_module("sqlseed_ai")
    _AI_PLUGIN_AVAILABLE = True
except ImportError:
    pass


class TestCLIFill:
    def test_fill_basic(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "10", "--provider", "base"],
        )
        assert result.exit_code == 0
        assert "10" in result.output

    def test_fill_with_seed(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                tmp_db,
                "--table",
                "users",
                "--count",
                "5",
                "--provider",
                "base",
                "--seed",
                "42",
            ],
        )
        assert result.exit_code == 0

    def test_fill_with_clear(self, tmp_db) -> None:
        runner = CliRunner()
        runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "5", "--provider", "base"],
        )
        result = runner.invoke(
            cli,
            [
                "fill",
                tmp_db,
                "--table",
                "users",
                "--count",
                "3",
                "--provider",
                "base",
                "--clear",
            ],
        )
        assert result.exit_code == 0

    def test_fill_count_zero_shows_error(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "0", "--provider", "base"],
        )
        assert result.exit_code != 0
        assert "count" in result.output.lower()
        assert "must be greater than 0" in result.output

    def test_fill_count_negative_shows_error(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "-1", "--provider", "base"],
        )
        assert result.exit_code != 0
        assert "count" in result.output.lower()
        assert "must be greater than 0" in result.output

    def test_fill_missing_count_shows_error(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--provider", "base"],
        )
        assert result.exit_code != 0
        assert "--count is required" in result.output

    @pytest.mark.parametrize(
        "extra_args",
        [
            [],
            [pytest.param("{db}", "--table", "users", "--provider", "base", id="with_db_table")],
        ],
    )
    def test_fill_with_config(self, tmp_db, tmp_path, extra_args) -> None:
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "db_path": tmp_db,
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data))
        runner = CliRunner()
        args = ["fill", "--config", str(config_path)]
        for arg in extra_args:
            args.append(arg.format(db=tmp_db) if "{db}" in arg else arg)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0

    def test_fill_with_transform(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.close()

        transform_path = str(tmp_path / "transform.py")
        with open(transform_path, "w", encoding="utf-8") as f:
            f.write("def transform_row(row, ctx):\n    row['name'] = row.get('name', '').upper()\n    return row\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                db_path,
                "--table",
                "users",
                "--count",
                "5",
                "--provider",
                "base",
                "--transform",
                transform_path,
            ],
        )
        assert result.exit_code == 0

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM users").fetchall()
        conn.close()
        for (name,) in rows:
            if name:
                assert name == name.upper()

    def test_fill_with_snapshot(self, tmp_db, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                tmp_db,
                "--table",
                "users",
                "--count",
                "5",
                "--provider",
                "base",
                "--snapshot",
            ],
        )
        assert result.exit_code == 0
        assert "Snapshot saved" in result.output


class TestCLIPreview:
    def test_preview(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "preview",
                tmp_db,
                "--table",
                "users",
                "--count",
                "3",
                "--provider",
                "base",
            ],
        )
        assert result.exit_code == 0


class TestCLIInspect:
    def test_inspect_all_tables(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", tmp_db])
        assert result.exit_code == 0

    def test_inspect_specific_table(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", tmp_db, "--table", "users"])
        assert result.exit_code == 0

    def test_inspect_with_mapping(self, tmp_db) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", tmp_db, "--table", "users", "--show-mapping"])
        assert result.exit_code == 0


class TestCLIInit:
    def test_init(self, tmp_path) -> None:
        runner = CliRunner()
        config_path = str(tmp_path / "gen.yaml")
        result = runner.invoke(cli, ["init", config_path, "--db", "test.db"])
        assert result.exit_code == 0


class TestCLIReplay:
    def test_replay(self, tmp_db, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        config = GeneratorConfig(
            db_path=tmp_db,
            provider=ProviderType.BASE,
            tables=[TableConfig(name="users", count=5)],
        )
        snapshot_path = manager.save(config, "users", 5, seed=42)

        runner = CliRunner()
        result = runner.invoke(cli, ["replay", snapshot_path])
        assert result.exit_code == 0


class TestCLIMain:
    def test_main_entry(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_version_matches_package_metadata(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        expected = pkg_version("sqlseed")
        assert expected in result.output, f"Expected '{expected}' in version output, got: {result.output}"


class TestCLIAISuggest:
    @pytest.mark.skipif(
        not _AI_PLUGIN_AVAILABLE,
        reason="Requires sqlseed-ai plugin",
    )
    def test_ai_suggest_no_api_key(self, bank_cards_db, tmp_path) -> None:
        runner = CliRunner()
        output_path = str(tmp_path / "output.yaml")
        result = runner.invoke(
            cli,
            ["ai-suggest", bank_cards_db, "--table", "bank_cards", "--output", output_path],
        )
        assert result.exit_code == 0
        assert "No suggestions received" in result.output or "AI suggestion" in result.output

    @pytest.mark.skipif(
        not _AI_PLUGIN_AVAILABLE,
        reason="Requires sqlseed-ai plugin",
    )
    def test_ai_suggest_with_model_option(self, bank_cards_db, tmp_path) -> None:
        runner = CliRunner()
        output_path = str(tmp_path / "output.yaml")
        result = runner.invoke(
            cli,
            ["ai-suggest", bank_cards_db, "--table", "bank_cards", "--output", output_path, "--model", "gpt-4o"],
        )
        assert result.exit_code == 0
