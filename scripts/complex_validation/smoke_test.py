"""Smoke test suite for sqlseed core + CLI (S1-S8).

  S1  seed reproducibility   : same seed -> identical rows across two fills
  S2  provider compatibility : base + faker providers both fill correctly
  S3  CLI surface            : fill / preview / inspect commands work
  S4  boundary counts        : count=0 and count=1 edge cases
  S5  large-scale fill       : 20k rows with UNIQUE + FK stays consistent
  S6  preview isolation      : preview never writes to the database
  S7  YAML round-trip        : fill_from_config honors seed/derive_from
  S8  error handling         : unknown table / bad config fail loudly

Usage: python scripts/complex_validation/smoke_test.py
Exit code 0 iff all checks pass.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

OUT_DIR = Path(tempfile.mkdtemp(prefix="sqlseed_smoke_"))

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


def build_db(name: str, ddl: list[str]) -> Path:
    db = OUT_DIR / name
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    for stmt in ddl:
        con.execute(stmt)
    con.commit()
    con.close()
    return db


SHOP_DDL = [
    """CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        age INTEGER CHECK (age >= 0 AND age <= 150)
    )""",
    """CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(user_id),
        total REAL NOT NULL CHECK (total >= 0)
    )""",
]


def s1_seed_reproducibility() -> None:
    print("\n[S1] seed reproducibility")
    import sqlseed

    db1 = build_db("s1a.db", SHOP_DDL)
    db2 = build_db("s1b.db", SHOP_DDL)
    sqlseed.fill(str(db1), table="users", count=100, seed=123)
    sqlseed.fill(str(db2), table="users", count=100, seed=123)
    rows1 = sqlite3.connect(db1).execute("SELECT email, name, age FROM users ORDER BY user_id").fetchall()
    rows2 = sqlite3.connect(db2).execute("SELECT email, name, age FROM users ORDER BY user_id").fetchall()
    check("S1 same seed -> identical rows", rows1 == rows2 and len(rows1) == 100,
          f"equal={rows1 == rows2} n1={len(rows1)} n2={len(rows2)}")

    db3 = build_db("s1c.db", SHOP_DDL)
    sqlseed.fill(str(db3), table="users", count=100, seed=999)
    rows3 = sqlite3.connect(db3).execute("SELECT email, name, age FROM users ORDER BY user_id").fetchall()
    check("S1 different seed -> different rows", rows1 != rows3)


def s2_provider_compatibility() -> None:
    print("\n[S2] provider compatibility")
    import sqlseed

    for provider in ("base", "faker"):
        db = build_db(f"s2_{provider}.db", SHOP_DDL)
        try:
            sqlseed.fill(str(db), table="users", count=50, seed=7, provider=provider)
            con = sqlite3.connect(db)
            n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            dup = con.execute("SELECT COUNT(*) - COUNT(DISTINCT email) FROM users").fetchone()[0]
            con.close()
            check(f"S2 provider={provider} fills 50 unique-email rows", n == 50 and dup == 0,
                  f"n={n} dup={dup}")
        except Exception as e:  # noqa: BLE001
            check(f"S2 provider={provider} fills 50 unique-email rows", False, f"{type(e).__name__}: {e}")


def s3_cli_surface() -> None:
    print("\n[S3] CLI surface")
    from click.testing import CliRunner
    from sqlseed_cli.main import cli

    db = build_db("s3.db", SHOP_DDL)
    runner = CliRunner()
    r = runner.invoke(cli, ["fill", str(db), "-t", "users", "-n", "40", "--seed", "5"])
    check("S3 cli fill", r.exit_code == 0, f"exit={r.exit_code} out={r.output[-200:]}")

    r = runner.invoke(cli, ["preview", str(db), "-t", "users", "-n", "5"])
    check("S3 cli preview", r.exit_code == 0, f"exit={r.exit_code} out={r.output[-200:]}")

    r = runner.invoke(cli, ["inspect", str(db)])
    check("S3 cli inspect", r.exit_code == 0 and "users" in r.output,
          f"exit={r.exit_code} out={r.output[-200:]}")


def s4_boundary_counts() -> None:
    print("\n[S4] boundary counts")
    import sqlseed

    db = build_db("s4.db", SHOP_DDL)
    # count=0 is rejected loudly (ValueError, not assert — per project rules).
    try:
        sqlseed.fill(str(db), table="users", count=0, seed=1)
        check("S4 count=0 rejected loudly", False, "no exception")
    except ValueError:
        check("S4 count=0 rejected loudly", True)
    except Exception as e:  # noqa: BLE001
        check("S4 count=0 rejected loudly", False, f"wrong type: {type(e).__name__}: {e}")

    try:
        sqlseed.fill(str(db), table="users", count=1, seed=1)
        n1 = sqlite3.connect(db).execute("SELECT COUNT(*) FROM users").fetchone()[0]
        check("S4 count=1 inserts exactly one", n1 == 1, f"n={n1}")
    except Exception as e:  # noqa: BLE001
        check("S4 count=1 inserts exactly one", False, f"{type(e).__name__}: {e}")


def s5_large_scale() -> None:
    print("\n[S5] large-scale fill")
    import sqlseed

    db = build_db("s5.db", SHOP_DDL)
    sqlseed.fill(str(db), table="users", count=2000, seed=11)
    sqlseed.fill(str(db), table="orders", count=20000, seed=11)
    con = sqlite3.connect(db)
    users_n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    orders_n = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) - COUNT(DISTINCT email) FROM users").fetchone()[0]
    orphans = con.execute(
        "SELECT COUNT(*) FROM orders WHERE user_id NOT IN (SELECT user_id FROM users)"
    ).fetchone()[0]
    con.close()
    check("S5 2k users + 20k orders, unique emails, no FK orphans",
          users_n == 2000 and orders_n == 20000 and dup == 0 and orphans == 0,
          f"users={users_n} orders={orders_n} dup={dup} orphans={orphans}")


def s6_preview_isolation() -> None:
    print("\n[S6] preview isolation")
    import sqlseed

    db = build_db("s6.db", SHOP_DDL)
    rows = sqlseed.preview(str(db), table="users", count=10, seed=3)
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM users").fetchone()[0]
    check("S6 preview returns rows without writing",
          len(rows) == 10 and n == 0, f"preview_rows={len(rows)} db_rows={n}")


def s7_yaml_round_trip() -> None:
    print("\n[S7] YAML round-trip")
    import yaml

    from sqlseed import fill_from_config

    db = build_db("s7.db", [
        """CREATE TABLE invoices (
            id INTEGER PRIMARY KEY,
            qty INTEGER NOT NULL CHECK (qty > 0),
            unit_price REAL NOT NULL CHECK (unit_price > 0),
            line_total REAL NOT NULL
        )"""
    ])
    cfg = {
        "db_path": str(db),
        "seed": 42,
        "tables": [{
            "name": "invoices",
            "count": 60,
            "columns": [
                {"name": "qty", "generator": "integer", "params": {"min_value": 1, "max_value": 10}},
                {"name": "unit_price", "generator": "float", "params": {"min_value": 1, "max_value": 100}},
                {"name": "line_total", "derive_from": ["qty", "unit_price"],
                 "expression": "round(row['qty'] * row['unit_price'], 2)"},
            ],
        }],
    }
    path = OUT_DIR / "s7.yaml"
    path.write_text(yaml.safe_dump(cfg))
    fill_from_config(str(path))
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    mismatch = con.execute(
        "SELECT COUNT(*) FROM invoices WHERE ABS(line_total - ROUND(qty * unit_price, 2)) > 0.001"
    ).fetchone()[0]
    bad_check = con.execute("SELECT COUNT(*) FROM invoices WHERE qty <= 0 OR unit_price <= 0").fetchone()[0]
    con.close()
    check("S7 derive_from expression + CHECK compliance",
          n == 60 and mismatch == 0 and bad_check == 0,
          f"n={n} mismatch={mismatch} bad_check={bad_check}")


def s8_error_handling() -> None:
    print("\n[S8] error handling")
    import sqlseed

    db = build_db("s8.db", SHOP_DDL)
    # Public fill() collects errors into the result rather than raising.
    r = sqlseed.fill(str(db), table="no_such_table", count=5)
    check("S8 unknown table surfaces error in result",
          r.count == 0 and bool(r.errors), f"count={r.count} errors={r.errors}")

    import yaml

    from sqlseed import fill_from_config

    bad = OUT_DIR / "s8_bad.yaml"
    bad.write_text(yaml.safe_dump({"db_path": str(db), "tables": [{"name": "users", "count": -5}]}))
    try:
        fill_from_config(str(bad))
        check("S8 negative count rejected", False, "no exception")
    except Exception as e:  # noqa: BLE001
        check("S8 negative count rejected", True, f"{type(e).__name__}")


def main() -> int:
    print("=" * 70)
    print("sqlseed smoke test suite (S1-S8)")
    print("=" * 70)
    s1_seed_reproducibility()
    s2_provider_compatibility()
    s3_cli_surface()
    s4_boundary_counts()
    s5_large_scale()
    s6_preview_isolation()
    s7_yaml_round_trip()
    s8_error_handling()
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
