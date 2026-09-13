from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sqlseed.config.models import GeneratorConfig, TableConfig
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
        with pytest.raises(FileNotFoundError):
            manager.load("/nonexistent/snapshot.yaml")

    @pytest.mark.parametrize("table_name", ["sales/orders", "../outside", "sales:orders", "x" * 300, "订单" * 100])
    def test_save_arbitrary_table_name(self, tmp_path: Path, table_name: str) -> None:
        manager = self._make_manager(tmp_path)
        config = GeneratorConfig(db_path="test.db", tables=[TableConfig(name=table_name, count=1)])

        path = Path(manager.save(config, table_name, 1))

        assert path.parent == tmp_path / "snapshots"
        data = manager.load(str(path))
        assert data["table_name"] == table_name
        assert data["config"]["tables"][0]["name"] == table_name
        assert manager.list_snapshots() == [str(path)]

    @pytest.mark.parametrize("contents", ["", "null", "[]", "42", "a string"])
    def test_load_rejects_non_mapping(self, tmp_path: Path, contents: str) -> None:
        path = tmp_path / "invalid.yaml"
        path.write_text(contents, encoding="utf-8")
        manager = self._make_manager(tmp_path)
        path_string = str(path)
        with pytest.raises(ValueError, match="mapping"):
            manager.load(path_string)

    def test_replay_removed(self, tmp_path: Any) -> None:
        """SnapshotManager.replay() was removed (H5: config→core reverse dependency).
        Replay logic now lives in the CLI layer. Verify the method no longer exists."""
        manager = self._make_manager(tmp_path)
        assert not hasattr(manager, "replay"), "replay() should have been removed from SnapshotManager"
