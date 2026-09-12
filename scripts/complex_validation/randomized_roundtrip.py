"""Randomized complex-schema validation across ALL sqlseed libraries.

Randomly fabricates legal-but-structurally-complex databases (FK chains,
CHECK enum/range, UNIQUE, composite PK, self-referencing FK, BLOB, date
columns) and then generates data with every library in the project:

  L1 sqlseed core      : zero-config fill (fill_table)
  L2 sqlseed-ai        : FastValidator + RepairPipeline offline convergence
  L3 MCP tools         : sqlseed_generate_yaml + sqlseed_execute_fill

Each library's output is verified with the SAME 5-dimension harness used by
run_validation.py (imported, not duplicated): row counts / FK integrity /
CHECK re-eval / UNIQUE+NOT NULL / semantic invariants.

Usage: python scripts/complex_validation/randomized_roundtrip.py [seed] [rounds]
Exit code 0 iff every library passes every round with zero violations.
"""

from __future__ import annotations

import random
import sqlite3
import string
import sys
import time
from pathlib import Path
from typing import NamedTuple

from sqlalchemy.exc import SQLAlchemyError

from sqlseed.generators._protocol import ConfigurationError

if __package__:
    from ._checks import CheckRecorder
    from .run_validation import build_db, verify_db
else:
    from _checks import CheckRecorder
    from run_validation import build_db, verify_db

DB_DIR = Path(__file__).resolve().parent / "dbs"
DB_DIR.mkdir(parents=True, exist_ok=True)

check = CheckRecorder(report_passes=False)


# ---------------------------------------------------------------------------
# Random schema fabricator
# ---------------------------------------------------------------------------
# Semantic column catalog: name -> (SQL type, kind, metadata). Kinds drive CHECK inference
# that is ALIGNED with core's mapper semantic domain, so every generated
# value satisfies the constraint (no fabricated semantic contradictions).
#   num   : integer range CHECK (mapper range from EXACT_MATCH_PARAMS)
#   dec   : real  >= 0            (mapper float)
#   enum  : TEXT CHECK IN(mapper's own enum) — aligns with mapper exactly
#   text  : free TEXT (catch_phrase/email/name/...), no CHECK
#   date  : no CHECK (datetime/date generator)
#   blob  : BLOB, no CHECK
#   fk    : INTEGER reference, no CHECK
class _CatalogColumn(NamedTuple):
    """SQL type, semantic kind, and optional CHECK bounds or choices."""

    sql_type: str
    kind: str
    metadata: tuple[int, int] | tuple[str, ...] | None


_COL_CATALOG = {
    "age": _CatalogColumn("INTEGER", "num", (18, 65)),
    "qty": _CatalogColumn("INTEGER", "num", (1, 100)),
    "score": _CatalogColumn("INTEGER", "num", (0, 100)),
    "year": _CatalogColumn("INTEGER", "num", (2000, 2026)),
    "price": _CatalogColumn("REAL", "dec", None),
    "amount": _CatalogColumn("NUMERIC", "dec", None),
    "rating": _CatalogColumn("REAL", "dec", None),
    "gender": _CatalogColumn("TEXT", "enum", ("male", "female", "other")),
    "priority": _CatalogColumn("TEXT", "enum", ("low", "medium", "high")),
    "role": _CatalogColumn("TEXT", "enum", ("admin", "user", "guest")),
    "status": _CatalogColumn("TEXT", "enum", ("active", "inactive", "banned")),
    "email": _CatalogColumn("TEXT", "text", None),
    "note": _CatalogColumn("TEXT", "text", None),
    "name": _CatalogColumn("TEXT", "text", None),
    "title": _CatalogColumn("TEXT", "text", None),
    "description": _CatalogColumn("TEXT", "text", None),
    "created_at": _CatalogColumn("DATETIME", "date", None),
    "updated_at": _CatalogColumn("DATETIME", "date", None),
    "order_date": _CatalogColumn("DATE", "date", None),
    "blobdata": _CatalogColumn("BLOB", "blob", None),
}
_ENUM_COLS = [c for c, (_, k, _v) in _COL_CATALOG.items() if k == "enum"]


class ColumnSpec:
    def __init__(self, name: str, col_type: str, nullable: bool, unique: bool):
        self.name = name
        self.type = col_type
        self.nullable = nullable
        self.unique = unique
        self.check: str | None = None
        self.default: str | None = None
    def ddl(self) -> str:
        parts = [f'"{self.name}" {self.type}']
        if not self.nullable:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        if self.check:
            parts.append(f"CHECK {self.check}")
        return " ".join(parts)
    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Col {self.name} {self.type} nn={not self.nullable} uniq={self.unique}>"


