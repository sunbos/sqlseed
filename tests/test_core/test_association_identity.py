"""Association table identities across SQLite aliases and exact-name dialects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from sqlseed.config.models import ColumnAssociation, GeneratorConfig
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.relation import RelationResolver
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


def _config(db_path: Path, source: str, target: str) -> GeneratorConfig:
    return GeneratorConfig(
        db_path=str(db_path),
        provider="base",
        optimize_pragma=False,
        associations=[
            ColumnAssociation(column_name="token", source_table=source, source_column="code", target_tables=[target])
        ],
    )


@pytest.mark.parametrize("generator", ["integer", "foreign_key_or_integer"])
@pytest.mark.parametrize(
    "source,target", [("Parent", "Child"), ("PARENT", "Child"), ("Parent", "CHILD"), ("PARENT", "CHILD")]
)
def test_ascii_association_aliases_preserve_values_and_config(
    tmp_path: Path, generator: str, source: str, target: str
) -> None:
    db_path = tmp_path / "aliases.sqlite"
    with sqlite_connection(db_path) as conn:
        conn.executescript(
            "CREATE TABLE Parent(code INTEGER NOT NULL);"
            "INSERT INTO Parent VALUES(701);"
            "CREATE TABLE Child(token INTEGER NOT NULL);"
        )
    config = _config(db_path, source, target)
    original = config.model_dump()
    columns = {"token": {"generator": generator, "min_value": -9, "max_value": -9}}
    with DataOrchestrator.from_config(config) as live:
        assert live.get_topological_table_order(["Child", "Parent"]) == ["Parent", "Child"]
        assert live.get_topological_table_order(["CHILD", "PARENT"]) == ["PARENT", "CHILD"]
        assert live.preview_table("CHILD", count=2, seed=7, columns=columns) == [{"token": 701}] * 2
        result = live.fill_table("CHILD", count=2, seed=7, columns=columns, skip_ai=True)
        assert not result.errors and result.count == 2
    with sqlite_connection(db_path) as conn:
        assert conn.execute("SELECT token FROM Child").fetchall() == [(701,), (701,)]
    assert config.model_dump() == original


def test_sqlite_non_ascii_targets_stay_distinct(tmp_path: Path) -> None:
    db_path = tmp_path / "unicode-target.sqlite"
    with sqlite_connection(db_path) as conn:
        conn.executescript(
            "CREATE TABLE Parent(code INTEGER NOT NULL); INSERT INTO Parent VALUES(701);"
            'CREATE TABLE "Ä"(token INTEGER NOT NULL); CREATE TABLE "ä"(token INTEGER NOT NULL);'
        )
    with DataOrchestrator.from_config(_config(db_path, "Parent", "Ä")) as live:
        columns = {"token": {"generator": "integer", "min_value": -9, "max_value": -9}}
        assert live.preview_table("Ä", count=1, columns=columns) == [{"token": 701}]
        assert live.preview_table("ä", count=1, columns=columns) == [{"token": -9}]
        assert live.get_topological_table_order(["ä", "Parent", "Ä"]) == ["ä", "Parent", "Ä"]


def test_sqlite_non_ascii_sources_stay_distinct(tmp_path: Path) -> None:
    db_path = tmp_path / "unicode-source.sqlite"
    with sqlite_connection(db_path) as conn:
        conn.executescript(
            'CREATE TABLE "Ä"(code INTEGER NOT NULL); INSERT INTO "Ä" VALUES(701);'
            'CREATE TABLE "ä"(code INTEGER NOT NULL); INSERT INTO "ä" VALUES(902);'
            "CREATE TABLE Child(token INTEGER NOT NULL);"
        )
    for source, expected in (("Ä", 701), ("ä", 902)):
        with DataOrchestrator.from_config(_config(db_path, source, "Child")) as live:
            columns = {"token": {"generator": "integer", "min_value": -9, "max_value": -9}}
            assert live.preview_table("Child", count=1, columns=columns) == [{"token": expected}]
            other = "ä" if source == "Ä" else "Ä"
            assert live.get_topological_table_order(["Child", other, source]) == [other, source, "Child"]
            assert live.get_topological_table_order(["Child", other]) == ["Child", other]


def test_sqlite_self_source_alias_is_not_dependency(tmp_path: Path) -> None:
    db_path = tmp_path / "self.sqlite"
    with sqlite_connection(db_path) as conn:
        conn.execute("CREATE TABLE Child(code INTEGER NOT NULL, token INTEGER NOT NULL)")
    with DataOrchestrator.from_config(_config(db_path, "CHILD", "child")) as live:
        assert live._relation.get_dependencies("Child") == set()


def test_postgresql_association_names_remain_exact() -> None:
    """Dialect contract only: no PostgreSQL connection or database behavior is simulated."""
    resolver = RelationResolver(SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    resolver._fk_cache = {"Child": [], "Parent": [], "CHILD": [], "PARENT": []}
    resolver.set_associations(
        [ColumnAssociation(column_name="token", source_table="Parent", source_column="code", target_tables=["Child"])]
    )
    assert resolver.get_dependencies("Child") == {"Parent"}
    assert resolver.get_dependencies("CHILD") == set()
    assert resolver.topological_sort(["Child", "Parent"]) == ["Parent", "Child"]
    assert resolver.topological_sort(["Child", "PARENT"]) == ["Child", "PARENT"]
    spec = GeneratorSpec(generator_name="integer", params={"min_value": -9, "max_value": -9})
    assert resolver.apply_associations("CHILD", {"token": spec}) == {"token": spec}
