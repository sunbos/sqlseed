"""Reproduce the two known cross-layer defects (pre-fix confirmation).

Defect A: ``coerce_float_to_int`` emits ``random_int`` — an *expression*
function, not a core generator (GENERATOR_MAP) — so the repaired config
crashes the fill with UnknownGeneratorError. Companion gap: ``random_float``
on REAL/NUMERIC columns and ``random_int`` on INT columns are COMPATIBLE in
the builtin matrix, so the validator stays silent and the fill crashes too.

Defect B: a nullable UNIQUE column (not PK, no DEFAULT) falls through to the
mapper's DEFAULT-skip level and every row is silently filled with NULL.
SQLite allows multiple NULLs under UNIQUE, so nothing crashes — but the
column is uselessly empty.

Exit code 0 iff BOTH defects reproduce (i.e. the bugs exist).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

OUT_DIR = Path(tempfile.mkdtemp(prefix="sqlseed_repro_"))


def defect_a() -> bool:
    """random_float/random_int on numeric columns -> crash after/without repair."""
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.repair.pipeline import RepairPipeline
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    db = OUT_DIR / "defect_a.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE m (id INTEGER PRIMARY KEY, qty INT, price REAL, amount NUMERIC)")
    con.commit()
    con.close()

    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    snapshot = SchemaSnapshot(db_path=str(db))
    cfg = {
        "tables": [
            {
                "name": "m",
                "count": 10,
                "columns": [
                    {"name": "qty", "generator": "random_float", "params": {"min_value": 0, "max_value": 99}},
                    {"name": "price", "generator": "random_float", "params": {"min_value": 0, "max_value": 99}},
                    {"name": "amount", "generator": "random_int", "params": {"min_value": 0, "max_value": 99}},
                ],
            }
        ]
    }
    v = FastValidator(resolver, db_path=str(db)).validate(cfg, snapshot)
    flagged = {(x.columns[0], x.fix_hint) for x in v.violations}
    fixed_cfg, _res = RepairPipeline(resolver, db_path=str(db)).run(cfg, snapshot)
    gens = {c["name"]: c.get("generator") for t in fixed_cfg["tables"] for c in t["columns"]}

    # Try filling with the repaired config.
    import yaml

    from sqlseed import fill_from_config

    yaml_path = OUT_DIR / "defect_a.yaml"
    yaml_path.write_text(yaml.safe_dump({**fixed_cfg, "db_path": str(db)}))
    crash = None
    try:
        fill_from_config(str(yaml_path))
    except Exception as e:  # noqa: BLE001 - repro script
        crash = f"{type(e).__name__}: {e}"
    con = sqlite3.connect(db)
    rows = con.execute("SELECT COUNT(*) FROM m").fetchone()[0]
    con.close()

    print(f"  flagged by validator : {sorted(flagged)}")
    print(f"  generators after fix : {gens}")
    print(f"  fill result          : crash={crash!r} rows={rows}")
    # Defect present iff: any column unflagged, or any repaired generator not
    # in core GENERATOR_MAP, or the fill crashed / inserted 0 rows.
    from sqlseed.generators._dispatch import GeneratorDispatchMixin

    unknown = {n: g for n, g in gens.items() if g and g not in GeneratorDispatchMixin.GENERATOR_MAP}
    unflagged = {"qty", "price", "amount"} - {c for c, _ in flagged}
    present = bool(unflagged) or bool(unknown) or crash is not None or rows != 10
    print(f"  => unflagged={sorted(unflagged)} unknown_generators={unknown}")
    print(f"  => defect A {'REPRODUCED' if present else 'NOT present'}")
    return present


def defect_b() -> bool:
    """Nullable UNIQUE column silently filled with NULL in zero-config mode."""
    import sqlseed

    db = OUT_DIR / "defect_b.db"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            ssn TEXT UNIQUE,          -- nullable UNIQUE, no default
            badge_no INTEGER UNIQUE   -- nullable UNIQUE integer
        )"""
    )
    con.commit()
    con.close()

    sqlseed.fill(str(db), table="people", count=50, seed=42)
    con = sqlite3.connect(db)
    total = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    ssn_null = con.execute("SELECT COUNT(*) FROM people WHERE ssn IS NULL").fetchone()[0]
    badge_null = con.execute("SELECT COUNT(*) FROM people WHERE badge_no IS NULL").fetchone()[0]
    ssn_distinct = con.execute("SELECT COUNT(DISTINCT ssn) FROM people").fetchone()[0]
    con.close()
    print(f"  rows={total} ssn: NULL={ssn_null} distinct={ssn_distinct} | badge_no: NULL={badge_null}")
    present = ssn_null == total or badge_null == total
    print(f"  => defect B {'REPRODUCED' if present else 'NOT present'}")
    return present


def main() -> int:
    print("[A] coerce_float_to_int -> random_int / silent COMPATIBLE gaps")
    a = defect_a()
    print("\n[B] nullable UNIQUE column -> silent all-NULL fill")
    b = defect_b()
    print(f"\nRESULT: defect_a={'REPRO' if a else 'ok'} defect_b={'REPRO' if b else 'ok'}")
    return 0 if (a and b) else 1


if __name__ == "__main__":
    sys.exit(main())
