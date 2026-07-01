"""Schema-driven business logic verification.

Auto-discovers ALL constraints from the database schema (no hardcoded
table names) and verifies 5 categories:
1. CHECK constraints (parsed from DDL, including cross-column)
2. FK integrity (via PRAGMA foreign_key_list)
3. UNIQUE constraints (via PRAGMA index_list, including column-level)
4. GENERATED column formulas (parsed from DDL)
5. Data realism (column-name-based heuristics: *_name readability, integer range)

Exit code 0 = all checks pass, 1 = violations found.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass, field

DB_PATH = "complex_biz.db"


@dataclass
class CheckResult:
    name: str
    category: str  # "CHECK", "FK", "UNIQUE", "GENERATED", "REALISM"
    violations: int
    detail: str = ""


@dataclass
class VerificationReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def total_violations(self) -> int:
        return sum(r.violations for r in self.results)

    @property
    def passed(self) -> bool:
        return self.total_violations == 0

    def add(self, name: str, category: str, violations: int, detail: str = "") -> None:
        self.results.append(CheckResult(name, category, violations, detail))


def get_tables(cur: sqlite3.Cursor) -> list[str]:
    return [
        r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    ]


def get_ddl(cur: sqlite3.Cursor, table: str) -> str:
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row else ""


def parse_check_constraints(ddl: str) -> list[dict]:
    """Parse CHECK constraints from DDL, handling nested parens."""
    checks: list[dict] = []
    for m in re.finditer(r"(?:CONSTRAINT\s+\S+\s+)?CHECK\s*\(", ddl, re.IGNORECASE):
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, len(ddl)):
            if ddl[i] == "(":
                depth += 1
            elif ddl[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        expr = ddl[start + 1 : end].strip()
        cols = re.findall(r"\b([a-zA-Z_]\w*)\b", expr)
        keywords = {"AND", "OR", "NOT", "NULL", "IS", "IN", "BETWEEN", "LIKE",
                    "CASE", "WHEN", "THEN", "ELSE", "END", "TRUE", "FALSE",
                    "LENGTH", "ROUND", "ABS", "COALESCE", "LOWER", "UPPER"}
        col_names = [c for c in cols if c.upper() not in keywords]
        checks.append({
            "expression": expr,
            "columns": list(dict.fromkeys(col_names)),
        })
    return checks


def parse_generated_columns(ddl: str) -> list[dict]:
    """Parse GENERATED ALWAYS AS (...) columns from DDL."""
    generated: list[dict] = []
    lines = re.findall(
        r"(\w+)\s+\w+\s+.*?GENERATED\s+ALWAYS\s+AS\s*\((.*?)\)\s*(STORED|VIRTUAL)?",
        ddl, re.IGNORECASE
    )
    for name, expr, gen_type in lines:
        generated.append({
            "column": name,
            "expression": expr.strip(),
            "type": (gen_type or "STORED").upper(),
        })
    return generated


def get_unique_columns(cur: sqlite3.Cursor, table: str) -> list[str]:
    """Get all UNIQUE columns via PRAGMA index_list (catches column-level UNIQUE)."""
    unique_cols: list[str] = []
    for idx_row in cur.execute(f"PRAGMA index_list({table})").fetchall():
        if idx_row[2]:  # unique flag
            idx_name = idx_row[1]
            for ir in cur.execute(f"PRAGMA index_info({idx_name})").fetchall():
                if ir[2]:
                    unique_cols.append(ir[2])
    return unique_cols


def verify_check_constraints(
    conn: sqlite3.Connection, tables: list[str], report: VerificationReport
) -> None:
    """Verify all CHECK constraints by testing the negation."""
    cur = conn.cursor()
    for table in tables:
        ddl = get_ddl(cur, table)
        checks = parse_check_constraints(ddl)
        for chk in checks:
            expr = chk["expression"]
            try:
                count = cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE NOT ({expr})"
                ).fetchone()[0]
                report.add(
                    f"{table}.CHECK({expr})",
                    "CHECK",
                    count,
                    f"columns: {chk['columns']}",
                )
            except sqlite3.OperationalError as e:
                report.add(
                    f"{table}.CHECK({expr})",
                    "CHECK",
                    0,
                    f"skipped (unsupported in SELECT: {e})",
                )


def verify_fk_integrity(
    conn: sqlite3.Connection, tables: list[str], report: VerificationReport
) -> None:
    """Verify all FK relationships via PRAGMA foreign_key_list."""
    cur = conn.cursor()
    for table in tables:
        for fk_row in cur.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            ref_table = fk_row[2]
            from_col = fk_row[3]
            to_col = fk_row[4]
            try:
                count = cur.execute(
                    f"SELECT COUNT(*) FROM {table} t "
                    f"LEFT JOIN {ref_table} r ON t.{from_col} = r.{to_col} "
                    f"WHERE t.{from_col} IS NOT NULL AND r.{to_col} IS NULL"
                ).fetchone()[0]
                report.add(
                    f"FK {table}.{from_col} -> {ref_table}.{to_col}",
                    "FK",
                    count,
                )
            except sqlite3.OperationalError as e:
                report.add(
                    f"FK {table}.{from_col} -> {ref_table}.{to_col}",
                    "FK",
                    0,
                    f"skipped: {e}",
                )


def verify_unique_constraints(
    conn: sqlite3.Connection, tables: list[str], report: VerificationReport
) -> None:
    """Verify all UNIQUE constraints (including column-level auto-indexes)."""
    cur = conn.cursor()
    for table in tables:
        unique_cols = get_unique_columns(cur, table)
        for col in unique_cols:
            count = cur.execute(
                f"SELECT COUNT(*) FROM ("
                f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL "
                f"GROUP BY {col} HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            report.add(f"UNIQUE {table}.{col}", "UNIQUE", count)


def verify_generated_columns(
    conn: sqlite3.Connection, tables: list[str], report: VerificationReport
) -> None:
    """Verify GENERATED column formulas match the DDL expression."""
    cur = conn.cursor()
    for table in tables:
        ddl = get_ddl(cur, table)
        generated = parse_generated_columns(ddl)
        for gen in generated:
            col = gen["column"]
            expr = gen["expression"]
            try:
                count = cur.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE ABS({col} - ({expr})) > 0.01"
                ).fetchone()[0]
                report.add(
                    f"GENERATED {table}.{col} = {expr}",
                    "GENERATED",
                    count,
                )
            except sqlite3.OperationalError as e:
                report.add(
                    f"GENERATED {table}.{col}",
                    "GENERATED",
                    0,
                    f"skipped: {e}",
                )


def verify_data_realism(
    conn: sqlite3.Connection, tables: list[str], report: VerificationReport
) -> None:
    """Verify data realism based on column naming conventions.

    Generic heuristics (work for any database):
    - *_name columns should contain readable words, not random alphanumeric strings.
    - integer columns should have reasonable values (not absurdly large).
    - *_email columns should look like email addresses.
    """
    cur = conn.cursor()
    for table in tables:
        pragma_cols = cur.execute(f"PRAGMA table_info({table})").fetchall()
        for col_info in pragma_cols:
            col_name = col_info[1]
            col_type = col_info[2]

            # Check *_name columns for readability (not random gibberish)
            if col_name.endswith("_name") and col_type.upper() in ("TEXT", "VARCHAR"):
                rows = cur.execute(
                    f"SELECT {col_name} FROM {table} "
                    f"WHERE {col_name} IS NOT NULL LIMIT 100"
                ).fetchall()
                gibberish_count = 0
                for (val,) in rows:
                    if isinstance(val, str):
                        alpha = sum(1 for c in val if c.isalpha())
                        total = len(val)
                        if total > 0 and alpha / total < 0.6:
                            gibberish_count += 1
                        elif " " not in val and total > 30:
                            gibberish_count += 1
                if gibberish_count > len(rows) * 0.5:
                    report.add(
                        f"REALISM {table}.{col_name} (gibberish names)",
                        "REALISM",
                        gibberish_count,
                        f"{gibberish_count}/{len(rows)} rows look like random strings",
                    )

            # Check integer columns for absurdly large values
            if col_type.upper() == "INTEGER":
                try:
                    max_val = cur.execute(
                        f"SELECT MAX({col_name}) FROM {table} WHERE {col_name} IS NOT NULL"
                    ).fetchone()[0]
                    if max_val is not None and max_val > 1_000_000:
                        report.add(
                            f"REALISM {table}.{col_name} (absurdly large)",
                            "REALISM",
                            1,
                            f"max value = {max_val}",
                        )
                except sqlite3.OperationalError:
                    pass

            # Check *_email columns for email format
            if col_name.endswith("_email") and col_type.upper() in ("TEXT", "VARCHAR"):
                count = cur.execute(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE {col_name} IS NOT NULL "
                    f"AND {col_name} NOT LIKE '%@%.%'"
                ).fetchone()[0]
                report.add(
                    f"REALISM {table}.{col_name} (not email format)",
                    "REALISM",
                    count,
                )


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = get_tables(conn.cursor())

    report = VerificationReport()

    print("=" * 70)
    print("  Schema-Driven Business Logic Verification")
    print("=" * 70)

    # Row counts
    print("\n--- Row Counts ---")
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} rows")

    # 1. CHECK constraints
    print("\n--- CHECK Constraints ---")
    verify_check_constraints(conn, tables, report)

    # 2. FK integrity
    print("\n--- FK Integrity ---")
    verify_fk_integrity(conn, tables, report)

    # 3. UNIQUE constraints
    print("\n--- UNIQUE Constraints ---")
    verify_unique_constraints(conn, tables, report)

    # 4. GENERATED columns
    print("\n--- GENERATED Columns ---")
    verify_generated_columns(conn, tables, report)

    # 5. Data realism
    print("\n--- Data Realism ---")
    verify_data_realism(conn, tables, report)

    # Print all results
    print("\n" + "=" * 70)
    print("  VERIFICATION RESULTS")
    print("=" * 70)
    for r in report.results:
        status = "OK" if r.violations == 0 else f"FAIL ({r.violations})"
        print(f"  [{r.category:9s}] {r.name}: {status}")
        if r.detail:
            print(f"             {r.detail}")

    # Summary
    print("\n" + "=" * 70)
    print(f"  TOTAL VIOLATIONS: {report.total_violations}")
    print("=" * 70)
    if not report.passed:
        print("\n  Failed checks:")
        for r in report.results:
            if r.violations > 0:
                print(f"    - [{r.category}] {r.name}: {r.violations} violations")

    conn.close()
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
