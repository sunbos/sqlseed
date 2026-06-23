"""End-to-end tests for URL-based database connections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner

from sqlseed.cli.main import cli

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _setup_pg_table(pg_url: str) -> None:
    """Create a test table on PG."""
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    engine = create_engine(pg_url)
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT, age INTEGER)"
            )
        )
        conn.commit()
    engine.dispose()


class TestUrlE2E:
    """URL full-chain E2E tests."""

    def test_cli_url_to_pg_e2e(self, pg_url: str) -> None:
        """sqlseed fill --url pg_url -t users -n 100 full CLI→PG chain."""
        _setup_pg_table(pg_url)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["fill", "--url", pg_url, "--table", "users", "--count", "100", "--provider", "base"],
        )
        assert result.exit_code == 0
        assert "100" in result.output

    def test_api_url_to_pg_e2e(self, pg_url: str) -> None:
        """fill(url=pg_url, ...) full API→PG chain."""
        _setup_pg_table(pg_url)
        import sqlseed  # noqa: PLC0415

        result = sqlseed.fill(url=pg_url, table="users", count=50, provider="base")
        assert result.count == 50

    def test_config_url_to_pg_e2e(self, pg_url: str, tmp_path: Path) -> None:
        """YAML with url field → fill_from_config → PG."""
        _setup_pg_table(pg_url)
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": pg_url,
            "provider": "base",
            "tables": [{"name": "users", "count": 30}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        import sqlseed  # noqa: PLC0415

        results = sqlseed.fill_from_config(str(config_path))
        assert len(results) == 1
        assert results[0].count == 30

    def test_pg_url_snapshot_and_replay(
        self, pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On PG, snapshot save + replay (via CLI, since fill() has no snapshot param and replay is not exported)."""
        _setup_pg_table(pg_url)

        cache_dir = str(tmp_path / "cache")
        monkeypatch.setenv("SQLSEED_CACHE_DIR", cache_dir)

        # 1. Save snapshot via CLI fill --snapshot (fill() Python API does not support snapshot param)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                "--url",
                pg_url,
                "--table",
                "users",
                "--count",
                "20",
                "--provider",
                "base",
                "--seed",
                "42",
                "--snapshot",
            ],
        )
        assert result.exit_code == 0, f"CLI fill --snapshot failed: {result.output}"

        # 2. Find the snapshot file (list_snapshots returns list[str], not list[dict])
        from sqlseed.config.snapshot import SnapshotManager  # noqa: PLC0415

        sm = SnapshotManager(str(tmp_path / "cache" / "snapshots"))
        snapshots = sm.list_snapshots()
        assert len(snapshots) > 0, "No snapshot file found"
        snapshot_path = snapshots[0]  # Directly a file path string, not a dict

        # 3. Clear the table
        from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter  # noqa: PLC0415

        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        adapter.clear_table("users")
        assert adapter.get_row_count("users") == 0
        adapter.close()

        # 4. Replay via CLI (sqlseed.replay is not exported from public API, only CLI command)
        result = runner.invoke(cli, ["replay", snapshot_path])
        assert result.exit_code == 0, f"CLI replay failed: {result.output}"

        # 5. Verify data has been replayed
        adapter = SQLAlchemyAdapter()
        adapter.connect(pg_url)
        assert adapter.get_row_count("users") == 20
        adapter.close()

    def test_pg_url_preview_e2e(self, pg_url: str) -> None:
        """preview(url=pg_url, ...) returns correct preview."""
        _setup_pg_table(pg_url)
        import sqlseed  # noqa: PLC0415

        rows = sqlseed.preview(url=pg_url, table="users", count=5, provider="base")
        assert isinstance(rows, list)
        assert len(rows) == 5
        assert all(isinstance(r, dict) for r in rows)

    def test_pg_url_inspect_e2e(self, pg_url: str) -> None:
        """inspect(url=pg_url) shows mapping strategies."""
        _setup_pg_table(pg_url)
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "--url", pg_url])
        assert result.exit_code == 0
        # Verify output contains table name and column name (mapping strategy info)
        assert "users" in result.output, f"inspect output missing table name 'users': {result.output}"
        assert "name" in result.output, f"inspect output missing column name 'name': {result.output}"
