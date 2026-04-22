from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)


class SnapshotManager:
    def __init__(self, snapshot_dir: str | None = None) -> None:
        self._snapshot_dir = Path(snapshot_dir) if snapshot_dir else Path("./snapshots")

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

    def replay(self, snapshot_path: str) -> Any:
        data = self.load(snapshot_path)
        config_data = data["config"]
        config = GeneratorConfig(**config_data)

        table_name = data["table_name"]
        count = data["count"]
        seed = data.get("seed")

        table_config = None
        for tc in config.tables:
            if tc.name == table_name:
                table_config = tc
                break

        with DataOrchestrator.from_config(config) as orch:
            return orch.fill_table(
                table_name=table_name,
                count=count,
                seed=seed,
                batch_size=table_config.batch_size if table_config else 5000,
                clear_before=table_config.clear_before if table_config else False,
                column_configs=table_config.columns if table_config else None,
            )

    def list_snapshots(self) -> list[str]:
        if not self._snapshot_dir.exists():
            return []
        return sorted(str(p) for p in self._snapshot_dir.glob("*.yaml"))
