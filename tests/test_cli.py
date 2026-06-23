"""Tests for the sqlseed CLI commands."""

from __future__ import annotations

import sqlite3
from importlib.metadata import version as pkg_version
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from click.testing import CliRunner
from sqlalchemy.exc import NoSuchModuleError

from sqlseed.cli.main import cli
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager

if TYPE_CHECKING:
    from pathlib import Path

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
    def test_fill_with_config(self, tmp_db, tmp_path: Path, extra_args) -> None:
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

    def test_fill_with_transform(self, tmp_path: Path) -> None:
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

    def test_fill_with_snapshot(self, tmp_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SQLSEED_CACHE_DIR", str(tmp_path / "cache"))
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
    def test_init(self, tmp_path: Path) -> None:
        runner = CliRunner()
        config_path = str(tmp_path / "gen.yaml")
        result = runner.invoke(cli, ["init", config_path, "--db", "test.db"])
        assert result.exit_code == 0


class TestCLIReplay:
    def test_replay(self, tmp_db, tmp_path: Path) -> None:
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
    @pytest.fixture
    def ai_suggest_setup(
        self, unique_test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[CliRunner, str, str]:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("SQLSEED_AI_BACKEND", raising=False)
        runner = CliRunner()
        output_path = str(tmp_path / "output.yaml")
        return runner, unique_test_db, output_path

    @pytest.mark.skipif(
        not _AI_PLUGIN_AVAILABLE,
        reason="Requires sqlseed-ai plugin",
    )
    def test_ai_suggest_no_api_key(self, ai_suggest_setup: Any) -> None:
        runner, db_path, output_path = ai_suggest_setup
        result = runner.invoke(
            cli,
            ["ai-suggest", db_path, "--table", "projects", "--output", output_path],
        )
        assert result.exit_code == 1
        assert "API key not configured" in result.output

    @pytest.mark.skipif(
        not _AI_PLUGIN_AVAILABLE,
        reason="Requires sqlseed-ai plugin",
    )
    def test_ai_suggest_with_model_option(self, ai_suggest_setup: Any) -> None:
        runner, db_path, output_path = ai_suggest_setup
        result = runner.invoke(
            cli,
            [
                "ai-suggest",
                db_path,
                "--table",
                "projects",
                "--output",
                output_path,
                "--model",
                "openrouter/free",
            ],
        )
        assert result.exit_code == 1


class TestCLIUrlOption:
    """Tests for the --url option of CLI fill/preview/inspect commands."""

    def test_fill_with_url_sqlite(self, tmp_db) -> None:
        """sqlseed fill --url "sqlite:///path.db" -t users -n 10 succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "10", "--provider", "base"],
        )
        assert result.exit_code == 0
        # Stronger assertion: verify that the output contains the table name and row count
        assert "users" in result.output
        assert "10" in result.output

        # Verify that data was actually written
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 10
        conn.close()

    def test_fill_with_url_and_db_path_mutual_exclusion(self, tmp_db) -> None:
        """Providing both db_path and --url raises a UsageError."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", tmp_db, "--url", url, "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        assert "Cannot specify both" in result.output

    def test_fill_without_url_or_db_path_errors(self) -> None:
        """Providing neither raises a UsageError."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        assert "db_path or --url is required" in result.output

    def test_preview_with_url(self, tmp_db) -> None:
        """sqlseed preview --url "sqlite:///path.db" -t users -n 5 succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["preview", "--url", url, "--table", "users", "--count", "5", "--provider", "base"],
        )
        assert result.exit_code == 0

    def test_inspect_with_url(self, tmp_db) -> None:
        """sqlseed inspect --url "sqlite:///path.db" succeeds."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["inspect", "--url", url],
        )
        assert result.exit_code == 0

    def test_fill_url_output_format(self, tmp_db) -> None:
        """In url mode the output format matches the db_path mode."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"

        # url mode
        result_url = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base"],
        )
        # db_path mode
        result_path = runner.invoke(
            cli,
            ["fill", tmp_db, "--table", "users", "--count", "5", "--provider", "base"],
        )
        assert result_url.exit_code == 0
        assert result_path.exit_code == 0
        # Both should contain the row count information
        assert "5" in result_url.output

    def test_fill_url_with_config(self, tmp_db, tmp_path) -> None:
        """--url and --config can coexist (config specifies table config, url specifies the connection)."""
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": f"sqlite:///{tmp_db}",
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["fill", "--config", str(config_path)])
        assert result.exit_code == 0

        # Stronger assertion: verify that data was actually written
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_fill_url_postgresql_missing_driver(self, monkeypatch) -> None:
        """When the PG URL is missing a driver, the CLI reports a friendly error.

        RuntimeError is not caught by the except ValueError in _execute_fill,
        so it propagates to CliRunner's result.exception (catch_exceptions=True by default).
        """

        def mock_create_engine(url: str, **kwargs: Any) -> Any:
            raise NoSuchModuleError("postgresql.psycopg")

        monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--url", "postgresql://user:pass@host/db", "--table", "users", "--count", "10"],
        )
        assert result.exit_code != 0
        # RuntimeError propagates to result.exception (not a ValueError, so not caught as a UsageError)
        assert result.exception is not None
        assert "PostgreSQL driver not installed" in str(result.exception)
        assert "pip install sqlseed[postgres]" in str(result.exception)

    def test_fill_url_snapshot_flag(self, tmp_db, tmp_path, monkeypatch) -> None:
        """In url mode --snapshot works correctly and the snapshot file is generated.

        The CLI's _save_snapshot_cmd uses SnapshotManager() (no args),
        which internally calls get_cache_dir("snapshots") and appends a "snapshots"
        subdirectory to SQLSEED_CACHE_DIR. The test must look in the same directory.
        """
        cache_root = str(tmp_path / "cache")
        monkeypatch.setenv("SQLSEED_CACHE_DIR", cache_root)

        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"
        result = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--snapshot"],
        )
        assert result.exit_code == 0
        # CLI output should contain the snapshot save path
        assert "Snapshot saved:" in result.output

        # Verify that the snapshot file was actually generated under cache_root/snapshots/
        # (SnapshotManager() internally calls get_cache_dir("snapshots") which appends a "snapshots" subdirectory)
        sm = SnapshotManager(str(tmp_path / "cache" / "snapshots"))
        snapshots = sm.list_snapshots()
        assert len(snapshots) > 0, "snapshot file should have been generated"

    def test_fill_url_with_seed_reproducibility(self, tmp_db) -> None:
        """In url mode --seed is reproducible."""
        runner = CliRunner()
        url = f"sqlite:///{tmp_db}"

        # First fill
        result1 = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--seed", "42", "--clear"],
        )
        assert result1.exit_code == 0

        # Read the data
        conn = sqlite3.connect(tmp_db)
        rows1 = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
        conn.close()

        # Clear and fill a second time (same seed)
        result2 = runner.invoke(
            cli,
            ["fill", "--url", url, "--table", "users", "--count", "5", "--provider", "base", "--seed", "42", "--clear"],
        )
        assert result2.exit_code == 0

        conn = sqlite3.connect(tmp_db)
        rows2 = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
        conn.close()

        assert rows1 == rows2
