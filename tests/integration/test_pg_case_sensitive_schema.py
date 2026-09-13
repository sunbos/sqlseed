"""Ambiguous quoted PostgreSQL identifiers fail before any table is changed."""

from __future__ import annotations

import json
from contextlib import ExitStack
from functools import partial
from typing import TYPE_CHECKING

import pytest

from sqlseed import fill_from_config
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode", ["append", "clear", "preview", "config"])
def test_pg_case_colliding_columns_are_rejected_before_writes(pg_url: str, tmp_path: Path, mode: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(pg_url)
        adapter.execute("CREATE TABLE case_guard_first(value INTEGER)").close()
        adapter.execute("INSERT INTO case_guard_first VALUES(777)").close()
        adapter.execute(
            'CREATE TABLE case_guard_items("A" INTEGER NOT NULL CHECK("A"=1), a INTEGER NOT NULL CHECK(a=2))'
        ).close()
        adapter.execute("INSERT INTO case_guard_items VALUES(1,2)").close()
        try:
            with ExitStack() as resources:
                if mode == "config":
                    path = tmp_path / "case_guard.json"
                    path.write_text(
                        json.dumps(
                            {
                                "url": pg_url,
                                "provider": "base",
                                "tables": [
                                    {"name": "case_guard_first", "count": 1},
                                    {"name": "case_guard_items", "count": 1},
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    operation = partial(fill_from_config, str(path), clear_before=True)
                else:
                    orch = resources.enter_context(
                        DataOrchestrator(pg_url, provider_name="base", optimize_pragma=False)
                    )
                    if mode == "preview":
                        operation = partial(orch.preview_table, "case_guard_items", count=1, seed=42)
                    else:
                        operation = partial(
                            orch.fill_table, "case_guard_items", count=1, clear_before=mode == "clear", skip_ai=True
                        )
                with pytest.raises(ConfigurationError, match=r"ASCII case.*not supported"):
                    operation()
            assert adapter.get_sample_rows("case_guard_first") == [{"value": 777}]
            assert adapter.get_sample_rows("case_guard_items") == [{"A": 1, "a": 2}]
        finally:
            adapter.execute("DROP TABLE case_guard_items").close()
            adapter.execute("DROP TABLE case_guard_first").close()
