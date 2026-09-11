"""Explicit generators inherit only compatible name-rule parameter defaults."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pytest

from sqlseed.config.models import ColumnConfig
from sqlseed.core.mapper import ColumnMapper
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError
from tests.conftest import make_column_info

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("column", "generator", "params", "expected"),
    [
        ("bio", "sentence", {}, {}),
        ("sku", "sentence", {}, {}),
        ("order_code", "sentence", {}, {}),
        ("sku", "text", {}, {"min_length": 6, "max_length": 12}),
        ("bio", "string", {"min_length": 60}, {"min_length": 60, "max_length": 200}),
        ("sku", "string", {"min_length": 8}, {"min_length": 8, "max_length": 12, "charset": "alphanumeric"}),
    ],
)
def test_explicit_generator_receives_compatible_defaults(
    column: str, generator: str, params: dict[str, Any], expected: dict[str, Any]
) -> None:
    config = ColumnConfig(name=column, generator=generator, params=params)
    before = config.model_dump()
    spec = ColumnMapper().map_column(make_column_info(column, "TEXT", nullable=False), config)
    assert spec.generator_name == generator
    assert spec.params == expected
    assert config.model_dump() == before


@pytest.mark.parametrize("provider", ["faker", "mimesis"])
def test_explicit_sentence_and_text_preview_with_real_provider(tmp_path: Path, provider: str) -> None:
    if provider == "mimesis":
        pytest.importorskip("mimesis")
    db_path = tmp_path / "generator-contract.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE users (bio TEXT NOT NULL, sku TEXT NOT NULL)")
    with DataOrchestrator(str(db_path), provider_name=provider) as orch:
        rows = orch.preview_table(
            "users",
            count=5,
            seed=31,
            column_configs=[ColumnConfig(name="bio", generator="sentence"), ColumnConfig(name="sku", generator="text")],
        )
    assert len(rows) == 5
    assert all(isinstance(row["bio"], str) and row["bio"] for row in rows)
    assert all(isinstance(row["sku"], str) and 6 <= len(row["sku"]) <= 12 for row in rows)
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (0,)


@pytest.mark.parametrize("provider", ["faker", "mimesis"])
def test_explicit_invalid_sentence_params_are_still_rejected(tmp_path: Path, provider: str) -> None:
    if provider == "mimesis":
        pytest.importorskip("mimesis")
    db_path = tmp_path / "invalid-generator-contract.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE users (bio TEXT NOT NULL)")
    with (
        DataOrchestrator(str(db_path), provider_name=provider) as orch,
        pytest.raises(ConfigurationError, match="unexpected keyword argument 'min_length'"),
    ):
        orch.preview_table(
            "users",
            count=1,
            column_configs=[ColumnConfig(name="bio", generator="sentence", params={"min_length": 5})],
        )