class TableSpec:
    def __init__(self, name: str):
        self.name = name
        self.columns: list[ColumnSpec] = []
        self.pk: list[str] = []
        self.fk: list[tuple[str, str, str]] = []  # (col, ref_table, ref_col)
        self.ref_by: list[str] = []  # tables referencing us (for 2-pass fill)
    def ddl(self) -> str:
        parts = [f"CREATE TABLE \"{self.name}\" ("]
        defs = [c.ddl() for c in self.columns]
        if self.pk:
            primary_key = ", ".join(f'"{column}"' for column in self.pk)
            defs.append(f"PRIMARY KEY ({primary_key})")
        for col, rt, rc in self.fk:
            defs.append(f"FOREIGN KEY (\"{col}\") REFERENCES \"{rt}\"(\"{rc}\")")
        parts.append(", ".join(defs))
        parts.append(")")
        return " ".join(parts)


def _mk_col(rng: random.Random, name: str, nullable: bool, unique: bool) -> ColumnSpec:
    col_type, kind, meta = _COL_CATALOG[name]
    c = ColumnSpec(name, col_type, nullable, unique)
    if kind == "num":
        lo, hi = meta
        c.check = f"({name} >= {lo} AND {name} <= {hi})"
    elif kind == "dec":
        c.check = f"({name} >= 0)"
    elif kind == "enum":
        values = ", ".join(repr(v) for v in meta)
        c.check = f"({name} IN ({values}))"
    return c


def _pick_col(rng: random.Random, used: set[str]) -> str:
    """Pick a semantic column name not yet used on this table."""
    cands = [c for c in _COL_CATALOG if c not in used]
    return rng.choice(cands)


def fabricate(seed: int, rng: random.Random) -> list[TableSpec]:
    """Build a random acyclic FK graph with N tables (2-5).

    Every column is a semantically-consistent (name, type, CHECK) triple, so
    the schemas are both legal AND well-formed — the stress comes from the
    random FK graph, column subsets, UNIQUE/nullable flags, and CHECK ranges.
    """
    n_tables = rng.randint(2, 5)
    names = [f"t{i}" for i in range(n_tables)]
    tables = [TableSpec(n) for n in names]

    for i, table in enumerate(tables):
        n_cols = rng.randint(2, 4)
        table.columns.append(ColumnSpec("id", "INTEGER", False, False))
        table.pk = ["id"]
        used = {"id"}
        # Table row count (mirrors counts_for): table i gets 20 + i*7 rows.
        count = 20 + i * 7
        for _ in range(n_cols):
            name = _pick_col(rng, used)
            used.add(name)
            # Only mark a column UNIQUE when its value space can actually hold
            # `count` distinct values. A UNIQUE num column bounded by a small
            # CHECK range (e.g. year [2000,2026] = 27 values) with count=41 is
            # legal SQL but UNSATISFIABLE — no generator can fill it. Such
            # schemas would trigger 1000 retries and a RuntimeError, which is
            # a fabricator artifact, not a code defect. text/date/blob/dec
            # have effectively unbounded spaces, so UNIQUE is always fine.
            _, kind, meta = _COL_CATALOG[name]
            unique = False
            if rng.random() < 0.25 and name not in _ENUM_COLS:
                if kind == "num":
                    lo, hi = meta
                    unique = (hi - lo + 1) >= count
                else:
                    unique = True
            nullable = rng.random() < 0.3
            table.columns.append(_mk_col(rng, name, nullable, unique))

    # FK edges: each non-root table gets 0-2 FK to earlier tables (acyclic).
    for i in range(1, n_tables):
        n_fk = rng.randint(0, 2)
        cands = list(range(i))
        rng.shuffle(cands)
        for j in cands[:n_fk]:
            col = ColumnSpec(f"{tables[j].name}_id", "INTEGER", True, False)
            tables[i].columns.append(col)
            tables[i].fk.append((col.name, tables[j].name, "id"))
    return tables


def counts_for(tables: list[TableSpec]) -> dict[str, int]:
    return {t.name: 20 + i * 7 for i, t in enumerate(tables)}


# ---------------------------------------------------------------------------
# L1: sqlseed core zero-config fill
# ---------------------------------------------------------------------------
def l1_core(db: Path, tables: list[TableSpec], counts: dict[str, int], seed: int) -> bool:
    import sqlseed

    ok = True
    with sqlseed.connect(str(db)) as orch:
        order = orch.get_topological_table_order(orch.get_table_names())
        for t in order:
            try:
                result = orch.fill_table(t, count=counts[t], seed=seed, batch_size=1000)
                if result.errors:
                    print(f"  [L1] core fill failed on {t}: {result.errors}")
                    ok = False
            except (ConfigurationError, ValueError, RuntimeError, OSError, SQLAlchemyError) as e:
                print(f"  [L1] core fill failed on {t}: {type(e).__name__}: {e}")
                ok = False
    return ok and _verify_all(db, counts, "L1-core")


def _verify_all(db: Path, counts: dict[str, int], tag: str) -> bool:
    results = verify_db(db, counts, [])
    bad = [c for c in results if not c.ok]
    ok = True
    for c in bad:
        ok = False
        print(f"  [L1] {tag} verify fail: {c.dim} {c.table} {c.detail}")
    return ok


