"""Reflection keeps FK identity needed for bounded execution preflight.

PostgreSQL cases exercise SQLAlchemy metadata contracts, not a live server.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import Column, ForeignKeyConstraint, Integer, MetaData, Table

from sqlseed.core.relation import RelationResolver
from sqlseed.database._dialect import PostgresDialect
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


def test_real_sqlite_reflection_preserves_separate_fk_constraint_identity(tmp_path: Path) -> None:
    path = tmp_path / "groups.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE parents(a INTEGER,b INTEGER,PRIMARY KEY(a,b));"
            "CREATE TABLE other(id INTEGER PRIMARY KEY);"
            "CREATE TABLE children(a INTEGER,b INTEGER,other_id INTEGER REFERENCES other(id),"
            "FOREIGN KEY(a,b) REFERENCES parents(a,b));"
        )
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(path))
        fks = {fk.column: fk for fk in adapter.get_foreign_keys("children")}
        assert fks["a"].constraint_id == fks["b"].constraint_id
        assert fks["a"].constraint_id is not None
        assert fks["a"].constraint_id != fks["other_id"].constraint_id
        assert fks["a"].ref_schema is None
        RelationResolver(adapter).validate_generation_schema("children")


@pytest.mark.parametrize("width,schema", [(2, None), (1, "archive"), (1, None)])
def test_postgres_metadata_is_preserved_then_rejected_before_sampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int, schema: str | None
) -> None:
    metadata = MetaData()
    names = ["a", "b"][:width]
    parent = Table("parents", metadata, *(Column(name, Integer, primary_key=True) for name in names), schema=schema)
    child = Table(
        "children",
        metadata,
        *(Column(name, Integer) for name in names),
        ForeignKeyConstraint(names, [parent.c[name] for name in names], name="fk_parent"),
    )

    class MetadataInspector:
        def get_foreign_keys(self, table_name: str, **kwargs: object) -> list[dict[str, Any]]:
            assert table_name == child.name
            return [
                {
                    "name": constraint.name,
                    "constrained_columns": [element.parent.name for element in constraint.elements],
                    "referred_columns": [element.column.name for element in constraint.elements],
                    "referred_table": parent.name,
                    # PostgreSQL can hide a target schema present in search_path.
                    "referred_schema": parent.schema if kwargs.get("postgresql_ignore_search_path") else None,
                }
                for constraint in child.foreign_key_constraints
            ]

    with SQLAlchemyAdapter() as adapter:
        adapter.connect(str(tmp_path / "metadata_only.db"))
        adapter._dialect = PostgresDialect()
        monkeypatch.setattr(adapter, "_get_inspector", MetadataInspector)
        fks = adapter.get_foreign_keys("children")
        assert [fk.ref_column for fk in fks] == names
        assert all(fk.ref_schema == schema and fk.constraint_id == 0 for fk in fks)
        if width == 1 and schema is None:
            RelationResolver(adapter).validate_generation_schema("children")
            return
        reason = "schema-qualified foreign key" if schema else "PostgreSQL composite foreign key"
        with pytest.raises(ConfigurationError, match=rf"children.*{reason}.*not supported"):
            RelationResolver(adapter).validate_generation_schema("children")
