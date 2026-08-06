"""Reproduce the real defects surfaced by randomized roundtrip.

Three separate cases:
  1. UNIQUE INTEGER column (age) — mapper integer, UniqueAdjuster path
  2. UNIQUE INTEGER column (score) — mapper maps score->float (type drift)
  3. role TEXT CHECK IN('admin','user','guest') — choice generator
  4. UNIQUE qty INTEGER
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import sqlseed

OUT = Path(tempfile.mkdtemp(prefix="repro2_"))


def run_case(name: str, ddl: str, count: int, seed: int = 42) -> None:
    db = OUT / f"{name}.db"
    con = sqlite3.connect(db)
    con.execute(ddl)
    con.commit()
    con.close()
    try:
        with sqlseed.connect(str(db)) as orch:
            for t in orch.get_topological_table_order(orch.get_table_names()):
                res = orch.fill_table(t, count=count, seed=seed)
        errs = res.errors if hasattr(res, "errors") else None
        con = sqlite3.connect(db)
        n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        con.close()
        print(f"[OK]   {name}: rows={n} errors={errs}")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {name}: {type(e).__name__}: {str(e)[:180]}")


run_case("age_u", 'CREATE TABLE age_u (id INTEGER PRIMARY KEY, age INTEGER UNIQUE NOT NULL)', 27)
run_case("score_u", 'CREATE TABLE score_u (id INTEGER PRIMARY KEY, score INTEGER UNIQUE NOT NULL)', 27)
run_case("qty_u", 'CREATE TABLE qty_u (id INTEGER PRIMARY KEY, qty INTEGER UNIQUE NOT NULL)', 27)
run_case("role_c", "CREATE TABLE role_c (id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK (role IN ('admin','user','guest')))", 27)
run_case("year_u", 'CREATE TABLE year_u (id INTEGER PRIMARY KEY, year INTEGER UNIQUE NOT NULL)', 27)