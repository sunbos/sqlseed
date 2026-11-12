"""Explicit association NULL handling uses target nullability."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError
from tests.test_core.test_association_refresh import _association_config, _association_database, _database_digest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("nullable", [True, False])
@pytest.mark.parametrize("generator", ["integer", "foreign_key_or_integer"])
def test_association_nullability_and_live_recovery(tmp_path: Path, nullable: bool, generator: str) -> None:
    path = tmp_path / "nullability.sqlite"
    declaration = "" if nullable else "NOT NULL"
    schema = (
        "CREATE TABLE parent(id INTEGER); INSERT INTO parent VALUES(101), (NULL);"
        f"CREATE TABLE child(id INTEGER PRIMARY KEY, department_id INTEGER {declaration});"
        "INSERT INTO child VALUES(1, 123);"
    )
    with _association_database(path, schema) as db:
        columns = {"department_id": {"generator": generator, "strategy": "coverage", "null_ratio": 0}}
        with DataOrchestrator.from_config(_association_config(path)) as live:
            for stage in range(3):
                if stage == 1:
                    db.execute("UPDATE parent SET id=NULL")
                elif stage == 2:
                    db.execute("INSERT INTO parent VALUES(202)")
                db.commit()
                source = db.execute("SELECT id FROM parent").fetchall()
                expected = {row[0] for row in source if nullable or row[0] is not None}
                before = db.execute("SELECT * FROM child ORDER BY id").fetchall()
                digest = _database_digest(path)
                if not expected:
                    with pytest.raises(ConfigurationError, match="no non-NULL source values"):
                        live.preview_table("child", count=6, columns=columns)
                    with pytest.raises(ConfigurationError, match="no non-NULL source values"):
                        live.fill_table("child", count=6, columns=columns, skip_ai=True)
                    assert _database_digest(path) == digest
                    continue
                preview = live.preview_table("child", count=6, seed=11, columns=columns)
                assert _database_digest(path) == digest
                assert {row["department_id"] for row in preview} == expected
                result = live.fill_table("child", count=6, batch_size=2, seed=11, columns=columns, skip_ai=True)
                assert result.count == 6 and not result.errors
                after = db.execute("SELECT * FROM child ORDER BY id").fetchall()
                assert after[: len(before)] == before
                assert [row[1] for row in after[len(before) :]] == [row["department_id"] for row in preview]
                assert db.execute("SELECT id FROM parent").fetchall() == source
                assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
