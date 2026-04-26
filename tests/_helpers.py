from __future__ import annotations

import sqlite3
from typing import Any

import yaml

import sqlseed


def assert_fk_integrity(db_path: str, fk_query: str, ref_query: str) -> None:
    conn = sqlite3.connect(db_path)
    fk_values = {r[0] for r in conn.execute(fk_query).fetchall() if r[0] is not None}
    ref_values = {r[0] for r in conn.execute(ref_query).fetchall()}
    conn.close()
    assert fk_values.issubset(ref_values)


def fill_from_config_and_verify_fk(
    db_path: str,
    config_data: dict[str, Any],
    config_dir: str,
    fk_query: str,
    ref_query: str,
) -> list[Any]:
    config_path = str(config_dir) + "/config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    results = sqlseed.fill_from_config(config_path)
    assert_fk_integrity(db_path, fk_query, ref_query)
    return results
