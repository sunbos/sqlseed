"""Initialization failures must not leave a half-connected orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.plugins.hookspecs import hookimpl

if TYPE_CHECKING:
    from pathlib import Path

    from sqlseed.core.mapper import ColumnMapper


def test_failed_plugin_initialization_closes_connection_and_allows_retry(tmp_path: Path) -> None:
    class FailingPlugin:
        @hookimpl
        def sqlseed_register_column_mappers(self, mapper: ColumnMapper) -> None:
            raise RuntimeError("plugin initialization failed")

    orch = DataOrchestrator(str(tmp_path / "initialization.db"), provider_name="base")
    plugin = FailingPlugin()
    orch._plugins.register(plugin)
    try:
        with pytest.raises(RuntimeError, match="plugin initialization failed"), orch:
            pass
        with pytest.raises(RuntimeError, match="not connected"):
            orch.database_adapter.get_table_names()
        orch._plugins.unregister(plugin)
        with orch:
            orch.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)").close()
            result = orch.fill_table("items", count=3, skip_ai=True)
            assert not result.errors
            assert result.count == orch.get_row_count("items") == 3
    finally:
        orch.close()
