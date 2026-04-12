from __future__ import annotations

from click.testing import CliRunner

from sqlseed.cli.main import cli


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

    def test_fill_with_config(self, tmp_db, tmp_path) -> None:
        import yaml

        config_path = tmp_path / "gen.yaml"
        config_data = {
            "db_path": tmp_db,
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data))
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "fill",
                tmp_db,
                "--table",
                "users",
                "--config",
                str(config_path),
                "--provider",
                "base",
            ],
        )
        assert result.exit_code == 0

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
        from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
        from sqlseed.config.snapshot import SnapshotManager

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