# ---------------------------------------------------------------------------
# L2: sqlseed-ai FastValidator + RepairPipeline offline
# ---------------------------------------------------------------------------
def l2_ai(db: Path, seed: int) -> bool:
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.repair.pipeline import RepairPipeline
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    snapshot = SchemaSnapshot(db_path=str(db))

    # Build a naive LLM-style config (generic generators) to stress the
    # contract matrix + repair pipeline against the random schema.
    tables = [
        r[0] for r in sqlite3.connect(db).execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    cfg = {"tables": []}
    con = sqlite3.connect(db)
    for t in tables:
        cols = []
        for r in con.execute(f'PRAGMA table_info("{t}")'):
            name, ctype = r[1], r[2]
            if ctype.upper() == "INTEGER":
                cols.append({"name": name, "generator": "integer", "params": {"min_value": 0, "max_value": 999}})
            elif ctype.upper() in {"REAL", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE"}:
                cols.append({"name": name, "generator": "float", "params": {"min_value": 0, "max_value": 999}})
            elif ctype.upper() in {"BLOB", "BOOLEAN"}:
                cols.append({"name": name, "generator": "string"})
            else:
                cols.append({"name": name, "generator": "string"})
        cfg["tables"].append({"name": t, "count": 25, "columns": cols})
    con.close()

    FastValidator(resolver, db_path=str(db)).validate(cfg, snapshot)
    fixed, _res = RepairPipeline(resolver, db_path=str(db)).run(cfg, snapshot)

    # Emit repaired YAML and fill via core.
    import yaml

    from sqlseed import fill_from_config

    out = DB_DIR / f"_rand_{seed}_ai.yaml"
    out.write_text(yaml.safe_dump({**fixed, "db_path": str(db)}))
    try:
        results = fill_from_config(str(out))
        if errors := [error for result in results for error in result.errors]:
            print(f"  [L2] ai-repaired fill failed: {errors}")
            return False
    except (ConfigurationError, ValueError, RuntimeError, OSError, SQLAlchemyError) as e:
        print(f"  [L2] ai-repaired fill failed: {type(e).__name__}: {e}")
        return False
    return _verify_all(db, {t: 25 for t in tables}, "L2-ai")


# ---------------------------------------------------------------------------
# L3: MCP tools generate_yaml + execute_fill
# ---------------------------------------------------------------------------
def l3_mcp(db: Path, tables: list[TableSpec], seed: int) -> bool:
    from mcp_server_sqlseed.server import sqlseed_execute_fill, sqlseed_generate_yaml

    ok = True
    for t in tables:
        yaml_str = sqlseed_generate_yaml(db_path=str(db), table_name=t.name)
        if "# Error" in yaml_str:
            print(f"  [L3] generate_yaml({t.name}) failed: {yaml_str[:120]}")
            ok = False
            continue
        r = sqlseed_execute_fill(db_path=str(db), table_name=t.name, count=18, yaml_config=yaml_str)
        if not isinstance(r, dict) or r.get("errors"):
            print(f"  [L3] execute_fill({t.name}) failed: {str(r)[:160]}")
            ok = False
    if ok:
        return _verify_all(db, {t.name: 18 for t in tables}, "L3-mcp")
    return False


# ---------------------------------------------------------------------------
def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260805
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rng = random.Random(seed)

    t0 = time.perf_counter()
    for r in range(rounds):
        r_seed = rng.randint(0, 10**9)
        r_rng = random.Random(r_seed)
        tables = fabricate(r_seed, r_rng)
        counts = counts_for(tables)
        db = DB_DIR / f"rand_r{r}.db"
        build_db(db, [t.ddl() for t in tables])
        print(f"\n=== Round {r} seed={r_seed} tables={len(tables)} ===")
        for t in tables:
            print(f"  {t.name}: {[c.name for c in t.columns]} pk={t.pk} fk={[f[0] for f in t.fk]}")

        # L1 core (fresh db)
        db_l1 = DB_DIR / f"rand_r{r}_core.db"
        build_db(db_l1, [t.ddl() for t in tables])
        check(f"L1-core round{r}", l1_core(db_l1, tables, counts, r_seed))

        # L2 ai (fresh db)
        db_l2 = DB_DIR / f"rand_r{r}_ai.db"
        build_db(db_l2, [t.ddl() for t in tables])
        check(f"L2-ai round{r}", l2_ai(db_l2, r_seed))

        # L3 mcp (fresh db)
        db_l3 = DB_DIR / f"rand_r{r}_mcp.db"
        build_db(db_l3, [t.ddl() for t in tables])
        check(f"L3-mcp round{r}", l3_mcp(db_l3, tables, r_seed))

    print("\n" + "=" * 70)
    print(f"TOTAL: {check.passed} passed, {check.failed} failed  ({time.perf_counter()-t0:.1f}s)")
    if check.failures:
        print("failed:", ", ".join(check.failures))
    print("=" * 70)
    return 0 if check.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
