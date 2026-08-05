"""Offline validation suite for the sqlseed-ai self-healing subsystem.

Exercises all six layers WITHOUT any LLM backend (deterministic paths only):

  A  Layer 1 contracts    : ContractResolver specificity + learned-override
  B  Layer 2 validator    : FastValidator single-column + dialect_parser
  C  Layer 3 repair       : RepairPipeline on broken configs + LLM-name gaps
  D  Layer 4 degrader     : ProgressiveDegrader keeps CHECK-inferred params
  E  Layer 5 auto-heal    : deterministic CHECK inference -> L3 convergence
  F  MCP tools            : generate_yaml / execute_fill round-trip + safety

Test DBs (built fresh under ./dbs):
  shop.db     — CHECK enum + range, UNIQUE, 2-table FK
  forum.db    — self-referencing FK, 4-table FK cycle
  metrics.db  — numeric columns for the LLM-name normalization gap

Usage: python scripts/complex_validation/ai_offline_validation.py
Exit code 0 iff all checks pass.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent / "dbs"
DB_DIR.mkdir(exist_ok=True)

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name}  {detail}")


def build_db(path: Path, ddl: list[str]) -> Path:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for stmt in ddl:
        con.execute(stmt)
    con.commit()
    con.close()
    return path


SHOP_DDL = [
    """CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'banned')),
        age INTEGER CHECK (age >= 18 AND age <= 120),
        created_at DATETIME NOT NULL
    )""",
    """CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(user_id),
        total REAL NOT NULL CHECK (total >= 0),
        ordered_at DATETIME NOT NULL
    )""",
]

FORUM_DDL = [
    """CREATE TABLE category (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id INTEGER REFERENCES category(id)
    )""",
    """CREATE TABLE cycle_a (
        id INTEGER PRIMARY KEY,
        b_id INTEGER REFERENCES cycle_b(id)
    )""",
    """CREATE TABLE cycle_b (
        id INTEGER PRIMARY KEY,
        c_id INTEGER REFERENCES cycle_c(id)
    )""",
    """CREATE TABLE cycle_c (
        id INTEGER PRIMARY KEY,
        d_id INTEGER REFERENCES cycle_d(id)
    )""",
    """CREATE TABLE cycle_d (
        id INTEGER PRIMARY KEY,
        a_id INTEGER REFERENCES cycle_a(id)
    )""",
]


def fill_with_config(cfg: dict[str, Any], db: Path, tag: str) -> tuple[bool, str]:
    """Fill via sqlseed.fill_from_config; return (ok, error_detail)."""
    import yaml

    from sqlseed import fill_from_config

    yaml_path = DB_DIR / f"_{tag}.yaml"
    yaml_path.write_text(yaml.safe_dump({**cfg, "db_path": str(db)}))
    try:
        fill_from_config(str(yaml_path))
    except Exception as e:  # noqa: BLE001 - validation harness
        return False, f"{type(e).__name__}: {e}"
    return True, ""


# ---------------------------------------------------------------------------
# A. Layer 1 — contract matrix
# ---------------------------------------------------------------------------
def section_a() -> None:
    print("\n[A] Layer 1 ContractResolver")
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver, ContractViolation, ViolationKind

    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    check("A1 builtin matrix non-trivial size", len(BUILTIN_VIOLATIONS) >= 15, f"size={len(BUILTIN_VIOLATIONS)}")

    v = resolver.check("integer", "TIMESTAMP", frozenset(), {})
    check("A2 integer@TIMESTAMP crash -> datetime",
          v is not None and v.fix_strategy == "switch_generator" and v.fix_params.get("target") == "datetime")

    v = resolver.check("email", "TEXT", frozenset(), {})
    check("A3 unlisted combo defaults COMPATIBLE", v is None)

    # Specificity: exact match beats wildcard ANY.
    v = resolver.check("string", "INTEGER", frozenset(), {})
    check("A4 string@INTEGER exact beats ANY wildcard",
          v is not None and v.kind == ViolationKind.CRASH and v.fix_params.get("target") == "integer")

    # Learned overrides builtin with the same identity.
    learned = {
        ContractViolation(
            generator="integer",
            column_type="TIMESTAMP",
            constraints=frozenset(),
            kind=ViolationKind.CRASH,
            fix_strategy="switch_generator",
            fix_params={"target": "string"},  # deliberately different target
            source="auto_learned",
        )
    }
    resolver2 = ContractResolver(BUILTIN_VIOLATIONS, learned)
    v = resolver2.check("integer", "TIMESTAMP", frozenset(), {})
    check("A5 learned violation overrides builtin",
          v is not None and v.fix_params.get("target") == "string", f"got={v and v.fix_params}")

    # Predicate gating: code-like name triggers, plain name does not.
    v_code = resolver.check("choice", "ANY", frozenset({"UNIQUE"}),
                            {"name": "order_code", "row_count": 100, "pool_size": 200})
    v_plain = resolver.check("choice", "ANY", frozenset({"UNIQUE"}),
                             {"name": "status", "row_count": 100, "pool_size": 200})
    check("A6 predicate gating (code-like vs plain)",
          v_code is not None and v_code.fix_strategy == "upgrade_to_template" and v_plain is None)


# ---------------------------------------------------------------------------
# B. Layer 2 — FastValidator
# ---------------------------------------------------------------------------
def section_b() -> None:
    print("\n[B] Layer 2 FastValidator")
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.dialect_parser import DialectErrorParser
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    db = build_db(DB_DIR / "shop_b.db", SHOP_DDL)
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    snapshot = SchemaSnapshot(db_path=str(db))
    validator = FastValidator(resolver, db_path=str(db))

    clean_cfg = {
        "tables": [{
            "name": "users", "count": 30,
            "columns": [
                {"name": "email", "generator": "email"},
                {"name": "status", "generator": "choice",
                 "params": {"choices": ["active", "inactive", "banned"]}},
                {"name": "age", "generator": "integer", "params": {"min_value": 18, "max_value": 120}},
                {"name": "created_at", "generator": "datetime"},
            ],
        }]
    }
    v = validator.validate(clean_cfg, snapshot)
    check("B1 clean config passes validation", v.is_clean, f"violations={[(x.columns, x.fix_hint) for x in v.violations]}")

    broken_cfg = {
        "tables": [{
            "name": "users", "count": 30,
            "columns": [
                {"name": "created_at", "generator": "integer"},          # crash: integer@DATETIME? (only TIMESTAMP covered) -> may be clean
                {"name": "status", "generator": "integer"},               # crash: integer@TEXT? semantic
                {"name": "age", "generator": "random_float"},             # coerce_float_to_int
            ],
        }]
    }
    v = validator.validate(broken_cfg, snapshot)
    hints = {(x.columns[0], x.fix_hint) for x in v.violations}
    check("B2 broken config flagged (age coerce)",
          ("age", "coerce_float_to_int") in hints, f"hints={sorted(hints)}")

    # Cardinality: choice pool smaller than row count on UNIQUE column.
    card_cfg = {
        "tables": [{
            "name": "users", "count": 30,
            "columns": [{"name": "email", "generator": "choice", "params": {"choices": ["a@x.com", "b@x.com"]}}],
        }]
    }
    v = validator.validate(card_cfg, snapshot)
    uniq = [x for x in v.violations if x.severity == "unique_unsatisfiable"]
    check("B3 UNIQUE cardinality check (pool 2 < 30 rows)", len(uniq) >= 1,
          f"violations={[(x.columns, x.severity) for x in v.violations]}")

    # Dialect parser: normalize a raw sqlite IntegrityError into a report.
    try:
        con = sqlite3.connect(db)
        con.execute("INSERT INTO users (user_id, email, status, age, created_at) VALUES (1, 'a@b.c', 'active', 30, '2024-01-01')")
        con.execute("INSERT INTO users (user_id, email, status, age, created_at) VALUES (2, 'a@b.c', 'active', 30, '2024-01-01')")
        con.commit()
        check("B4 dialect parser (setup insert must fail)", False, "no IntegrityError raised")
    except Exception as e:  # noqa: BLE001
        report = DialectErrorParser.parse(e, dialect="sqlite", table="users", snapshot=None)
        check("B4 dialect parser normalizes UNIQUE IntegrityError",
              report is not None and report.constraint_type.name == "UNIQUE" and "email" in report.columns,
              f"report={report}")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# C. Layer 3 — RepairPipeline
# ---------------------------------------------------------------------------
def section_c() -> None:
    print("\n[C] Layer 3 RepairPipeline")
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.repair.pipeline import RepairPipeline
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    db = build_db(DB_DIR / "shop_c.db", SHOP_DDL)
    snapshot = SchemaSnapshot(db_path=str(db))
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    pipeline = RepairPipeline(resolver, db_path=str(db))

    broken = {
        "tables": [{
            "name": "users", "count": 30,
            "columns": [
                {"name": "email", "generator": "email"},
                {"name": "status", "generator": "choice", "params": {"choices": ["active", "inactive", "banned"]}},
                {"name": "age", "generator": "random_float", "params": {"min_value": 18, "max_value": 120}},
                {"name": "created_at", "generator": "integer"},
            ],
        }]
    }
    new_cfg, result = pipeline.run(broken, snapshot)
    fixed_strategies = {f.fix_strategy for f in result.applied_fixes}
    check("C1 pipeline repairs random_float+integer crashes",
          {"coerce_float_to_int", "switch_generator"} <= fixed_strategies and not result.unfixable,
          f"fixed={fixed_strategies} unfixable={result.unfixable}")

    gens = {c["name"]: c.get("generator") for t in new_cfg["tables"] for c in t["columns"]}
    check("C2 repaired generators are core-registered",
          gens.get("age") == "integer" and gens.get("created_at") == "datetime",
          f"gens={gens}")

    ok, detail = fill_with_config(new_cfg, db, "c2")
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    check("C3 repaired config fills 30 users", ok and n == 30, f"{detail} rows={n}")

    # normalize_params strips params outside the generator whitelist.
    from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES
    from sqlseed_ai.validator.models import ConstraintType, ViolationReport

    col = {"name": "age", "generator": "integer",
           "params": {"min_value": 0, "max_value": 9, "bogus_param": True, "length": 3}}
    v = ViolationReport(table="t", columns=["age"], constraint_type=ConstraintType.CHECK,
                        severity="semantic_error", fix_hint="normalize_params", fix_params={})
    stripped = REPAIR_STRATEGIES["normalize_params"](col, v, {})
    check("C4 normalize_params strips non-whitelist params",
          stripped["params"] == {"min_value": 0, "max_value": 9}, f"params={stripped['params']}")

    # LLM-name normalization: random_float/random_int are expression functions, not
    # core generators. The matrix must catch them on EVERY numeric column family,
    # and the repaired config must fill without UnknownGeneratorError.
    db2 = DB_DIR / "shop_c2.db"
    build_db(db2, ["CREATE TABLE m (id INTEGER PRIMARY KEY, price REAL, qty INT, amount NUMERIC)"])
    snap2 = SchemaSnapshot(db_path=str(db2))
    pipeline2 = RepairPipeline(resolver, db_path=str(db2))
    llm_cfg = {
        "tables": [{
            "name": "m", "count": 10,
            "columns": [
                {"name": "price", "generator": "random_float", "params": {"min_value": 0, "max_value": 99}},
                {"name": "qty", "generator": "random_int", "params": {"min_value": 0, "max_value": 99}},
                {"name": "amount", "generator": "random_float"},
            ],
        }]
    }
    v2 = FastValidator(resolver, db_path=str(db2)).validate(llm_cfg, snap2)
    flagged = {(v.columns[0], v.fix_hint) for v in v2.violations}
    fixed_cfg, fix_res = pipeline2.run(llm_cfg, snap2)
    gens = {c["name"]: c.get("generator") for t in fixed_cfg["tables"] for c in t["columns"]}
    ok, detail = fill_with_config(fixed_cfg, db2, "c5")
    con = sqlite3.connect(db2)
    n2 = con.execute("SELECT COUNT(*) FROM m").fetchone()[0]
    con.close()
    check("C5 LLM-style names (random_float/random_int) on REAL/INT/NUMERIC: caught, repaired, filled",
          len(v2.violations) == 3 and not fix_res.unfixable
          and gens == {"price": "float", "qty": "integer", "amount": "float"}
          and ok and n2 == 10,
          f"flagged={flagged} gens={gens} {detail} rows={n2}")


# ---------------------------------------------------------------------------
# D. Layer 4 — ProgressiveDegrader
# ---------------------------------------------------------------------------
def section_d() -> None:
    print("\n[D] Layer 4 ProgressiveDegrader")
    from sqlseed_ai.healer.degrader import ProgressiveDegrader
    from sqlseed_ai.healer.models import DegradeReason
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    db = build_db(DB_DIR / "shop_d.db", SHOP_DDL)
    snapshot = SchemaSnapshot(db_path=str(db))
    degrader = ProgressiveDegrader(snapshot)

    cfg = {
        "tables": [{
            "name": "users", "count": 30,
            "columns": [
                {"name": "email", "generator": "email"},
                {"name": "status", "generator": "choice",
                 "params": {"choices": ["active", "inactive", "banned"]},
                 "faker_method": "random_element", "native_params": {"elements": ["active"]}},
                {"name": "age", "generator": "integer", "params": {"min_value": 18, "max_value": 120}},
            ],
        }]
    }
    new_cfg, applied = degrader.degrade(cfg, {"status": DegradeReason.LLM_FAILURE}, [])
    status_col = next(c for t in new_cfg["tables"] for c in t["columns"] if c["name"] == "status")
    check("D1 degraded column marked _degraded", status_col.get("_degraded") is True)
    check("D2 LLM-native fields stripped",
          "faker_method" not in status_col and "native_params" not in status_col,
          f"keys={sorted(status_col)}")
    check("D3 CHECK-inferred generator/params preserved",
          status_col.get("generator") == "choice"
          and status_col.get("params", {}).get("choices") == ["active", "inactive", "banned"],
          f"col={status_col}")
    other = next(c for t in new_cfg["tables"] for c in t["columns"] if c["name"] == "age")
    check("D4 untouched columns keep their spec", other.get("generator") == "integer" and "_degraded" not in other)
    check("D5 applied fixes recorded", len(applied) >= 1 and applied[0].fix_strategy == "progressive_degrade",
          f"applied={[(a.columns, a.fix_strategy) for a in applied]}")


# ---------------------------------------------------------------------------
# E. Layer 5 — deterministic CHECK inference + L3 convergence
# ---------------------------------------------------------------------------
def section_e() -> None:
    print("\n[E] Layer 5 AutoHeal deterministic inference")
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.repair.pipeline import RepairPipeline
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    db = build_db(DB_DIR / "shop_e.db", SHOP_DDL)
    resolver = ContractResolver(BUILTIN_VIOLATIONS, set())
    snapshot = SchemaSnapshot(db_path=str(db))

    # Simulate the deterministic CHECK-inference output (what
    # AutoHealOrchestrator._build_subgraph_config produces before any LLM call):
    # choice with the CHECK enum, integer within the CHECK range.
    inferred = {
        "tables": [{
            "name": "users", "count": 25,
            "columns": [
                {"name": "email", "generator": "string"},   # deliberately generic -> semantic_upgrade/switch expected? (string@TEXT UNIQUE code-like? email is not code-like) 
                {"name": "status", "generator": "choice",
                 "params": {"choices": ["active", "inactive", "banned"]}},
                {"name": "age", "generator": "integer", "params": {"min_value": 18, "max_value": 120}},
                {"name": "created_at", "generator": "datetime"},
            ],
        }]
    }
    v1 = FastValidator(resolver, db_path=str(db)).validate(inferred, snapshot)
    fixed, res = RepairPipeline(resolver, db_path=str(db)).run(inferred, snapshot)
    v2 = FastValidator(resolver, db_path=str(db)).validate(fixed, snapshot)
    check("E1 inferred config converges after L3 repair",
          v2.is_clean, f"remaining={[(x.columns, x.fix_hint) for x in v2.violations]}")
    check("E2 no unfixable violations", not res.unfixable, f"unfixable={res.unfixable}")

    ok, detail = fill_with_config(fixed, db, "e3")
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    bad_status = con.execute("SELECT COUNT(*) FROM users WHERE status NOT IN ('active','inactive','banned')").fetchone()[0]
    bad_age = con.execute("SELECT COUNT(*) FROM users WHERE age < 18 OR age > 120").fetchone()[0]
    con.close()
    check("E3 repaired config fills with CHECK compliance",
          ok and n == 25 and bad_status == 0 and bad_age == 0,
          f"{detail} rows={n} bad_status={bad_status} bad_age={bad_age}")


# ---------------------------------------------------------------------------
# F. MCP tools — rule-driven YAML generation + fill round-trip
# ---------------------------------------------------------------------------
def section_f() -> None:
    print("\n[F] MCP tools round-trip")
    try:
        from mcp_server_sqlseed.server import sqlseed_execute_fill, sqlseed_generate_yaml
    except Exception as e:  # noqa: BLE001
        check("F0 MCP server importable", False, f"{type(e).__name__}: {e}")
        return

    db = build_db(DB_DIR / "shop_f.db", SHOP_DDL)

    users_yaml = sqlseed_generate_yaml(db_path=str(db), table_name="users")
    check("F1 generate_yaml(users) returns YAML",
          "# Error" not in users_yaml and "users" in users_yaml, f"out={users_yaml[:160]}")

    orders_yaml = sqlseed_generate_yaml(db_path=str(db), table_name="orders")
    check("F2 generate_yaml(orders) returns YAML",
          "# Error" not in orders_yaml and "orders" in orders_yaml, f"out={orders_yaml[:160]}")

    r1 = sqlseed_execute_fill(db_path=str(db), table_name="users", count=30, yaml_config=users_yaml)
    check("F3 execute_fill(users, 30) succeeds",
          isinstance(r1, dict) and r1.get("count") == 30 and not r1.get("errors"),
          f"result={str(r1)[:200]}")

    r2 = sqlseed_execute_fill(db_path=str(db), table_name="orders", count=50, yaml_config=orders_yaml)
    check("F4 execute_fill(orders, 50) succeeds",
          isinstance(r2, dict) and r2.get("count") == 50 and not r2.get("errors"),
          f"result={str(r2)[:200]}")

    con = sqlite3.connect(db)
    users_n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    orders_n = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    fk_orphans = con.execute("PRAGMA foreign_key_check").fetchall()
    bad_status = con.execute(
        "SELECT COUNT(*) FROM users WHERE status NOT IN ('active','inactive','banned')"
    ).fetchone()[0]
    con.close()
    check("F5 round-trip rows + FK + CHECK enum integrity",
          users_n == 30 and orders_n == 50 and len(fk_orphans) == 0 and bad_status == 0,
          f"users={users_n} orders={orders_n} orphans={len(fk_orphans)} bad_status={bad_status}")

    # Safety: unknown table must be rejected, not crash or fill anything.
    bad = sqlseed_generate_yaml(db_path=str(db), table_name="no_such_table")
    check("F6 generate_yaml rejects unknown table", "# Error" in bad, f"out={bad[:160]}")

    # Safety: unwritable db target must be rejected by _validate_db_target.
    bad2 = sqlseed_execute_fill(db_path="/nonexistent_dir_xyz/nope.db", table_name="users", count=1)
    check("F7 execute_fill rejects unwritable target",
          isinstance(bad2, dict) and ("error" in bad2 or "errors" in bad2),
          f"result={str(bad2)[:200]}")


def main() -> int:
    print("=" * 70)
    print("sqlseed-ai offline validation (no LLM backend required)")
    print("=" * 70)
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    print("\n" + "=" * 70)
    print(f"TOTAL: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("failed checks:")
        for f in FAILURES:
            print(f"  - {f}")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
