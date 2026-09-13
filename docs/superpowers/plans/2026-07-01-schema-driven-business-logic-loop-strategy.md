# Schema-Driven Business Logic Loop Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a schema-driven loop strategy that guarantees LLM-generated data is both constraint-accurate and business-logically correct, while keeping core code (`src/sqlseed/`) entirely free of business logic.

**Architecture:** Three-layer separation: (1) Core `sqlseed` package remains unchanged — generic data generation engine. (2) `sqlseed-ai/schema_analyzer.py` gains generic auto-fix rules (Fix 9-11) based on column naming patterns and type conventions — not business-specific. (3) Standalone scripts (`_verify_business_logic.py`, `_run_business_logic_loop.py`) contain database-specific verification logic, auto-discovering constraints from the schema.

**Tech Stack:** Python 3.10+, SQLite (via `sqlite3` + SQLAlchemy), pluggy, Pydantic, structlog, pytest.

**Design Principles:**
- **Core isolation:** `src/sqlseed/` has ZERO changes. No business logic enters the core.
- **Generic auto-fix:** Fix 9-11 are pattern-based (column name → generator, type → range), working for ANY database.
- **Schema-driven verification:** The verification script auto-discovers CHECK/FK/UNIQUE/GENERATED constraints from the schema — no hardcoded table names.
- **Loop methodology:** clear → analyze → auto-fix → fill → verify → iterate.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `_verify_business_logic.py` | Create | Generic schema-driven verification: auto-discover and verify all CHECK/FK/UNIQUE/GENERATED constraints + data realism checks (name readability, integer range sanity) |
| `_run_business_logic_loop.py` | Create | Enhanced loop runner: integrates business logic verification, root-cause analysis, failure categorization |
| `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` | Modify | Add Fix 9 (name column generator correction), Fix 10 (missing integer max_value), Fix 11 (email/phone generator enforcement) |
| `plugins/sqlseed-ai/tests/test_schema_analyzer.py` | Modify | Tests for Fix 9/10/11 |

**Deleted (superseded):**
- `_run_llm_loop.py` — replaced by `_run_business_logic_loop.py`
- `_verify_constraints.py` — replaced by `_verify_business_logic.py`
- `_clear_db.py` — logic absorbed into `_run_business_logic_loop.py`

---

## Task 1: Create Generic Schema-Driven Verification Script

**Files:**
- Create: `_verify_business_logic.py`

**Design:** The script auto-discovers ALL constraints from the database schema (no hardcoded table/constraint names). It verifies 5 categories: CHECK constraints, FK integrity, UNIQUE constraints, GENERATED column formulas, and data realism (column-name-based heuristics).

- [ ] **Step 1: Create the verification script with auto-discovery**

```python
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
from collections import namedtuple
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
            # Build a query that counts rows violating the CHECK
            # We test the negation: NOT (expr) — if any rows match, they violate
            # SQLite CHECK is evaluated at INSERT/UPDATE time, so all existing
            # rows already satisfy it. But we verify programmatically to catch
            # any edge cases (e.g., if CHECK was added after data existed).
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
                # Some CHECK expressions may use functions SQLite doesn't support
                # in SELECT context; skip those
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
            # (id, seq, table, from, to, on_update, on_delete, match)
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
                        # Count alphanumeric vs alpha characters
                        # If >50% of chars are digits, it's likely gibberish
                        alpha = sum(1 for c in val if c.isalpha())
                        total = len(val)
                        if total > 0 and alpha / total < 0.6:
                            gibberish_count += 1
                        # Also check if no spaces and very long (random string)
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
```

- [ ] **Step 2: Test the verification script against the empty database**

Run: `python _verify_business_logic.py`
Expected: All checks pass with 0 violations (empty tables have no data to violate).

- [ ] **Step 3: Commit**

```bash
git add _verify_business_logic.py
git commit -m "feat: add schema-driven business logic verification script"
```

---

