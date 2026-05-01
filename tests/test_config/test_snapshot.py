from __future__ import annotations

from typing import Any

from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager


class TestSnapshotManager:
    def _make_manager(self, tmp_path: Any) -> SnapshotManager:
        return SnapshotManager(str(tmp_path / "snapshots"))

    def _make_users_config(self, db_path: str = "test.db") -> GeneratorConfig:
        return GeneratorConfig(
            db_path=db_path,
            tables=[TableConfig(name="users", count=100)],
        )

    def test_save_snapshot(self, tmp_path: Any) -> None:
        manager = self._make_manager(tmp_path)
        config = self._make_users_config()
        path = manager.save(config, "users", 100, seed=42)
        assert path.endswith(".yaml")

    def test_load_snapshot(self, tmp_path: Any) -> None:
        manager = self._make_manager(tmp_path)
        config = self._make_users_config()
        path = manager.save(config, "users", 100, seed=42)
        data = manager.load(path)
        assert data["table_name"] == "users"
        assert data["count"] == 100
        assert data["seed"] == 42

    def test_list_snapshots(self, tmp_path: Any) -> None:
        manager = self._make_manager(tmp_path)
        config = GeneratorConfig(db_path="test.db")
        manager.save(config, "users", 100)
        manager.save(config, "orders", 500)
        snapshots = manager.list_snapshots()
        assert len(snapshots) == 2

    def test_list_snapshots_empty_dir(self, tmp_path: Any) -> None:
        manager = SnapshotManager(str(tmp_path / "nonexistent"))
        snapshots = manager.list_snapshots()
        assert snapshots == []

    def test_load_nonexistent(self, tmp_path: Any) -> None:
        manager = self._make_manager(tmp_path)
        try:
            manager.load("/nonexistent/snapshot.yaml")
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError:
            pass

    def test_replay(self, tmp_db, tmp_path: Any) -> None:
        manager = self._make_manager(tmp_path)
        config = GeneratorConfig(
            db_path=tmp_db,
            provider=ProviderType("base"),
            tables=[TableConfig(name="users", count=5)],
        )
        path = manager.save(config, "users", 5, seed=42)
        result = manager.replay(path)
        assert result.count == 5
