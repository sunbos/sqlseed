from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir

if TYPE_CHECKING:
    from sqlseed.config.models import GeneratorConfig

logger = get_logger(__name__)


class SnapshotManager:
    def __init__(self, snapshot_dir: str | None = None) -> None:
        self._snapshot_dir = Path(snapshot_dir) if snapshot_dir else get_cache_dir("snapshots")

    def save(
        self,
        config: GeneratorConfig,
        table_name: str,
        count: int,
        seed: int | None = None,
    ) -> str:
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"{timestamp}_{table_name}.yaml"
        filepath = self._snapshot_dir / filename

        snapshot_data = {
            "timestamp": timestamp,
            "table_name": table_name,
            "count": count,
            "seed": seed,
            "config": config.model_dump(mode="json"),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(snapshot_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info("Snapshot saved", filepath=str(filepath))
        return str(filepath)

    def load(self, snapshot_path: str) -> dict[str, Any]:
        path = Path(snapshot_path)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        return data

    def list_snapshots(self) -> list[str]:
        if not self._snapshot_dir.exists():
            return []
        return sorted(str(p) for p in self._snapshot_dir.glob("*.yaml"))
