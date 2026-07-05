"""Broken-edge post-repair — Section 14 (nullable FK range alignment).

When :class:`SubgraphSplitter` breaks a megacluster, the broken FK edges
lose their referential integrity during LLM analysis. After healing, this
module re-aligns the broken FK columns by marking them nullable so the
runtime generator can pick from the parent table's existing value set
without crashing on missing parents.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class BrokenEdgeAligner:
    """Re-align nullable FK columns broken by megacluster splitting."""

    def align(
        self,
        config: dict[str, Any],
        broken_edges: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Mark FK columns on the source side of broken edges as nullable.

        Args:
            config: Full per-table config.
            broken_edges: List of (src_table, dst_table) tuples from
                :class:`SubgraphSplitter`.

        Returns:
            New config dict (input is not mutated).
        """
        if not broken_edges:
            return config

        new_config = copy.deepcopy(config)
        broken_sources = {src for src, _ in broken_edges}

        for table_cfg in new_config.get("tables", []):
            if table_cfg["name"] not in broken_sources:
                continue
            for col in table_cfg.get("columns", []):
                # Heuristic: any column ending in "_id" in a broken source
                # table is treated as a broken FK column.
                if col.get("name", "").endswith("_id"):
                    col["nullable"] = True
                    col["null_ratio"] = 0.1  # 10% nulls to allow alignment
                    logger.debug(
                        "Marked broken FK column as nullable",
                        table=table_cfg["name"], column=col["name"],
                    )
        return new_config
