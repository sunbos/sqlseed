"""Zero-config validation harness for complex real-world schemas.

Pipeline per schema DB:
  build (DDL only) -> fill (sqlseed core, zero-config) -> verify 5 dimensions.

Verification is INDEPENDENT of fill-time enforcement:
  D1 row counts     : SELECT COUNT(*) == requested (skipped tables == 0)
  D2 FK integrity   : PRAGMA foreign_key_check returns 0 rows
  D3 CHECK re-eval  : extract CHECK(...) from sqlite_master, re-run WHERE NOT (expr)
  D4 UNIQUE/NOT NULL: group-by duplicate scan + NULL scan via PRAGMA metadata
  D5 semantic       : per-schema domain invariants (e.g. email contains '@')

Usage: python scripts/complex_validation/run_validation.py [schema ...]
Exit code 0 iff all hard checks pass.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import DEFAULT_COUNT, SCHEMAS  # noqa: E402

DB_DIR = Path(__file__).resolve().parent / "dbs"
SEED = 42


@dataclass
class CheckResult:
    dim: str
    table: str
    ok: bool
    detail: str = ""


@dataclass
class DbReport:
    name: str
    fill_errors: dict[str, str] = field(default_factory=dict)
    fill_seconds: float = 0.0
    rows_filled: int = 0
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]


def extract_checks(create_sql: str) -> list[str]:
    """Extract balanced-paren CHECK(...) expressions from a CREATE TABLE statement."""
    exprs: list[str] = []
    for m in re.finditer(r"\bCHECK\b", create_sql, re.IGNORECASE):
        i = m.end()
        while i < len(create_sql) and create_sql[i].isspace():
            i += 1
        if i >= len(create_sql) or create_sql[i] != "(":
            continue
        depth, j, in_str = 0, i, False
        while j < len(create_sql):
            c = create_sql[j]
            if in_str:
                if c == "'":
                    if j + 1 < len(create_sql) and create_sql[j + 1] == "'":
                        j += 1
                    else:
                        in_str = False
            elif c == "'":
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    exprs.append(create_sql[i + 1 : j])
                    break
            j += 1
    return exprs


def build_db(db_path: Path, ddl: list[str]) -> None:
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    try:
        for stmt in ddl:
            con.execute(stmt)
        con.commit()
    finally:
        con.close()


def fill_db(db_path: Path, counts: dict) -> tuple[dict[str, str], float, int]:
    import sqlseed

    errors: dict[str, str] = {}
    rows = 0
    t_start = time.perf_counter()
    with sqlseed.connect(str(db_path)) as orch:
        order = orch.get_topological_table_order(orch.get_table_names())
        for table in order:
            n = counts.get(table, DEFAULT_COUNT)
            if n is None:
                continue
            try:
                orch.fill_table(table, count=n, seed=SEED, batch_size=5000)
                rows += n
            except Exception as exc:  # noqa: BLE001 - record and continue
                errors[table] = f"{type(exc).__name__}: {exc}"[:300]
    return errors, time.perf_counter() - t_start, rows


def verify_db(db_path: Path, counts: dict, semantic: list) -> list[CheckResult]:
    checks: list[CheckResult] = []
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        tables = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

        # D1 row counts
        for t in tables:
            n = counts.get(t, DEFAULT_COUNT)
            expected = 0 if n is None else n
            actual = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            checks.append(CheckResult("D1-rows", t, actual == expected, f"expected={expected} actual={actual}"))

        # D2 FK integrity
        orphans = con.execute("PRAGMA foreign_key_check").fetchall()
        checks.append(CheckResult("D2-fk", "*", len(orphans) == 0, f"orphans={len(orphans)} {orphans[:3]}"))

        # D3 CHECK re-evaluation (independent of insert-time enforcement)
        for t, sql in tables.items():
            if counts.get(t, DEFAULT_COUNT) is None:
                continue
            for expr in extract_checks(sql):
                try:
                    bad = con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE NOT ({expr})').fetchone()[0]
                except sqlite3.Error as exc:
                    checks.append(CheckResult("D3-check", t, False, f"unevaluable: {expr[:60]} ({exc})"))
                    continue
                checks.append(CheckResult("D3-check", t, bad == 0, f"NOT ({expr[:70]}) -> {bad}"))

        # D4 UNIQUE duplicates + NOT NULL violations
        for t in tables:
            if counts.get(t, DEFAULT_COUNT) is None:
                continue
            cols_info = con.execute(f'PRAGMA table_info("{t}")').fetchall()
            notnull_cols = [r[1] for r in cols_info if r[3] == 1]
            pk_cols = {r[1] for r in cols_info if r[5] > 0}
            single_int_pk = len(pk_cols) == 1 and any(
                r[1] in pk_cols and r[2].upper() == "INTEGER" for r in cols_info
            )
            for col in notnull_cols:
                nulls = con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{col}" IS NULL').fetchone()[0]
                checks.append(CheckResult("D4-notnull", t, nulls == 0, f"{col} nulls={nulls}"))
            for idx in con.execute(f'PRAGMA index_list("{t}")').fetchall():
                idx_name, is_unique, origin = idx[1], idx[2], idx[3]
                if not is_unique or origin not in ("u", "pk"):
                    continue
                idx_cols = [r[2] for r in con.execute(f'PRAGMA index_info("{idx_name}")')]
                if single_int_pk and set(idx_cols) == pk_cols:
                    continue  # rowid alias is inherently unique
                col_list = ", ".join(f'"{c}"' for c in idx_cols)
                # SQL standard: UNIQUE indexes allow repeated NULLs — exclude
                # rows with any NULL key column from the duplicate scan.
                not_null_where = " AND ".join(f'"{c}" IS NOT NULL' for c in idx_cols)
                dup = con.execute(
                    f'SELECT COUNT(*) FROM (SELECT {col_list} FROM "{t}" WHERE {not_null_where} '
                    f"GROUP BY {col_list} HAVING COUNT(*) > 1)"
                ).fetchone()[0]
                checks.append(CheckResult("D4-unique", t, dup == 0, f"({col_list}) dup_groups={dup}"))

        # D5 semantic invariants
        for t, expr, desc in semantic:
            if counts.get(t, DEFAULT_COUNT) is None:
                continue
            bad = con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE NOT ({expr})').fetchone()[0]
            checks.append(CheckResult("D5-semantic", t, bad == 0, f"{desc}: violations={bad}"))
    finally:
        con.close()
    return checks


def run_schema(name: str, schema: dict) -> DbReport:
    report = DbReport(name)
    db_path = DB_DIR / f"{name}.db"
    build_db(db_path, schema["ddl"])
    report.fill_errors, report.fill_seconds, report.rows_filled = fill_db(db_path, schema["counts"])
    for t, err in report.fill_errors.items():
        report.checks.append(CheckResult("D0-fill", t, False, err))
    report.checks.extend(verify_db(db_path, schema["counts"], schema.get("semantic", [])))
    return report


def main() -> int:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    selected = sys.argv[1:] or list(SCHEMAS)
    reports: list[DbReport] = []
    for name in selected:
        t0 = time.perf_counter()
        rep = run_schema(name, SCHEMAS[name])
        reports.append(rep)
        n_fail = len(rep.failed)
        status = "PASS" if n_fail == 0 else f"FAIL({n_fail})"
        print(
            f"[{status}] {name:<12} rows={rep.rows_filled:<6} "
            f"fill={rep.fill_seconds:5.1f}s checks={len(rep.checks):<4} total={time.perf_counter() - t0:5.1f}s"
        )
        for c in rep.failed[:8]:
            print(f"    ✗ {c.dim:<12} {c.table:<16} {c.detail}")

    print("\n" + "=" * 78)
    print(f"{'schema':<12} {'fill':<6} {'D1-rows':<9} {'D2-fk':<7} {'D3-check':<9} {'D4-uni/nn':<10} {'D5-sem':<7}")
    all_ok = True
    for rep in reports:
        dims = ["D0-fill", "D1-rows", "D2-fk", "D3-check", "D4-unique", "D4-notnull", "D5-semantic"]

        def dim_status(prefixes: tuple[str, ...]) -> str:
            sel = [c for c in rep.checks if c.dim in prefixes]
            if not sel:
                return "-"
            bad = sum(1 for c in sel if not c.ok)
            return "ok" if bad == 0 else f"FAIL/{bad}"

        row = (
            f"{rep.name:<12} {dim_status(('D0-fill',)):<6} {dim_status(('D1-rows',)):<9} "
            f"{dim_status(('D2-fk',)):<7} {dim_status(('D3-check',)):<9} "
            f"{dim_status(('D4-unique', 'D4-notnull')):<10} {dim_status(('D5-semantic',)):<7}"
        )
        print(row)
        if rep.failed:
            all_ok = False
    print("=" * 78)
    print(f"OVERALL: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