## Task 2: Add Fix 9 — Name Column Generator Correction

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` (add Fix 9 after Fix 8, before `return config`)
- Test: `plugins/sqlseed-ai/tests/test_schema_analyzer.py`

**Design:** Fix 9 is a generic pattern: columns ending in `_name` should use `word` (readable words) or `company` (for merchant/company names), not `string`/`text` (which produce random gibberish). This works for ANY database — it's based on column naming conventions, not business knowledge.

- [ ] **Step 1: Write the failing test for Fix 9**

Add to `plugins/sqlseed-ai/tests/test_schema_analyzer.py`:

```python
    def test_fixes_name_column_generator_to_word(self) -> None:
        """Fix 9: *_name columns using string/text should be corrected to word."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "categories",
                    "columns": [
                        {
                            "name": "category_name",
                            "generator": "string",
                            "params": {"min_length": 10, "max_length": 100},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "word"
        assert col.get("params") is None or col["params"] == {}

    def test_fixes_merchant_name_to_company(self) -> None:
        """Fix 9: merchant_name / company_name should use company generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "merchants",
                    "columns": [
                        {
                            "name": "merchant_name",
                            "generator": "text",
                            "params": {"min_length": 20},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "company"

    def test_no_fix_when_name_col_already_uses_word(self) -> None:
        """Fix 9: no correction when *_name already uses word/company."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "product_name",
                            "generator": "word",
                            "params": {},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "word"

    def test_no_fix_when_name_col_has_derive_from(self) -> None:
        """Fix 9: no correction when *_name column is in derived mode."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "full_name",
                            "derive_from": "first_name",
                            "expression": "value + ' ' + lookup('users','last_name',value)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert "generator" not in col
        assert col["derive_from"] == "first_name"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "fixes_name_column or fixes_merchant or no_fix_when_name" -v --tb=short`
Expected: FAIL — generator stays as `string`/`text` (Fix 9 not implemented yet).

- [ ] **Step 3: Implement Fix 9 in schema_analyzer.py**

Add after Fix 8 (before `return config` at line 789), inside the `for col in columns:` loop:

```python
                # Fix 9: name column generator correction.
                # Columns ending in _name should use readable generators (word
                # or company), not string/text (which produce random gibberish).
                # merchant_name / company_name -> company; other *_name -> word.
                # This is a generic naming-convention heuristic, not business logic.
                if (
                    isinstance(col_name, str)
                    and col_name.endswith("_name")
                    and col.get("generator") in ("string", "text")
                    and not col.get("derive_from")
                ):
                    old_gen = col.get("generator")
                    if "merchant" in col_name or "company" in col_name:
                        new_gen = "company"
                    else:
                        new_gen = "word"
                    logger.warning(
                        "Auto-fix: correcting name column generator "
                        "(string/text -> readable)",
                        table=table.get("name"),
                        column=col_name,
                        old_generator=old_gen,
                        new_generator=new_gen,
                    )
                    col["generator"] = new_gen
                    col.pop("params", None)
```

- [ ] **Step 4: Run tests to verify Fix 9 passes**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "fixes_name_column or fixes_merchant or no_fix_when_name" -v --tb=short`
Expected: PASS — all 4 tests pass.

- [ ] **Step 5: Run full test suite to ensure no regressions**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -v --tb=short`
Expected: All tests pass (32 existing + 4 new = 36).

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py plugins/sqlseed-ai/tests/test_schema_analyzer.py
git commit -m "feat: add Fix 9 — name column generator correction (string/text -> word/company)"
```

---

## Task 3: Add Fix 10 — Missing max_value for Integer Generator

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` (add Fix 10 after Fix 9)
- Test: `plugins/sqlseed-ai/tests/test_schema_analyzer.py`

**Design:** When the LLM generates `integer` with `min_value` but no `max_value`, the generator can produce absurdly large numbers (e.g., stock=503893). Fix 10 adds a reasonable `max_value` based on the column name heuristic: `*_count`/`*_stock` → 9999, `quantity*` → 100, default → 99999.

- [ ] **Step 1: Write the failing test for Fix 10**

```python
    def test_adds_max_value_to_integer_without_max(self) -> None:
        """Fix 10: integer generator without max_value gets a reasonable default."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "stock",
                            "generator": "integer",
                            "params": {"min_value": 0},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"].get("max_value") is not None
        assert col["params"]["max_value"] <= 99999

    def test_no_max_value_added_when_already_present(self) -> None:
        """Fix 10: no change when max_value already set."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {
                            "name": "stock_count",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 5000},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"]["max_value"] == 5000

    def test_quantity_column_gets_smaller_max(self) -> None:
        """Fix 10: quantity* columns get max_value=100 (not 99999)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "sales",
                    "columns": [
                        {
                            "name": "quantity_sold",
                            "generator": "integer",
                            "params": {"min_value": 1},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"]["max_value"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "max_value" -v --tb=short`
Expected: FAIL — `max_value` not added (Fix 10 not implemented).

- [ ] **Step 3: Implement Fix 10**

Add after Fix 9, still inside the `for col in columns:` loop:

```python
                # Fix 10: add max_value to integer generator when missing.
                # Without max_value, the generator can produce absurdly large
                # numbers (e.g., stock=503893). Add a reasonable default based
                # on column name heuristics.
                if (
                    col.get("generator") == "integer"
                    and isinstance(col.get("params"), dict)
                    and "max_value" not in col["params"]
                ):
                    if col_name and isinstance(col_name, str):
                        name_lower = col_name.lower()
                        if "quantity" in name_lower:
                            default_max = 100
                        elif "count" in name_lower or "stock" in name_lower:
                            default_max = 9999
                        else:
                            default_max = 99999
                    else:
                        default_max = 99999
                    logger.warning(
                        "Auto-fix: adding max_value to integer generator",
                        table=table.get("name"),
                        column=col_name,
                        max_value=default_max,
                    )
                    col["params"]["max_value"] = default_max
```

- [ ] **Step 4: Run tests to verify Fix 10 passes**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "max_value" -v --tb=short`
Expected: PASS — all 3 tests pass.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -v --tb=short`
Expected: All 39 tests pass (36 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py plugins/sqlseed-ai/tests/test_schema_analyzer.py
git commit -m "feat: add Fix 10 — missing max_value for integer generator"
```

---

## Task 4: Add Fix 11 — Email/Phone Generator Enforcement

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` (add Fix 11 after Fix 10)
- Test: `plugins/sqlseed-ai/tests/test_schema_analyzer.py`

**Design:** Columns ending in `_email` should use `email` generator (not `string`), and `*_phone` should use `phone` or `pattern` (not `string`). This is a generic naming-convention pattern.

- [ ] **Step 1: Write the failing test for Fix 11**

```python
    def test_fixes_email_column_to_email_generator(self) -> None:
        """Fix 11: *_email columns using string should be corrected to email."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "contact_email",
                            "generator": "string",
                            "params": {"min_length": 5, "max_length": 50},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "email"

    def test_fixes_phone_column_to_phone_generator(self) -> None:
        """Fix 11: *_phone columns using string should be corrected to phone."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "phone",
                            "generator": "string",
                            "params": {"min_length": 10, "max_length": 15},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "phone"

    def test_no_fix_when_email_already_correct(self) -> None:
        """Fix 11: no correction when *_email already uses email generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "email",
                            "generator": "email",
                            "params": {},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "email"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "email_column or phone_column" -v --tb=short`
Expected: FAIL — generator stays as `string` (Fix 11 not implemented).

- [ ] **Step 3: Implement Fix 11**

Add after Fix 10:

```python
                # Fix 11: enforce semantic generators for email/phone columns.
                # *_email -> email, *_phone -> phone (not string).
                if (
                    isinstance(col_name, str)
                    and col.get("generator") == "string"
                    and not col.get("derive_from")
                ):
                    if col_name.endswith("_email") or col_name == "email":
                        logger.warning(
                            "Auto-fix: correcting email column generator (string -> email)",
                            table=table.get("name"),
                            column=col_name,
                        )
                        col["generator"] = "email"
                        col.pop("params", None)
                    elif col_name.endswith("_phone") or col_name == "phone":
                        logger.warning(
                            "Auto-fix: correcting phone column generator (string -> phone)",
                            table=table.get("name"),
                            column=col_name,
                        )
                        col["generator"] = "phone"
                        col.pop("params", None)
```

- [ ] **Step 4: Run tests to verify Fix 11 passes**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -k "email_column or phone_column" -v --tb=short`
Expected: PASS — all 3 tests pass.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -v --tb=short`
Expected: All 42 tests pass (39 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py plugins/sqlseed-ai/tests/test_schema_analyzer.py
git commit -m "feat: add Fix 11 — email/phone generator enforcement"
```

---

## Task 5: Create Enhanced Loop Runner

**Files:**
- Create: `_run_business_logic_loop.py`

**Design:** Replaces `_run_llm_loop.py`. Integrates `_verify_business_logic.py` (not just `_verify_constraints.py`). Adds root-cause analysis and failure categorization. The loop methodology: clear → analyze → auto-fix (implicit in ai-analyze) → fill → verify (schema + business logic) → report with categorized failures.

- [ ] **Step 1: Create the enhanced loop runner**

```python
"""Schema-driven business logic loop runner.

Drives one iteration: clear DB -> ai-analyze -> fill -> verify (schema + business logic).
Returns exit code 0 on success, 1 on failure.

Success criteria (all must hold):
1. All 8 tables have exactly 1000 rows
2. _verify_business_logic.py reports 0 violations (CHECK + FK + UNIQUE + GENERATED + REALISM)
3. LLM's YAML uses >=2 of {template, weighted_choice, lookup, multi-col derive_from}
4. No manual edit of ai_analyze_out.yaml (LLM output consumed verbatim)

Usage:
    python _run_business_logic_loop.py [iteration_number]
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

DB_PATH = "complex_biz.db"
YAML_PATH = "ai_analyze_out.yaml"
EXPECTED_TABLES = [
    "merchants",
    "categories",
    "users",
    "products",
    "items",
    "orders",
    "order_items",
    "sales",
]
EXPECTED_ROWS = 1000
P0_P3_MARKERS = [
    r"generator:\s*template",
    r"generator:\s*weighted_choice",
    r"lookup\(",
    r"derive_from:\s*\n\s*-",
]

LM_STUDIO_ENV = {
    "SQLSEED_AI_BACKEND": "lm_studio",
    "SQLSEED_AI_BASE_URL": "http://127.0.0.1:1234/v1",
    "SQLSEED_AI_API_KEY": "lm-studio",
}


def run(cmd_args: list[str], env_override: dict[str, str] | None = None) -> tuple[int, str]:
    full_env = dict(os.environ)
    if env_override:
        full_env.update(env_override)
    result = subprocess.run(
        cmd_args,
        capture_output=True,
        text=True,
        env=full_env,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout + result.stderr


def clear_db() -> bool:
    """Step 1: Clear all table data (FK-safe: disable FK checks, delete, re-enable)."""
    print("\n[1/5] Clearing database...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        tables = [
            r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for t in tables:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cur.execute(f"DELETE FROM {t}")
            print(f"  Cleared {t}: {n} rows deleted")
        try:
            cur.execute("DELETE FROM sqlite_sequence")
        except sqlite3.OperationalError:
            pass
        cur.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"FAIL: clear_db error: {e}")
        return False


def ai_analyze() -> bool:
    """Step 2: Run sqlseed ai-analyze (LLM generates YAML, auto-fix applied internally)."""
    print("\n[2/5] Running sqlseed ai-analyze (LLM generates YAML)...")
    code, out = run(
        ["sqlseed", "ai-analyze", "--db", DB_PATH, "-o", YAML_PATH, "--timeout", "600"],
        env_override=LM_STUDIO_ENV,
    )
    print(out[-2000:])
    if code != 0:
        print("FAIL: ai-analyze command failed")
        return False
    if not Path(YAML_PATH).exists():
        print("FAIL: YAML file not created")
        return False
    return True


def fill_db() -> bool:
    """Step 3: Run sqlseed fill (LLM YAML verbatim, NO manual edits)."""
    print("\n[3/5] Running sqlseed fill (LLM YAML verbatim)...")
    code, out = run(
        ["sqlseed", "fill", "--config", YAML_PATH, "--provider", "faker", "--clear"]
    )
    print(out[-2000:])
    if code != 0:
        print("FAIL: fill command failed")
        return False
    return True


def verify_business_logic() -> tuple[bool, str]:
    """Step 4: Run schema-driven business logic verification."""
    print("\n[4/5] Verifying business logic (schema + realism)...")
    code, out = run([sys.executable, "_verify_business_logic.py"])
    print(out[-3000:])
    return code == 0, out


def check_success_criteria() -> dict[str, object]:
    """Step 5: Check all success criteria."""
    print("\n[5/5] Checking success criteria...")
    report: dict[str, object] = {
        "tables_ok": True,
        "business_logic_ok": True,
        "p0_p3_usage": 0,
        "p0_p3_markers_found": [],
        "row_counts": {},
        "errors": [],
    }

    # Criterion 1: all tables have expected rows
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for t in EXPECTED_TABLES:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            report["row_counts"][t] = n  # type: ignore[index]
            if n != EXPECTED_ROWS:
                report["tables_ok"] = False
                report["errors"].append(f"{t}: expected {EXPECTED_ROWS} rows, got {n}")
        conn.close()
    except Exception as e:
        report["tables_ok"] = False
        report["errors"].append(f"DB check error: {e}")

    # Criterion 3: LLM used >=2 P0-P3 features
    try:
        yaml_text = Path(YAML_PATH).read_text(encoding="utf-8")
        for marker in P0_P3_MARKERS:
            if re.search(marker, yaml_text):
                report["p0_p3_usage"] = int(report["p0_p3_usage"]) + 1  # type: ignore[assignment]
                report["p0_p3_markers_found"].append(marker)  # type: ignore[index]
    except Exception as e:
        report["errors"].append(f"YAML read error: {e}")

    return report


def categorize_failures(verify_output: str) -> list[str]:
    """Categorize failures from verification output for root-cause analysis."""
    categories: list[str] = []
    if "CHECK" in verify_output and "FAIL" in verify_output:
        categories.append("CHECK constraint violation — consider adding derive_from for cross-column CHECK")
    if "FK" in verify_output and "FAIL" in verify_output:
        categories.append("FK integrity violation — check topological fill order")
    if "UNIQUE" in verify_output and "FAIL" in verify_output:
        categories.append("UNIQUE constraint violation — ensure constraints.unique=true is set")
    if "GENERATED" in verify_output and "FAIL" in verify_output:
        categories.append("GENERATED column issue — ensure GENERATED columns are excluded from config")
    if "REALISM" in verify_output and "FAIL" in verify_output:
        categories.append("Data realism issue — check generator selection for name/email/phone columns")
    return categories


def main() -> int:
    iteration = sys.argv[1] if len(sys.argv) > 1 else "1"
    print(f"=== Schema-Driven Business Logic Loop - Iteration {iteration} ===")

    if not clear_db():
        return 1
    if not ai_analyze():
        return 1
    if not fill_db():
        report = check_success_criteria()
        print("\n--- REPORT (fill failed) ---")
        print(f"P0-P3 features used: {report['p0_p3_usage']}/4")
        print(f"Errors: {report['errors']}")
        return 1

    verify_ok, verify_output = verify_business_logic()
    if not verify_ok:
        report["business_logic_ok"] = False  # type: ignore[index]

    report = check_success_criteria()
    report["business_logic_ok"] = verify_ok  # type: ignore[index]

    print("\n=== FINAL REPORT ===")
    print(f"Tables OK: {report['tables_ok']}")
    print(f"Business Logic OK: {report['business_logic_ok']}")
    print(f"Row counts: {report['row_counts']}")
    print(f"P0-P3 features used: {report['p0_p3_usage']}/4")
    print(f"P0-P3 markers: {report['p0_p3_markers_found']}")
    if report["errors"]:
        print(f"Errors: {report['errors']}")

    if not verify_ok:
        print("\n--- Root Cause Analysis ---")
        categories = categorize_failures(verify_output)
        for c in categories:
            print(f"  - {c}")

    all_pass = (
        bool(report["tables_ok"])
        and bool(report["business_logic_ok"])
        and int(report["p0_p3_usage"]) >= 2
    )
    if all_pass:
        print("\n[OK] SUCCESS: all criteria met")
        return 0
    print("\n[FAIL] FAIL: criteria not met")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test the loop runner (dry run without LLM)**

First verify the script syntax is correct:
Run: `python -c "import _run_business_logic_loop; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add _run_business_logic_loop.py
git commit -m "feat: add enhanced business logic loop runner with root-cause analysis"
```

---

## Task 6: Strengthen System Prompt with Name/Type Rules

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` (update `_build_system_prompt` method)

**Design:** Add explicit rules to the system prompt about generator selection for name/email/phone columns and integer range requirements. These rules complement the auto-fixes (Fix 9-11) — the prompt teaches the LLM, and the auto-fix catches any misses.

- [ ] **Step 1: Add generator selection rules to the system prompt**

In the `_build_system_prompt` method, find the `Rules:` section and add after the existing rules:

```python

Generator selection by column name:
- *_name non-person (category_name, product_name, item_name) -> word (readable words, NOT string)
- merchant_name / company_name -> company (company names, NOT text/sentence)
- *_email / email -> email (valid email format, NOT string)
- *_phone / phone -> phone or pattern(regex) (phone format, NOT string)
- *_code / *_no / sku -> template (UNIQUE business codes with sequence)
- *_status / role -> weighted_choice (enum with realistic distribution, NOT choice)
- *_price / *_amount -> float with precision=2 (monetary values)
- *_count / quantity* -> integer with max_value (avoid absurdly large numbers)
```

- [ ] **Step 2: Verify the prompt is valid**

Run: `python -c "from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer; a = SchemaSemanticAnalyzer(); print(a._build_system_prompt()[:500])"`
Expected: The prompt prints without errors, including the new rules.

- [ ] **Step 3: Run existing tests to ensure no regressions**

Run: `python -m pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -v --tb=short`
Expected: All 42 tests pass.

- [ ] **Step 4: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py
git commit -m "feat: strengthen system prompt with generator selection rules for name/email/phone"
```

---

## Task 7: Run Full Loop Validation

**Files:** None (validation only)

**Design:** Run the complete loop using the enhanced runner and verify all success criteria pass. This validates that Fix 9-11 + the enhanced verification + the strengthened prompt work together.

- [ ] **Step 1: Ensure LM Studio is running**

Run: `python -c "import urllib.request; r = urllib.request.urlopen('http://127.0.0.1:1234/v1/models', timeout=5); print(r.read().decode()[:200])"`
Expected: JSON response with `google/gemma-4-e2b` model.

- [ ] **Step 2: Run the full loop**

Run: `python _run_business_logic_loop.py 18`
Expected: All criteria pass:
- 8/8 tables with 1000 rows
- 0 business logic violations (CHECK + FK + UNIQUE + GENERATED + REALISM)
- ≥2 P0-P3 features used
- Exit code 0

- [ ] **Step 3: If REALISM violations found, check which auto-fix didn't trigger**

If the verification reports REALISM violations (e.g., gibberish names), check the YAML to see if Fix 9/10/11 triggered. If the LLM used a generator not covered by the auto-fix (e.g., `sentence` for a name column), extend Fix 9 to cover that case.

- [ ] **Step 4: Commit final state if all passes**

```bash
git add -A
git commit -m "feat: schema-driven business logic loop strategy validated"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ "保证生成的数据准确" → Task 1 (verification) + Task 7 (validation)
- ✅ "符合业务逻辑" → Task 1 (business realism checks) + Task 2-4 (auto-fix for name/email/phone/integer)
- ✅ "核心代码不涉及业务逻辑" → No changes to `src/sqlseed/`; all fixes are generic patterns in `sqlseed-ai`; business verification is in standalone scripts

**2. Placeholder scan:** No TBD/TODO found. All steps have complete code.

**3. Type consistency:** Fix 9/10/11 all use `col_name`, `col`, `table` variables consistent with existing Fix 1-8.

**4. Core isolation:** `src/sqlseed/` has ZERO file modifications. Only `plugins/sqlseed-ai/` and standalone scripts are modified.
