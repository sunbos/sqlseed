"""Deferred self references preserve row identity and database uniqueness."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed.core.orchestrator import DataOrchestrator
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("check", ["", ", CHECK(parent_code != code)"])
def test_self_reference_locates_complete_composite_primary_key(tmp_path: Path, check: str) -> None:
    path = tmp_path / "composite_identity.db"
    with sqlite_connection(path) as db:
        db.execute(
            "CREATE TABLE nodes (tenant INTEGER NOT NULL, slot INTEGER NOT NULL, "
            "code INTEGER NOT NULL UNIQUE, parent_code INTEGER REFERENCES nodes(code), "
            f"PRIMARY KEY(tenant, slot){check})"
        )
    snapshots = []
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        for _ in range(2):
            result = orch.fill_table(
                "nodes",
                count=20,
                batch_size=5,
                clear_before=True,
                columns={
                    "tenant": {"generator": "integer", "params": {"min_value": 1, "max_value": 1}},
                    "slot": {"generator": "integer", "params": {"min_value": 1, "max_value": 100000}},
                    "code": {"generator": "integer", "params": {"min_value": 100, "max_value": 100000}},
                },
                seed=42,
                skip_ai=True,
            )
            assert_empty(result.errors, list)
            assert result.count == 20
            assert result.batch_count == 4
            rows = orch.query("SELECT * FROM nodes ORDER BY tenant, slot")
            snapshots.append(rows)
            assert rows[0]["parent_code"] is None
            preceding_codes: set[int] = set()
            for row in rows:
                if row["parent_code"] is not None:
                    assert row["parent_code"] in preceding_codes
                preceding_codes.add(row["code"])
            assert any(row["parent_code"] is not None for row in rows)
            assert_empty(orch.query("PRAGMA foreign_key_check"), list)
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize(
    ("constraint", "index_sql"),
    [
        (", UNIQUE(parent_id)", ""),
        ("", "CREATE UNIQUE INDEX one_child ON nodes(parent_id);"),
        (", UNIQUE(bucket, parent_id)", ""),
    ],
    ids=["column_unique", "unique_index", "composite_unique"],
)
def test_self_reference_respects_single_and_composite_unique(tmp_path: Path, constraint: str, index_sql: str) -> None:
    path = tmp_path / "unique_parent.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, bucket INTEGER NOT NULL, "
            f"parent_id INTEGER REFERENCES nodes(id){constraint});{index_sql}"
        )
    snapshots = []
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        for _ in range(2):
            result = orch.fill_table(
                "nodes",
                count=40,
                batch_size=10,
                clear_before=True,
                columns={"bucket": {"generator": "choice", "params": {"choices": [1, 2]}}},
                seed=42,
                skip_ai=True,
            )
            assert_empty(result.errors, list)
            assert result.count == 40
            rows = orch.query("SELECT * FROM nodes ORDER BY id")
            snapshots.append(rows)
            parents = [row for row in rows if row["parent_id"] is not None]
            assert len(parents) > 15
            assert all(row["parent_id"] < row["id"] for row in parents)
            if "bucket, parent_id" in constraint:
                assert len({(row["bucket"], row["parent_id"]) for row in parents}) == len(parents)
                assert len({row["parent_id"] for row in parents}) < len(parents)
            else:
                assert len({row["parent_id"] for row in parents}) == len(parents)
            assert_empty(orch.query("PRAGMA foreign_key_check"), list)
    assert snapshots[0] == snapshots[1]


def test_self_reference_unique_uses_adjusted_conditional_value(tmp_path: Path) -> None:
    path = tmp_path / "conditional_unique.db"
    with sqlite_connection(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id), "
            "kind INTEGER NOT NULL, UNIQUE(parent_id, kind), CHECK(kind IN (0, 1)), "
            "CHECK(kind = 0 OR parent_id IS NOT NULL), CHECK(kind != 0 OR parent_id IS NULL))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("nodes", count=30, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 30
        rows = orch.query("SELECT * FROM nodes ORDER BY id")
        parents = [row["parent_id"] for row in rows if row["parent_id"] is not None]
        assert len(parents) > 10
        assert len(set(parents)) == len(parents)
        assert all(row["kind"] == int(row["parent_id"] is not None) for row in rows)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


@pytest.mark.parametrize("nullable_bucket", [False, True])
def test_self_reference_composite_unique_obeys_collation_and_null_semantics(
    tmp_path: Path, nullable_bucket: bool
) -> None:
    path = tmp_path / "collated_unique.db"
    with sqlite_connection(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, bucket TEXT COLLATE NOCASE, "
            "parent_id INTEGER REFERENCES nodes(id), UNIQUE(bucket, parent_id))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "nodes",
            count=30,
            columns={
                "bucket": {
                    "generator": "choice",
                    "params": {"choices": ["A", "a"]},
                    "null_ratio": 1.0 if nullable_bucket else 0.0,
                }
            },
            seed=42,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        rows = orch.query("SELECT * FROM nodes ORDER BY id")
        parents = [row["parent_id"] for row in rows if row["parent_id"] is not None]
        assert len(parents) > 10
        if nullable_bucket:
            assert all(row["bucket"] is None for row in rows)
            assert len(set(parents)) < len(parents)
        else:
            assert {row["bucket"] for row in rows} == {"A", "a"}
            assert len(set(parents)) == len(parents)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_self_reference_nullable_composite_primary_key_uses_unique_target_identity(tmp_path: Path) -> None:
    path = tmp_path / "nullable_identity.db"
    with sqlite_connection(path) as db:
        db.execute(
            'CREATE TABLE nodes ("tenant key" INTEGER, "slot key" INTEGER NOT NULL, '
            "code INTEGER NOT NULL UNIQUE, parent_code INTEGER REFERENCES nodes(code), "
            'PRIMARY KEY("tenant key", "slot key"))'
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "nodes",
            count=20,
            columns={
                "tenant key": {"generator": "integer", "null_ratio": 1.0},
                "slot key": {"generator": "integer", "params": {"min_value": 1, "max_value": 1}},
                "code": {"generator": "integer", "params": {"min_value": 100, "max_value": 100000}},
            },
            seed=42,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 20
        rows = orch.query("SELECT * FROM nodes ORDER BY code")
        assert all(row["tenant key"] is None and row["slot key"] == 1 for row in rows)
        assert rows[0]["parent_code"] is None
        assert any(row["parent_code"] is not None for row in rows)
        assert all(row["parent_code"] is None or row["parent_code"] < row["code"] for row in rows)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_self_reference_exhausted_unique_targets_retain_null_roots(tmp_path: Path) -> None:
    path = tmp_path / "exhausted_targets.db"
    with sqlite_connection(path) as db:
        db.execute(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, code INTEGER UNIQUE CHECK(code BETWEEN 1 AND 2), "
            "parent_code INTEGER UNIQUE REFERENCES nodes(code))"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "nodes",
            count=30,
            columns={
                "code": {
                    "generator": "integer",
                    "params": {"min_value": 1, "max_value": 2},
                    "null_ratio": 0.75,
                }
            },
            seed=42,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 30
        rows = orch.query("SELECT * FROM nodes ORDER BY id")
        targets = {row["code"] for row in rows if row["code"] is not None}
        parents = [row["parent_code"] for row in rows if row["parent_code"] is not None]
        assert len(targets) == 2
        assert len(parents) == len(set(parents)) == 2
        assert set(parents) == targets
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_self_reference_update_failure_preserves_committed_batches(tmp_path: Path) -> None:
    path = tmp_path / "post_fill_failure.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES nodes(id));"
            "CREATE TRIGGER reject_late_parents BEFORE UPDATE ON nodes "
            "WHEN NEW.id > 8 AND NEW.parent_id IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT, 'late parent rejected'); END;"
        )
    with DataOrchestrator(str(path), provider_name="base") as orch:
        result = orch.fill_table("nodes", count=20, batch_size=5, seed=42, skip_ai=True)
        assert result.count == 20
        assert result.batch_count == 4
        assert len(result.errors) == 1
        assert "late parent rejected" in result.errors[0]
        assert orch.get_row_count("nodes") == 20
        assert orch.query("SELECT id FROM nodes WHERE id <= 8 AND parent_id IS NOT NULL")
        assert_empty(orch.query("SELECT id FROM nodes WHERE id > 8 AND parent_id IS NOT NULL"), list)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


def test_self_reference_unique_parent_sampling_keeps_hierarchy_density(tmp_path: Path) -> None:
    path = tmp_path / "unique_density.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, parent_id INTEGER UNIQUE REFERENCES nodes(id))")
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table("nodes", count=1000, batch_size=100, seed=42, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 1000
        assert result.batch_count == 10
        summary = orch.query(
            "SELECT COUNT(parent_id) AS linked, COUNT(DISTINCT parent_id) AS parents, "
            "SUM(CASE WHEN parent_id >= id THEN 1 ELSE 0 END) AS invalid FROM nodes"
        )[0]
        # A dense old prefix must not defeat the 70% selection policy when
        # every preceding row offers a distinct, valid parent candidate.
        assert 650 <= summary["linked"] <= 800
        assert summary["parents"] == summary["linked"]
        assert summary["invalid"] == 0
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)


@pytest.mark.parametrize("index_columns", ["parent_code COLLATE NOCASE", "bucket, parent_code COLLATE NOCASE"])
def test_self_reference_unique_index_collation_overrides_column_collation(tmp_path: Path, index_columns: str) -> None:
    path = tmp_path / "index_collation.db"
    with sqlite_connection(path) as db:
        db.executescript(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY, bucket INTEGER NOT NULL DEFAULT 1, "
            "code TEXT NOT NULL UNIQUE, parent_code TEXT REFERENCES nodes(code));"
            "CREATE UNIQUE INDEX binary_children ON nodes(parent_code COLLATE BINARY);"
            f"CREATE UNIQUE INDEX nocase_children ON nodes({index_columns});"
        )
    with DataOrchestrator(str(path), provider_name="base", optimize_pragma=False) as orch:
        result = orch.fill_table(
            "nodes",
            count=6,
            columns={"code": {"generator": "choice", "params": {"choices": ["A", "a", "B", "b", "C", "c"]}}},
            seed=1,
            skip_ai=True,
        )
        assert_empty(result.errors, list)
        assert result.count == 6
        parents = orch.query("SELECT parent_code FROM nodes WHERE parent_code IS NOT NULL")
        assert len(parents) >= 2
        assert len({row["parent_code"].lower() for row in parents}) == len(parents)
        assert_empty(orch.query("PRAGMA foreign_key_check"), list)
