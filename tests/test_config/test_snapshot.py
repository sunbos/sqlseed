from __future__ import annotations

from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager


class TestSnapshotManager:
    def test_save_snapshot(self, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        config = GeneratorConfig(
            db_path="test.db",
            tables=[TableConfig(name="users", count=100)],
        )
        path = manager.save(config, "users", 100, seed=42)
        assert path.endswith(".yaml")

    def test_load_snapshot(self, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        config = GeneratorConfig(
            db_path="test.db",
            tables=[TableConfig(name="users", count=100)],
        )
        path = manager.save(config, "users", 100, seed=42)
        data = manager.load(path)
        assert data["table_name"] == "users"
        assert data["count"] == 100
        assert data["seed"] == 42

    def test_list_snapshots(self, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        config = GeneratorConfig(db_path="test.db")
        manager.save(config, "users", 100)
        manager.save(config, "orders", 500)
        snapshots = manager.list_snapshots()
        assert len(snapshots) == 2

    def test_list_snapshots_empty_dir(self, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "nonexistent"))
        snapshots = manager.list_snapshots()
        assert snapshots == []

    def test_load_nonexistent(self, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        try:
            manager.load("/nonexistent/snapshot.yaml")
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError:
            pass

    def test_replay(self, tmp_db, tmp_path) -> None:
        manager = SnapshotManager(str(tmp_path / "snapshots"))
        config = GeneratorConfig(
            db_path=tmp_db,
            provider=ProviderType("base"),
            tables=[TableConfig(name="users", count=5)],
        )
        path = manager.save(config, "users", 5, seed=42)
        result = manager.replay(path)
        assert result.count == 5
