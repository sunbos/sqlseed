"""Recover an unavailable explicit source within one live orchestrator."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError
from tests.test_core.test_association_refresh import _association_config, _database_digest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("generator", ["integer", "foreign_key_or_integer"])
@pytest.mark.parametrize("source_state", ["empty", "missing"])
def test_unavailable_source_recovers_in_same_live_orchestrator(
    tmp_path: Path, source_state: str, generator: str
) -> None:
    db_path = tmp_path / "recovery.sqlite"
    audit = {"source_state": source_state, "generator": generator, "refusals": [], "stages": []}
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE unrelated(department_id INTEGER PRIMARY KEY);
            INSERT INTO unrelated VALUES(9001);
            CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL);
            INSERT INTO child VALUES(1, 123);
            CREATE TABLE sentinel(value TEXT);
            INSERT INTO sentinel VALUES('original');
            """
        )
        if source_state == "empty":
            conn.execute("CREATE TABLE source(id INTEGER PRIMARY KEY)")
        conn.commit()
        columns = {"department_id": {"generator": generator, "strategy": "coverage", "null_ratio": 0}}
        with DataOrchestrator.from_config(_association_config(db_path, source_table="source")) as live:
            result = live.fill_table("unrelated", count=1, seed=20, skip_ai=True)
            assert result.count == 1 and not result.errors
            assert live._shared_pool.get("department_id")
            before_dump = list(conn.iterdump())
            digest = _database_digest(db_path)
            for api in ("preview", "fill"):
                with pytest.raises(ConfigurationError, match="has no readable source values") as raised:
                    if api == "preview":
                        live.preview_table("child", count=12, seed=30, columns=columns)
                    else:
                        live.fill_table("child", count=12, seed=30, columns=columns, skip_ai=True)
                assert _database_digest(db_path) == digest
                assert list(conn.iterdump()) == before_dump
                audit["refusals"].append({"api": api, "error": str(raised.value), "sha256": digest})

            # Only add synthetic fixtures, never clear a table or replace the orchestrator.
            if source_state == "missing":
                conn.execute("CREATE TABLE source(id INTEGER PRIMARY KEY)")
            conn.executemany("INSERT INTO source VALUES(?)", [(101,), (102,)])
            conn.commit()
            unrelated = conn.execute("SELECT * FROM unrelated ORDER BY department_id").fetchall()
            for stage in range(3):
                if stage:
                    conn.execute("INSERT INTO source VALUES(?)", (102 + stage,))
                    conn.commit()
                expected = {row[0] for row in conn.execute("SELECT id FROM source")}
                before = conn.execute("SELECT * FROM child ORDER BY id").fetchall()
                digest = _database_digest(db_path)
                preview = live.preview_table("child", count=12, seed=30 + stage, columns=columns)
                assert _database_digest(db_path) == digest
                replay = live.preview_table("child", count=12, seed=30 + stage, columns=columns)
                assert replay == preview
                assert _database_digest(db_path) == digest
                values = [row["department_id"] for row in preview]
                assert set(values) == expected
                result = live.fill_table(
                    "child", count=12, batch_size=5, seed=30 + stage, columns=columns, skip_ai=True
                )
                assert result.count == 12 and not result.errors
                after = conn.execute("SELECT * FROM child ORDER BY id").fetchall()
                assert after[: len(before)] == before
                assert [row[1] for row in after[len(before) :]] == values
                for start in range(0, 12, len(expected)):
                    assert set(values[start : start + len(expected)]) == expected
                # The historical child value 123 is deliberately outside the association.
                assert after[0] == (1, 123)
                assert conn.execute("SELECT * FROM sentinel").fetchall() == [("original",)]
                assert conn.execute("SELECT * FROM unrelated ORDER BY department_id").fetchall() == unrelated
                assert conn.execute("PRAGMA foreign_key_list(child)").fetchall() == []
                assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
                audit["stages"].append(
                    {"source": sorted(expected), "preview": values, "rows": after, "integrity_check": "ok"}
                )
        assert conn.execute("SELECT COUNT(*) FROM child").fetchone() == (37,)
    audit["final_sha256"] = _database_digest(db_path)
    (tmp_path / "sqlite-results.json").write_text(json.dumps(audit, indent=2) + "\n")
