"""Shared real-database roundtrip checks for self-reference regressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty

if TYPE_CHECKING:
    from pathlib import Path


def fill_self_reference_rows(path: Path, *, count: int, seed: int) -> list[dict[str, Any]]:
    """Fill a nodes table and return ordered rows after checking write integrity."""
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("nodes", count=count, seed=seed, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == count
        rows = orch.query("SELECT * FROM nodes ORDER BY id")
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)
        return rows
