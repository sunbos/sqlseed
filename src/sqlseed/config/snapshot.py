"""sqlseed configuration snapshot management.

SnapshotManager is responsible for saving, loading, and listing configuration
snapshots, used by the replay feature (regenerating previously saved configurations).
"""

from __future__ import annotations

import hashlib
import re
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
    """Configuration snapshot manager.

    Responsible for saving GeneratorConfig to timestamped YAML snapshot files,
    and supporting loading and listing existing snapshots. Snapshots are used
    by the replay feature.
    """

    def __init__(self, snapshot_dir: str | None = None) -> None:
        """Initialize the snapshot manager.

        Args:
            snapshot_dir: Snapshot directory path. If None, the default cache directory is used.
        """
        self._snapshot_dir = Path(snapshot_dir) if snapshot_dir else get_cache_dir("snapshots")

    def save(
        self,
        config: GeneratorConfig,
        table_name: str,
        count: int,
        seed: int | None = None,
    ) -> str:
        """Save a configuration snapshot to a YAML file.

        File name format: {timestamp}_{safe_table_label}.yaml. The original
        table name is preserved in the snapshot, independently of its filename.

        Args:
            config: Generator configuration
            table_name: Table name (used for file naming)
            count: Number of rows to generate
            seed: Random seed (optional)

        Returns:
            Snapshot file path
        """
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Include microseconds to avoid filename collisions when multiple snapshots
        # are saved within the same second.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        # SQL identifiers can contain path separators and exceed filesystem
        # filename limits. Keep familiar names readable and bound all others.
        table_label = table_name
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", table_label) is None:
            table_label = f"table-{hashlib.sha256(table_name.encode('utf-8')).hexdigest()[:16]}"
        filename = f"{timestamp}_{table_label}.yaml"
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
        """Load a snapshot file.

        Args:
            snapshot_path: Snapshot file path

        Returns:
            Snapshot data dict, containing fields such as timestamp, table_name,
            count, seed, and config

        Raises:
            FileNotFoundError: Snapshot file does not exist
            ValueError: Snapshot contents are not a mapping
        """
        path = Path(snapshot_path)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError("Snapshot must contain a YAML mapping")
        result: dict[str, Any] = data
        return result

    def list_snapshots(self) -> list[str]:
        """List all snapshot file paths in the snapshot directory.

        Returns:
            List of snapshot file paths sorted by file name. Returns an empty
            list if the directory does not exist.
        """
        if not self._snapshot_dir.exists():
            return []
        return sorted(str(p) for p in self._snapshot_dir.glob("*.yaml"))
