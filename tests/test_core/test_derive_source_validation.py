"""Reject absent explicit sources without treating legitimate NULL as a typo."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sqlseed import connect
from sqlseed.config.models import ColumnConfig
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.generators._protocol import ConfigurationError
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("source", ["soruce", ["source", "soruce"], ["absent", "source"], "SOURCE"])
def test_unknown_explicit_source_names_are_rejected(source: str | list[str]) -> None:
    specs = {name: GeneratorSpec(generator_name="integer") for name in ("source", "copied")}
    configs = [ColumnConfig(name="copied", derive_from=source, expression="value")]
    with pytest.raises(ConfigurationError, match="Column 'copied' derives from unknown source column"):
        ColumnDAG().build(specs, configs)


@pytest.mark.parametrize("generator", ["skip", "autoincrement", "integer"])
def test_existing_skipped_and_nullable_sources_are_not_unknown(generator: str) -> None:
    specs = {"source": GeneratorSpec(generator_name=generator), "copied": GeneratorSpec(generator_name="integer")}
    configs = [ColumnConfig(name="copied", derive_from="source", expression="value")]
    nodes = ColumnDAG().build(specs, configs)
    assert [node.name for node in nodes] == ["source", "copied"]
    assert nodes[1].derive_from_sources == ["source"]


def test_foreign_key_override_keeps_precedence_over_unused_derivation() -> None:
    specs = {"parent_id": GeneratorSpec(generator_name="foreign_key", params={"values": [7]})}
    configs = [ColumnConfig(name="parent_id", derive_from="unused_missing", expression="value")]
    nodes = ColumnDAG().build(specs, configs)
    assert nodes[0].is_derived is False
    assert nodes[0].derive_from_sources == []
    assert nodes[0].generator_spec.params == {"values": [7]}


def test_conditional_implicit_missing_reference_remains_lazy() -> None:
    specs = {name: GeneratorSpec(generator_name="integer") for name in ("source", "copied")}
    configs = [ColumnConfig(name="copied", derive_from="source", expression="value if True else row['absent']")]
    nodes = ColumnDAG().build(specs, configs)
    assert nodes[1].depends_on == ["source", "absent"]
    assert nodes[1].derive_from_sources == ["source"]


def test_exact_quoted_source_name_and_repeated_sources_are_valid() -> None:
    specs = {name: GeneratorSpec(generator_name="integer") for name in ("cost's value", "copied")}
    configs = [ColumnConfig(name="copied", derive_from=["cost's value", "cost's value"], expression="value[0]")]
    nodes = ColumnDAG().build(specs, configs)
    assert [node.name for node in nodes] == ["cost's value", "copied"]
    assert nodes[1].derive_from_sources == ["cost's value", "cost's value"]


@pytest.mark.parametrize("sources", ["soruce", ["source", "soruce"]])
def test_configured_preview_and_fill_reject_then_recover(tmp_path: Path, sources: str | list[str]) -> None:
    path = tmp_path / "sources.sqlite"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE samples (source INTEGER NOT NULL, copied INTEGER)")
        db.execute("INSERT INTO samples VALUES (99, 99)")
    config = [
        ColumnConfig(name="source", generator="integer", params={"min_value": 7, "max_value": 7}),
        ColumnConfig(name="copied", derive_from=sources, expression="value"),
    ]
    with connect(str(path), provider="base", optimize_pragma=False) as orchestrator:
        before = path.read_bytes()
        with pytest.raises(ConfigurationError, match=r"copied.*soruce"):
            orchestrator.preview_table("samples", count=3, seed=42, column_configs=config)
        assert path.read_bytes() == before
        with pytest.raises(ConfigurationError, match=r"copied.*soruce"):
            orchestrator.fill_table("samples", count=3, seed=42, column_configs=config, skip_ai=True)
        assert path.read_bytes() == before
        assert config[1].derive_from == sources
        config[1].derive_from = "source"
        preview = orchestrator.preview_table("samples", count=3, seed=42, column_configs=config)
        assert preview == [{"source": 7, "copied": 7}] * 3
        assert path.read_bytes() == before
        result = orchestrator.fill_table("samples", count=3, seed=42, column_configs=config, batch_size=2, skip_ai=True)
        assert_empty(result.errors, list)
        assert result.count == 3 and result.batch_count == 2
    with sqlite_connection(path) as db:
        assert db.execute("SELECT source, copied FROM samples ORDER BY rowid").fetchall() == [(99, 99)] + [(7, 7)] * 3
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
