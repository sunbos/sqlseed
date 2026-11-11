from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from sqlseed.config import snapshot
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


@pytest.mark.parametrize(
    "contents",
    [
        "metadata: &node {self: *node}\n",
        "config: {tables: [{columns: [{params: {schema: &node {type: array, items: *node}}}]}]}\n",
        "metadata: &items [*items]\n",
        "metadata: &items !!pairs [{self: *items}]\n",
    ],
    ids=["metadata-mapping", "config-schema", "metadata-list", "metadata-pairs"],
)
def test_snapshot_rejects_cycles_in_parsed_data(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "cyclic.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="cyclic YAML alias"):
        SnapshotManager(str(tmp_path / "cache")).load(str(path))

    assert path.read_text(encoding="utf-8") == contents


def test_snapshot_accepts_shared_aliases_and_merge_keys(tmp_path: Path) -> None:
    path = tmp_path / "shared.yaml"
    path.write_text("left: &leaf {type: boolean}\nright: *leaf\nmerged: {<<: *leaf, title: flag}\n", encoding="utf-8")

    data = SnapshotManager(str(tmp_path / "cache")).load(str(path))

    assert data["left"] is data["right"]
    assert data["merged"] == {"type": "boolean", "title": "flag"}


def test_snapshot_accepts_self_merge_flattened_by_parser(tmp_path: Path) -> None:
    path = tmp_path / "self-merge.yaml"
    path.write_text("metadata: &node {<<: *node, label: safe}\n", encoding="utf-8")

    data = SnapshotManager(str(tmp_path / "cache")).load(str(path))

    assert data == {"metadata": {"label": "safe"}}


class _FixedClock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 1, 2, 3, 4, 5, 123456)


@pytest.mark.parametrize("table_name", ["users", "订单/明细"])
def test_same_tick_saves_preserve_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table_name: str
) -> None:
    monkeypatch.setattr(snapshot, "datetime", _FixedClock)
    manager = SnapshotManager(str(tmp_path))
    original = GeneratorConfig(db_path="first.db", tables=[TableConfig(name=table_name, count=3)])
    first = manager.save(original, table_name, 3, seed=11)
    before = Path(first).read_bytes()
    replacement = GeneratorConfig(db_path="second.db", tables=[TableConfig(name=table_name, count=5)])

    second = manager.save(replacement, table_name, 5, seed=13)
    third = manager.save(original, table_name, 7, seed=17)

    assert len({first, second, third}) == 3
    assert manager.list_snapshots() == sorted([first, second, third])
    assert Path(first).read_bytes() == before
    for path, config, count, seed in [
        (first, original, 3, 11),
        (second, replacement, 5, 13),
        (third, original, 7, 17),
    ]:
        loaded = manager.load(path)
        assert loaded["config"] == config.model_dump(mode="json")
        assert (loaded["table_name"], loaded["count"], loaded["seed"]) == (table_name, count, seed)


def test_concurrent_same_tick_saves_keep_each_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "datetime", _FixedClock)
    barrier = Barrier(8)

    def save(index: int) -> str:
        manager = SnapshotManager(str(tmp_path))
        config = GeneratorConfig(db_path=f"database-{index}.db")
        barrier.wait(timeout=5)
        return manager.save(config, "users", index + 1, seed=index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(save, range(8)))

    manager = SnapshotManager(str(tmp_path))
    assert len(set(paths)) == 8
    assert manager.list_snapshots() == sorted(paths)
    for index, path in enumerate(paths):
        loaded = manager.load(path)
        assert loaded["config"]["db_path"] == f"database-{index}.db"
        assert (loaded["count"], loaded["seed"]) == (index + 1, index)
