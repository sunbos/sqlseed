"""File configurations reject cyclic aliases before database side effects."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from sqlseed import fill_from_config, load_config
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "parameters",
    [
        "schema: &node {type: object, properties: {self: *node}}",
        "schema: &node {type: array, items: *node}",
        "schema: &node {type: object, properties: {children: {type: array, items: *node}}}",
        "choices: &items [*items]",
        "choices: &items !!pairs [{self: *items}]",
    ],
    ids=["object", "array", "indirect", "list", "pairs-tuple"],
)
def test_load_config_rejects_cyclic_yaml_aliases(tmp_path: Path, parameters: str) -> None:
    database = tmp_path / "unused.db"
    config = tmp_path / "cycle.yaml"
    config.write_text(
        f"db_path: {json.dumps(str(database))}\n"
        "tables:\n  - name: items\n    columns:\n"
        "      - name: payload\n        generator: json\n"
        f"        params:\n          {parameters}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cyclic YAML alias"):
        load_config(str(config))

    assert not database.exists()


def test_file_config_cycle_is_rejected_before_any_table_is_changed(tmp_path: Path) -> None:
    database = tmp_path / "multi.db"
    with sqlite_connection(database) as connection:
        connection.executescript(
            "CREATE TABLE a_good (payload TEXT NOT NULL);"
            "CREATE TABLE z_bad (payload TEXT NOT NULL);"
            "INSERT INTO a_good VALUES ('first marker');"
            "INSERT INTO z_bad VALUES ('second marker');"
        )
    original = database.read_bytes()
    cyclic: dict[str, Any] = {"type": "object"}
    cyclic["properties"] = {"self": cyclic}
    document = {
        "db_path": str(database),
        "provider": "base",
        "tables": [
            {
                "name": name,
                "count": 2,
                "columns": [{"name": "payload", "generator": "json", "params": {"schema": schema}}],
            }
            for name, schema in (("a_good", {"type": "boolean"}), ("z_bad", cyclic))
        ],
    }
    config = tmp_path / "generate.yaml"
    config.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="cyclic YAML alias"):
        fill_from_config(str(config), clear_before=True)

    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT payload FROM a_good").fetchall() == [("first marker",)]
        assert connection.execute("SELECT payload FROM z_bad").fetchall() == [("second marker",)]
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert database.read_bytes() == original


def test_shared_schema_aliases_remain_valid_for_generation(tmp_path: Path) -> None:
    database = tmp_path / "shared.db"
    with sqlite_connection(database) as connection:
        connection.execute("CREATE TABLE items (payload TEXT NOT NULL)")
        connection.execute("INSERT INTO items VALUES ('marker')")
    config = tmp_path / "shared.yaml"
    config.write_text(
        f"db_path: {json.dumps(str(database))}\nprovider: base\n"
        "tables:\n  - name: items\n    count: 2\n    columns:\n"
        "      - name: payload\n        generator: json\n        params:\n"
        "          schema:\n            type: object\n            properties:\n"
        "              left: &leaf {type: boolean}\n              right: *leaf\n",
        encoding="utf-8",
    )
    properties = load_config(str(config)).tables[0].columns[0].params["schema"]["properties"]
    assert properties["left"] is properties["right"]

    results = fill_from_config(str(config))

    assert results[0].count == 2
    assert not results[0].errors
    with sqlite_connection(database) as connection:
        rows = connection.execute("SELECT payload FROM items ORDER BY rowid").fetchall()
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert rows[0] == ("marker",)
    assert len(rows) == 3
    for (value,) in rows[1:]:
        parsed = json.loads(value)
        assert set(parsed) == {"left", "right"}
        assert all(isinstance(item, bool) for item in parsed.values())


def test_shared_alias_dag_is_not_expanded_or_rejected(tmp_path: Path) -> None:
    shared: Any = {"leaf": True}
    for _ in range(35):
        shared = [shared, shared]
    config = tmp_path / "shared-dag.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "db_path": str(tmp_path / "unused.db"),
                "tables": [{"name": "items", "columns": [{"name": "payload", "params": {"graph": shared}}]}],
            }
        ),
        encoding="utf-8",
    )

    actual = load_config(str(config)).tables[0].columns[0].params["graph"]

    for _ in range(35):
        assert actual[0] is actual[1]
        actual = actual[0]
    assert actual == {"leaf": True}


def test_acyclic_yaml_merges_match_equivalent_json(tmp_path: Path) -> None:
    config = tmp_path / "merge.yaml"
    config.write_text(
        f"db_path: {json.dumps(str(tmp_path / 'unused.db'))}\n"
        "defaults: &defaults {count: 2, batch_size: 1}\n"
        "tables:\n  - <<: *defaults\n    name: items\n",
        encoding="utf-8",
    )
    expected = load_config(str(config))
    plain = tmp_path / "equivalent.json"
    plain.write_text(expected.model_dump_json(), encoding="utf-8")

    assert load_config(str(plain)) == expected
    assert expected.tables[0].count == 2
    assert expected.tables[0].batch_size == 1


def test_self_merge_resolved_to_acyclic_config_remains_valid(tmp_path: Path) -> None:
    database = tmp_path / "unused.db"
    config = tmp_path / "self-merge.yaml"
    config.write_text(
        f"db_path: {json.dumps(str(database))}\n"
        "tables:\n"
        "  - &table\n"
        "    <<: *table\n"
        "    name: items\n"
        "    count: 2\n"
        "    batch_size: 1\n",
        encoding="utf-8",
    )

    actual = load_config(str(config))

    assert actual.tables[0].name == "items"
    assert actual.tables[0].count == 2
    assert actual.tables[0].batch_size == 1
    assert not database.exists()


@pytest.mark.parametrize(
    "body",
    [
        "metadata: &meta {self: *meta}\ntables: [{name: items}]\n",
        "tables: [{name: items, metadata: &meta {self: *meta}}]\n",
        "tables:\n  - name: items\n    columns:\n"
        "      - name: payload\n        params:\n          native_params: &native {self: *native}\n",
    ],
    ids=["top-level-metadata", "table-metadata", "native-params"],
)
def test_cycles_in_metadata_and_native_params_are_rejected(tmp_path: Path, body: str) -> None:
    database = tmp_path / "unused.db"
    config = tmp_path / "metadata-cycle.yaml"
    config.write_text(f"db_path: {json.dumps(str(database))}\n{body}", encoding="utf-8")

    with pytest.raises(ValueError, match="cyclic YAML alias"):
        load_config(str(config))

    assert not database.exists()
