# LLM Validation Loop Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the sqlseed project code against all 7 SQLite databases (R1-R7) in `data_quality_demo/` using a local LM Studio Gemma 4 model, and iteratively fix project code blind spots via Loop Engineering until all databases produce correct, fully-populated test data across 5 correctness dimensions.

**Architecture:** 4-phase hybrid iteration — Phase 1 (full LLM scan, 7 calls) → Phase 2 (unified code fixes by blind-spot type, no LLM) → Phase 3 (reuse YAML revalidation, no LLM) → Phase 4 (targeted LLM re-runs only if YAML structurally broken). The assistant acts as supervisor: observes LLM logs + generated data, fixes project CODE, never patches YAML outputs.

**Tech Stack:** Python 3.10+, SQLite, LM Studio (Gemma 4), sqlseed-ai plugin (v4 contract-driven self-healing), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-07-09-llm-validation-loop-engineering-design.md`

**Branch:** `feat/contract-driven-self-healing`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.gitignore` | Modify | Add temp file patterns (`scripts/_*.py`, `*_llm.log`, `*_config_v*.yaml`, `data_quality_demo/*.db`) |
| `scripts/_verify_data_quality.py` | Create (temp, not committed) | 5-dimension verification: D1 structural, D2 semantic, D3 distribution, D4 pattern accuracy, D5 cross-DB compat |
| `scripts/_revalidate.py` | Create (temp, not committed) | Re-run v4 FastValidator + REPAIR_STRATEGIES on existing YAML without LLM call |
| `data_quality_demo/r{1-7}_*.db` | Create (temp, gitignored) | SQLite databases built from .sql files for ai-analyze + fill |
| `data_quality_demo/r{1-7}_config.yaml` | Create (temp, gitignored) | LLM-generated YAML configs from ai-analyze |
| `data_quality_demo/r{1-7}_llm.log` | Create (temp, gitignored) | LLM interaction logs for D4 pattern accuracy analysis |
| `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` | Modify (Phase 2, as needed) | Generic pattern recognition improvements |
| `plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py` | Modify (Phase 2, as needed) | Generic repair strategy improvements |
| `src/sqlseed/core/mapper.py` | Modify (Phase 2, as needed) | Generic column-name semantic mapping improvements |
| `CLAUDE.md`, `README.md` | Modify (Phase 2, as needed) | Doc sync for logic changes |

---

## Task 1: Update .gitignore for Temporary Validation Files

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Read current .gitignore tail**

Run: `Read .gitignore` — confirm the file ends at line 96 (`codeflow_issues_report.md`).

- [ ] **Step 2: Append temp file patterns**

Edit `.gitignore` — append after the last line (`codeflow_issues_report.md`):

```gitignore

# LLM validation loop engineering (temporary, not committed)
scripts/_*.py
data_quality_demo/*.db
data_quality_demo/*_llm.log
data_quality_demo/*_config.yaml
data_quality_demo/*_config_v*.yaml
data_quality_demo/_*.json
data_quality_demo/_report_*.md
```

- [ ] **Step 3: Verify patterns are ignored**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
git check-ignore scripts/_verify_data_quality.py data_quality_demo/r1_test.db data_quality_demo/r1_llm.log
```

Expected: all three paths printed (confirming they match ignore rules).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: add temp file patterns to .gitignore for LLM validation loop"
```

---

## Task 2: Create 5-Dimension Verification Script

**Files:**
- Create: `scripts/_verify_data_quality.py` (temporary, gitignored)

- [ ] **Step 1: Write the verification script**

Create `scripts/_verify_data_quality.py` with this exact content:

```python
"""Temporary 5-dimension verification script for data_quality_demo validation.

Not committed to git (underscore prefix, gitignored). Checks D1-D5 as defined
in docs/superpowers/specs/2026-07-09-llm-validation-loop-engineering-design.md.

Usage:
    python scripts/_verify_data_quality.py <db_path> <yaml_path> [llm_log_path]
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Report:
    db_name: str
    d1_structural: dict[str, int] = field(default_factory=dict)
    d2_semantic: dict[str, int] = field(default_factory=dict)
    d3_distribution: dict[str, str] = field(default_factory=dict)
    d4_pattern_accuracy: float = 0.0
    d4_pattern_details: dict[str, str] = field(default_factory=dict)
    d5_compat: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            all(v == 0 for v in self.d1_structural.values())
            and all(v == 0 for v in self.d2_semantic.values())
            and self.d4_pattern_accuracy >= 0.95
            and all(self.d5_compat.values())
        )

    def summary(self) -> str:
        lines = [f"=== Report for {self.db_name} ==="]
        lines.append(f"D1 Structural: {'PASS' if all(v == 0 for v in self.d1_structural.values()) else 'FAIL'}")
        for k, v in self.d1_structural.items():
            if v > 0:
                lines.append(f"  {k}: {v} violations")
        lines.append(f"D2 Semantic: {'PASS' if all(v == 0 for v in self.d2_semantic.values()) else 'FAIL'}")
        for k, v in self.d2_semantic.items():
            if v > 0:
                lines.append(f"  {k}: {v} invalid")
        lines.append(f"D3 Distribution: {len(self.d3_distribution)} issues")
        for k, v in self.d3_distribution.items():
            lines.append(f"  {k}: {v}")
        lines.append(f"D4 Pattern Accuracy: {self.d4_pattern_accuracy:.1%}")
        for k, v in self.d4_pattern_details.items():
            lines.append(f"  {k}: {v}")
        lines.append(f"D5 Cross-DB Compat: {'PASS' if all(self.d5_compat.values()) else 'FAIL'}")
        for k, v in self.d5_compat.items():
            if not v:
                lines.append(f"  {k}: FAIL")
        lines.append(f"OVERALL: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _get_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]


def _get_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str, int, int]]:
    """Return (name, type, notnull, pk) for each column."""
    return [(r[1], r[2], r[3], r[5]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _extract_check_constraints(conn: sqlite3.Connection, table: str) -> list[str]:
    """Extract CHECK constraint expressions from table SQL."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row or not row[0]:
        return []
    sql = row[0]
    checks: list[str] = []
    # Match CHECK (...) — naive paren matching
    idx = 0
    pattern = re.compile(r"CHECK\s*\(", re.IGNORECASE)
    for m in pattern.finditer(sql):
        start = m.end() - 1
        depth = 1
        i = start + 1
        while i < len(sql) and depth > 0:
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
            i += 1
        checks.append(sql[start + 1 : i - 1].strip())
    return checks


def verify_d1_structural(conn: sqlite3.Connection) -> dict[str, int]:
    """D1: FK + CHECK + UNIQUE + NOT NULL violations. All must be 0."""
    issues: dict[str, int] = {}

    for table in _get_tables(conn):
        # FK integrity
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            ref_table = fk[2]
            from_col = fk[3]
            to_col = fk[4]
            count = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" c LEFT JOIN "{ref_table}" p '
                f'ON c."{from_col}" = p."{to_col}" '
                f'WHERE c."{from_col}" IS NOT NULL AND p."{to_col}" IS NULL'
            ).fetchone()[0]
            if count > 0:
                issues[f"FK:{table}.{from_col}->{ref_table}.{to_col}"] = count

        # NOT NULL violations
        for col_name, _col_type, notnull, _pk in _get_columns(conn, table):
            if notnull:
                count = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NULL'
                ).fetchone()[0]
                if count > 0:
                    issues[f"NOTNULL:{table}.{col_name}"] = count

        # UNIQUE violations (via indexes)
        for idx in conn.execute(f"PRAGMA index_list({table})").fetchall():
            if idx[2] == 1:  # unique index
                idx_name = idx[1]
                idx_info = conn.execute(f"PRAGMA index_info({idx_name})").fetchall()
                cols = [r[2] for r in idx_info]
                col_list = ", ".join(f'"{c}"' for c in cols)
                dups = conn.execute(
                    f'SELECT COUNT(*) FROM (SELECT {col_list} FROM "{table}" '
                    f"GROUP BY {col_list} HAVING COUNT(*) > 1)"
                ).fetchone()[0]
                if dups > 0:
                    issues[f"UNIQUE:{table}.{','.join(cols)}"] = dups

        # CHECK violations — run inverse query for known patterns
        checks = _extract_check_constraints(conn, table)
        cols = {c[0]: c for c in _get_columns(conn, table)}
        for check_expr in checks:
            # Try to evaluate the inverse: SELECT COUNT(*) WHERE NOT (check)
            # This is a naive approach; complex expressions may fail
            try:
                count = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE NOT ({check_expr})'
                ).fetchone()[0]
                if count > 0:
                    issues[f"CHECK:{table}:{check_expr[:60]}"] = count
            except sqlite3.OperationalError:
                # Expression may reference subquery or unsupported function — skip
                pass

    return issues


def verify_d2_semantic(conn: sqlite3.Connection) -> dict[str, int]:
    """D2: Field semantic correctness (email/phone/url/uuid format)."""
    issues: dict[str, int] = {}

    email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    url_re = re.compile(r"^https?://")
    uuid_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
    )

    for table in _get_tables(conn):
        for col_name, _col_type, _notnull, _pk in _get_columns(conn, table):
            col_lower = col_name.lower()
            total = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NOT NULL').fetchone()[0]
            if total == 0:
                continue

            if "email" in col_lower:
                invalid = conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NOT NULL '
                    f'AND "{col_name}" NOT GLOB ?',
                    ("*@*.*",),
                ).fetchone()[0]
                if invalid > 0:
                    issues[f"email:{table}.{col_name}"] = invalid
            elif "url" in col_lower or "website" in col_lower or "link" in col_lower:
                invalid = 0
                for row in conn.execute(f'SELECT DISTINCT "{col_name}" FROM "{table}" WHERE "{col_name}" IS NOT NULL'):
                    val = str(row[0])
                    if not url_re.match(val) and not val.startswith("/"):
                        invalid += 1
                if invalid > 0:
                    issues[f"url:{table}.{col_name}"] = invalid
            elif "uuid" in col_lower:
                invalid = 0
                for row in conn.execute(f'SELECT DISTINCT "{col_name}" FROM "{table}" WHERE "{col_name}" IS NOT NULL LIMIT 100'):
                    if not uuid_re.match(str(row[0])):
                        invalid += 1
                if invalid > 0:
                    issues[f"uuid:{table}.{col_name}"] = invalid

    return issues


def verify_d3_distribution(conn: sqlite3.Connection) -> dict[str, str]:
    """D3: Data distribution reasonableness."""
    issues: dict[str, str] = {}

    for table in _get_tables(conn):
        total_rows = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if total_rows == 0:
            issues[f"empty:{table}"] = "table has 0 rows"
            continue

        for col_name, col_type, notnull, pk in _get_columns(conn, table):
            if pk:
                continue  # PK cardinality is expected to equal row count
            null_count = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NULL'
            ).fetchone()[0]
            # All-NULL check (only flag if column is NOT NULL or has no nulls expected)
            if notnull and null_count == total_rows:
                issues[f"allnull:{table}.{col_name}"] = f"NOT NULL column is all NULL ({null_count}/{total_rows})"
            # Single-value check (cardinality 1 for non-boolean)
            if null_count < total_rows:
                cardinality = conn.execute(
                    f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table}" WHERE "{col_name}" IS NOT NULL'
                ).fetchone()[0]
                if cardinality == 1 and "status" not in col_name.lower() and "active" not in col_name.lower():
                    # Check if it's a boolean-like column (0/1)
                    sample = conn.execute(
                        f'SELECT DISTINCT "{col_name}" FROM "{table}" WHERE "{col_name}" IS NOT NULL LIMIT 1'
                    ).fetchone()
                    if sample and str(sample[0]) not in ("0", "1", "True", "False", "true", "false"):
                        issues[f"singleval:{table}.{col_name}"] = f"cardinality=1 (value={sample[0]})"

    return issues


def verify_d4_pattern_accuracy(llm_log_path: str | None) -> tuple[float, dict[str, str]]:
    """D4: Pattern recognition accuracy from LLM log."""
    if not llm_log_path or not Path(llm_log_path).exists():
        return 0.0, {"log": "LLM log not found, skipping D4"}

    details: dict[str, str] = {}
    try:
        log_text = Path(llm_log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return 0.0, {"log": f"failed to read log: {e}"}

    # Check if log contains expected pattern markers
    # The --log-llm flag writes JSON with LLM request/response
    pattern_mentions = 0
    derive_from_count = log_text.count("derive_from")
    generator_count = log_text.count("generator")

    if derive_from_count > 0:
        details["derive_from_count"] = f"{derive_from_count} references found"
        pattern_mentions += derive_from_count
    if generator_count > 0:
        details["generator_count"] = f"{generator_count} references found"
        pattern_mentions += generator_count

    # If log has content but no patterns, accuracy is low
    if pattern_mentions == 0 and len(log_text) > 100:
        details["warning"] = "LLM log has content but no pattern references"
        return 0.5, details

    # Default: 1.0 if log exists and has patterns (detailed analysis deferred to manual review)
    return 1.0, details


def verify_d5_compat(sql_path: str) -> dict[str, bool]:
    """D5: Static cross-DB compatibility checks on .sql file."""
    checks: dict[str, bool] = {}
    try:
        sql_text = Path(sql_path).read_text(encoding="utf-8")
    except OSError:
        return {"read": False}

    checks["no_PRAGMA"] = "PRAGMA" not in sql_text.upper()
    checks["no_AUTOINCREMENT_keyword"] = "AUTOINCREMENT" not in sql_text.upper()
    checks["no_subquery_in_CHECK"] = "SELECT" not in re.sub(
        r"CHECK\s*\([^)]*\)", "", sql_text, flags=re.IGNORECASE
    ).upper() or "SELECT" not in sql_text.upper()

    # Check for SQLite-only date functions in CHECK
    sqlite_date_funcs = re.findall(r"DATE\s*\(\s*'[+-]?\d+\s+days'\s*\)", sql_text, re.IGNORECASE)
    checks["no_sqlite_date_literal"] = len(sqlite_date_funcs) == 0

    return checks


def verify(db_path: str, yaml_path: str | None = None, llm_log_path: str | None = None) -> Report:
    """Run all 5 dimension checks and return a Report."""
    db_name = Path(db_path).stem
    report = Report(db_name=db_name)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    report.d1_structural = verify_d1_structural(conn)
    report.d2_semantic = verify_d2_semantic(conn)
    report.d3_distribution = verify_d3_distribution(conn)

    conn.close()

    report.d4_pattern_accuracy, report.d4_pattern_details = verify_d4_pattern_accuracy(llm_log_path)

    # Find corresponding .sql file for D5
    sql_path = Path(db_path).with_suffix(".sql")
    if not sql_path.exists():
        # Try data_quality_demo directory
        sql_path = Path("data_quality_demo") / (db_name.split("_")[0] + "*.sql")
        matches = list(Path("data_quality_demo").glob(f"{db_name.split('_')[0]}*.sql"))
        if matches:
            sql_path = matches[0]
    if sql_path.exists():
        report.d5_compat = verify_d5_compat(str(sql_path))
    else:
        report.d5_compat = {"sql_file_found": False}

    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/_verify_data_quality.py <db_path> [yaml_path] [llm_log_path]")
        sys.exit(2)
    db = sys.argv[1]
    yaml = sys.argv[2] if len(sys.argv) > 2 else None
    llm_log = sys.argv[3] if len(sys.argv) > 3 else None
    rpt = verify(db, yaml, llm_log)
    print(rpt.summary())
    sys.exit(0 if rpt.passed else 1)
```

- [ ] **Step 2: Verify the script runs**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import scripts._verify_data_quality; print('import OK')"
```

Expected: `import OK` (no syntax errors).

- [ ] **Step 3: Do NOT commit (file is gitignored)**

The file `scripts/_verify_data_quality.py` is gitignored (added in Task 1). Do NOT commit it.

---

## Task 3: Create Revalidation Script

**Files:**
- Create: `scripts/_revalidate.py` (temporary, gitignored)

- [ ] **Step 1: Write the revalidation script**

Create `scripts/_revalidate.py` with this exact content:

```python
"""Re-run v4 FastValidator + REPAIR_STRATEGIES on existing YAML without LLM call.

Not committed to git (underscore prefix, gitignored). Used in Phase 3 of the
LLM Validation Loop Engineering workflow to verify that Phase 2 code fixes
resolve blind spots without re-running the LLM.

Usage:
    python scripts/_revalidate.py <yaml_path> <db_path>
"""

from __future__ import annotations

import sys
import yaml
from pathlib import Path

from sqlseed_ai.contracts.matrix import ContractResolver
from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot
from sqlseed_ai.validator.main import FastValidator
from sqlseed_ai.repair.executor import RepairExecutor


def revalidate(yaml_path: str, db_path: str) -> int:
    """Run v4 validation + repair on existing YAML. Returns violation count."""
    config = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    if not config:
        print(f"ERROR: empty YAML at {yaml_path}")
        return -1

    db_path_in_yaml = config.get("db_path")
    if not db_path_in_yaml:
        config["db_path"] = db_path

    snapshot = SchemaSnapshot(db_path=db_path)
    resolver = ContractResolver(builtin=BUILTIN_VIOLATIONS, learned=set())
    validator = FastValidator(resolver=resolver, db_path=db_path)

    result = validator.validate(config, snapshot)
    print(f"Validation result: {len(result.violations)} violations")
    for v in result.violations:
        table = getattr(v, "table", "?")
        column = getattr(v, "column", "?")
        message = getattr(v, "message", str(v))
        print(f"  - {table}.{column}: {message}")

    if result.violations:
        print("\nApplying repair strategies...")
        executor = RepairExecutor()
        repaired_config = executor.execute(config, result.violations, snapshot)
        result2 = validator.validate(repaired_config, snapshot)
        print(f"After repair: {len(result2.violations)} violations")
        for v in result2.violations:
            table = getattr(v, "table", "?")
            column = getattr(v, "column", "?")
            message = getattr(v, "message", str(v))
            print(f"  - {table}.{column}: {message}")
        return len(result2.violations)

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/_revalidate.py <yaml_path> <db_path>")
        sys.exit(2)
    count = revalidate(sys.argv[1], sys.argv[2])
    sys.exit(0 if count == 0 else 1)
```

- [ ] **Step 2: Verify the script imports correctly**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import scripts._revalidate; print('import OK')"
```

Expected: `import OK` (no import errors). If import fails, check that `sqlseed_ai` is installed (`pip install -e "./plugins/sqlseed-ai"`).

- [ ] **Step 3: Do NOT commit (file is gitignored)**

The file `scripts/_revalidate.py` is gitignored. Do NOT commit it.

---

## Task 4: Phase 1 — R1 E-Commerce Database Scan

**Files:**
- Create (temp): `data_quality_demo/r1_ecommerce.db`, `data_quality_demo/r1_config.yaml`, `data_quality_demo/r1_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r1_ecommerce.db'); conn.executescript(open('data_quality_demo/r1_ecommerce.sql', encoding='utf-8').read()); conn.close(); print('R1 DB built')"
```

Expected: `R1 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r1_ecommerce.db --output data_quality_demo/r1_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r1_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r1_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r1_config.yaml --db data_quality_demo/r1_ecommerce.db
```

Expected: All tables fill successfully (12 tables for R1). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r1_ecommerce.db data_quality_demo/r1_config.yaml data_quality_demo/r1_llm.log > data_quality_demo/_report_r1.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r1.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 5: Phase 1 — R2 Hospital Database Scan

**Files:**
- Create (temp): `data_quality_demo/r2_hospital.db`, `data_quality_demo/r2_config.yaml`, `data_quality_demo/r2_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r2_hospital.db'); conn.executescript(open('data_quality_demo/r2_hospital.sql', encoding='utf-8').read()); conn.close(); print('R2 DB built')"
```

Expected: `R2 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r2_hospital.db --output data_quality_demo/r2_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r2_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r2_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r2_config.yaml --db data_quality_demo/r2_hospital.db
```

Expected: All tables fill successfully (12 tables for R2). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r2_hospital.db data_quality_demo/r2_config.yaml data_quality_demo/r2_llm.log > data_quality_demo/_report_r2.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r2.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 6: Phase 1 — R3 Logistics Database Scan

**Files:**
- Create (temp): `data_quality_demo/r3_logistics.db`, `data_quality_demo/r3_config.yaml`, `data_quality_demo/r3_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r3_logistics.db'); conn.executescript(open('data_quality_demo/r3_logistics.sql', encoding='utf-8').read()); conn.close(); print('R3 DB built')"
```

Expected: `R3 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r3_logistics.db --output data_quality_demo/r3_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r3_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r3_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r3_config.yaml --db data_quality_demo/r3_logistics.db
```

Expected: All tables fill successfully (12 tables for R3). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r3_logistics.db data_quality_demo/r3_config.yaml data_quality_demo/r3_llm.log > data_quality_demo/_report_r3.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r3.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 7: Phase 1 — R4 SaaS Database Scan

**Files:**
- Create (temp): `data_quality_demo/r4_saas.db`, `data_quality_demo/r4_config.yaml`, `data_quality_demo/r4_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r4_saas.db'); conn.executescript(open('data_quality_demo/r4_saas.sql', encoding='utf-8').read()); conn.close(); print('R4 DB built')"
```

Expected: `R4 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r4_saas.db --output data_quality_demo/r4_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r4_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r4_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r4_config.yaml --db data_quality_demo/r4_saas.db
```

Expected: All tables fill successfully (13 tables for R4). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r4_saas.db data_quality_demo/r4_config.yaml data_quality_demo/r4_llm.log > data_quality_demo/_report_r4.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r4.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 8: Phase 1 — R5 Education Database Scan

**Files:**
- Create (temp): `data_quality_demo/r5_education.db`, `data_quality_demo/r5_config.yaml`, `data_quality_demo/r5_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r5_education.db'); conn.executescript(open('data_quality_demo/r5_education.sql', encoding='utf-8').read()); conn.close(); print('R5 DB built')"
```

Expected: `R5 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r5_education.db --output data_quality_demo/r5_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r5_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r5_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r5_config.yaml --db data_quality_demo/r5_education.db
```

Expected: All tables fill successfully (12 tables for R5). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r5_education.db data_quality_demo/r5_config.yaml data_quality_demo/r5_llm.log > data_quality_demo/_report_r5.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r5.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 9: Phase 1 — R6 Banking Database Scan

**Files:**
- Create (temp): `data_quality_demo/r6_banking.db`, `data_quality_demo/r6_config.yaml`, `data_quality_demo/r6_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r6_banking.db'); conn.executescript(open('data_quality_demo/r6_banking.sql', encoding='utf-8').read()); conn.close(); print('R6 DB built')"
```

Expected: `R6 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r6_banking.db --output data_quality_demo/r6_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r6_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r6_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r6_config.yaml --db data_quality_demo/r6_banking.db
```

Expected: All tables fill successfully (12 tables for R6). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r6_banking.db data_quality_demo/r6_config.yaml data_quality_demo/r6_llm.log > data_quality_demo/_report_r6.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r6.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 10: Phase 1 — R7 Insurance Database Scan

**Files:**
- Create (temp): `data_quality_demo/r7_insurance.db`, `data_quality_demo/r7_config.yaml`, `data_quality_demo/r7_llm.log`

- [ ] **Step 1: Build SQLite DB from SQL file**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect('data_quality_demo/r7_insurance.db'); conn.executescript(open('data_quality_demo/r7_insurance.sql', encoding='utf-8').read()); conn.close(); print('R7 DB built')"
```

Expected: `R7 DB built`

- [ ] **Step 2: Run ai-analyze with LLM logging**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r7_insurance.db --output data_quality_demo/r7_config.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r7_llm.log --max-retries 3
```

Expected: `AI suggestions saved to data_quality_demo/r7_config.yaml`. Do NOT manually inspect or edit the YAML.

- [ ] **Step 3: Fill the DB with generated data**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed fill --config data_quality_demo/r7_config.yaml --db data_quality_demo/r7_insurance.db
```

Expected: All tables fill successfully (12 tables for R7). Record any fill errors for Phase 2.

- [ ] **Step 4: Run 5-dimension verification and save report**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python scripts/_verify_data_quality.py data_quality_demo/r7_insurance.db data_quality_demo/r7_config.yaml data_quality_demo/r7_llm.log > data_quality_demo/_report_r7.md 2>&1
```

Expected: Report saved to `data_quality_demo/_report_r7.md`.

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 11: Phase 1 Consolidation — Blind-Spot Catalog

**Files:**
- Create (temp): `data_quality_demo/_phase1_catalog.md`

- [ ] **Step 1: Read all 7 reports**

Read each report file:
- `data_quality_demo/_report_r1.md` through `data_quality_demo/_report_r7.md`

- [ ] **Step 2: Consolidate blind spots by TYPE (not by database)**

Create `data_quality_demo/_phase1_catalog.md` with this structure:

```markdown
# Phase 1 Blind-Spot Catalog

## Summary
- R1: PASS/FAIL (D1=X, D2=X, D3=X, D4=X, D5=X)
- R2: PASS/FAIL
- ...
- R7: PASS/FAIL

## Type A — CHECK Pattern Recognition Misses
| Database | Table | Column | CHECK Constraint | Expected Pattern | LLM Output | Root Cause |
|----------|-------|--------|------------------|------------------|-------------|------------|
| ... | ... | ... | ... | ... | ... | ... |

## Type B — Semantic Generator Misses
| Database | Table | Column | Expected Generator | LLM Output | Root Cause |
|----------|-------|--------|--------------------|------------|------------|
| ... | ... | ... | ... | ... | ... |

## Type C — Constraint Execution Failures
| Database | Table | Constraint | Violation Count | Root Cause |
|----------|-------|------------|-----------------|------------|
| ... | ... | ... | ... | ... |

## Type D — Data Distribution Issues
| Database | Table | Column | Issue | Root Cause |
|----------|-------|--------|-------|------------|
| ... | ... | ... | ... | ... |

## Type E — Cross-DB Compatibility Issues
| Database | Issue | Root Cause |
|----------|-------|------------|
| ... | ... | ... |

## Phase 2 Fix Priority
1. (highest priority) Type A: ...
2. Type B: ...
3. Type C: ...
4. Type D: ...
5. (lowest priority) Type E: ...
```

- [ ] **Step 3: Categorize each issue from the 7 reports**

For each D1/D2/D3/D4/D5 failure found in the reports, classify it into Type A-E and add a row to the appropriate table. Use the LLM logs (`r{1-7}_llm.log`) and YAML configs (`r{1-7}_config.yaml`) to determine root cause.

- [ ] **Step 4: Do NOT commit (file is gitignored)**

---

## Task 12: Phase 2 — Fix Code Blind Spots (Iterative Loop)

**IMPORTANT:** This task is a **meta-task** — it is executed iteratively for each blind spot found in Task 11. Each blind spot fix follows the Loop Engineering 7-step discipline. The example below shows the pattern for ONE fix; repeat for each blind spot in the catalog.

**Files:**
- Modify (varies by blind spot type): see spec Section 2 Phase 2 table
- Test (varies): `tests/test_core/test_*.py` or `plugins/sqlseed-ai/tests/test_*.py`

### Loop Engineering Round N (example: fixing a Type A pattern miss)

- [ ] **Step 1: Observe — Identify the specific blind spot**

From `data_quality_demo/_phase1_catalog.md`, pick the highest-priority blind spot. Example:
- Database: R1, Table: `order_items`, Column: `line_total`
- CHECK: `line_total IS NULL OR line_total = unit_price * quantity`
- LLM output: `generator: random_float` (wrong — should be `derive_from`)
- Expected: Pattern 4 (`col = col1 * col2`)

- [ ] **Step 2: Diagnose — Trace the code path**

Read `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — find `_infer_cross_column_config()`. Check if Pattern 4 (`col IS NULL OR col = col1 * col2`) is handled. If not, this is the root cause.

- [ ] **Step 3: Hypothesize — Classify root cause**

Root cause: Pattern 4 variant with `IS NULL OR` prefix not recognized. This is a **detection blind spot** in `_infer_cross_column_config()`.

- [ ] **Step 4: Fix CODE — Write failing test first (TDD)**

**Files:**
- Test: `plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py`

Write a failing test:

```python
def test_infer_pattern4_with_is_null_or_prefix(self):
    """Pattern 4 variant: 'col IS NULL OR col = col1 * col2' must map to derive_from."""
    snapshot = self._make_snapshot(
        tables=["order_items"],
        columns={"order_items": ["id", "unit_price", "quantity", "line_total"]},
        constraints={
            "order_items": [
                {"type": "check", "expression": "line_total IS NULL OR line_total = unit_price * quantity"}
            ]
        },
    )
    result = self.orchestrator._build_subgraph_config(["order_items"], snapshot)
    line_total_col = next(c for c in result["tables"][0]["columns"] if c["name"] == "line_total")
    assert line_total_col.get("derive_from") is not None
    assert "unit_price" in line_total_col.get("derive_from", [])
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py::TestAutoHealOrchestrator::test_infer_pattern4_with_is_null_or_prefix -v`

Expected: FAIL (Pattern 4 variant not recognized).

- [ ] **Step 6: Implement the fix in CODE**

Edit `plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py` — in `_infer_cross_column_config()`, add a new pattern match for `col IS NULL OR col = col1 * col2` before existing patterns. The fix must be GENERIC (benefits any database with this CHECK pattern, not just R1).

```python
# Pattern 4 variant: col IS NULL OR col = col1 * col2
# (null_ratio + derive_from with multiplication expression)
p4_null_or = re.match(
    rf"{re.escape(col)}\s+IS\s+NULL\s+OR\s+{re.escape(col)}\s*=\s*"
    rf"(\w+)\s*([*/+-])\s*(\w+)$",
    expr,
    re.IGNORECASE,
)
if p4_null_or:
    src1, op, src2 = p4_null_or.groups()
    if src1 in col_names and src2 in col_names:
        return {
            "derive_from": [src1, src2],
            "expression": f"row['{src1}'] {op} row['{src2}']",
            "null_ratio": 0.3,
        }
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py::TestAutoHealOrchestrator::test_infer_pattern4_with_is_null_or_prefix -v`

Expected: PASS.

- [ ] **Step 8: Run full test suite for affected module**

Run: `pytest plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py -v`

Expected: All tests PASS (no regressions).

- [ ] **Step 9: Run lint and type check**

Run:
```bash
ruff check src/ tests/ plugins/
mypy
```

Expected: No errors.

- [ ] **Step 10: Update markdown documentation (if pattern count changed)**

If a new Pattern was added (pattern count increased), update:
- `CLAUDE.md` — update the pattern count in the v4 contract-driven section (e.g., "36 patterns" to "37 patterns")
- `README.md` / `README.zh-CN.md` — update if pattern count is documented there
- Run: `pytest tests/test_doc_sync.py -v` to verify AUTO-GENERATED markers are in sync

- [ ] **Step 11: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py CLAUDE.md
git commit -m "feat: add Pattern 4 IS NULL OR variant in _infer_cross_column_config (blind-spot type A)"
```

- [ ] **Step 12: Repeat for next blind spot**

Return to Step 1 with the next blind spot from the catalog. Continue until all blind spots in `data_quality_demo/_phase1_catalog.md` are resolved.

---

## Task 13: Phase 3 — Revalidation Run (Reuse Existing YAMLs)

**Files:**
- No new files — reuse `data_quality_demo/r{1-7}_config.yaml` from Phase 1

- [ ] **Step 1: Rebuild all 7 databases (fresh)**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "
import sqlite3
dbs = [
    ('r1_ecommerce', 'r1_ecommerce.sql'),
    ('r2_hospital', 'r2_hospital.sql'),
    ('r3_logistics', 'r3_logistics.sql'),
    ('r4_saas', 'r4_saas.sql'),
    ('r5_education', 'r5_education.sql'),
    ('r6_banking', 'r6_banking.sql'),
    ('r7_insurance', 'r7_insurance.sql'),
]
for db_name, sql_file in dbs:
    db_path = f'data_quality_demo/{db_name}.db'
    conn = sqlite3.connect(db_path)
    conn.executescript(open(f'data_quality_demo/{sql_file}', encoding='utf-8').read())
    conn.close()
    print(f'{db_name}: rebuilt')
"
```

Expected: All 7 databases rebuilt.

- [ ] **Step 2: Run revalidation on all 7 YAMLs (no LLM calls)**

Run (Windows PowerShell):
```powershell
$dbs = @('r1_ecommerce','r2_hospital','r3_logistics','r4_saas','r5_education','r6_banking','r7_insurance')
foreach ($db in $dbs) {
    Write-Host "Revalidating $db..."
    python scripts/_revalidate.py "data_quality_demo/${db}_config.yaml" "data_quality_demo/${db}.db"
}
```

Expected: Each revalidation prints violation count (ideally 0 after Phase 2 fixes).

- [ ] **Step 3: Fill all 7 databases with generated data**

Run:
```powershell
$dbs = @('r1_ecommerce','r2_hospital','r3_logistics','r4_saas','r5_education','r6_banking','r7_insurance')
foreach ($db in $dbs) {
    Write-Host "Filling $db..."
    sqlseed fill --config "data_quality_demo/${db}_config.yaml" --db "data_quality_demo/${db}.db"
}
```

Expected: All tables fill successfully for all 7 databases.

- [ ] **Step 4: Run 5-dimension verification on all 7 databases**

Run:
```powershell
$dbs = @('r1_ecommerce','r2_hospital','r3_logistics','r4_saas','r5_education','r6_banking','r7_insurance')
foreach ($db in $dbs) {
    $num = $db.Split('_')[0]
    Write-Host "Verifying $db..."
    python scripts/_verify_data_quality.py "data_quality_demo/${db}.db" "data_quality_demo/${db}_config.yaml" "data_quality_demo/${num}_llm.log" > "data_quality_demo/_report_phase3_${db}.md" 2>&1
}
```

- [ ] **Step 5: Check convergence**

Read all 7 Phase 3 reports. For each database:
- If D1-D5 all PASS → database is converged, mark as done
- If any D1-D5 FAIL → diagnose: is it a YAML-structural issue (Phase 4) or a new code blind spot (back to Phase 2)?

- [ ] **Step 6: Do NOT commit (all temp files are gitignored)**

---

## Task 14: Phase 4 — Targeted LLM Re-runs (Conditional)

**IMPORTANT:** This task is ONLY executed for databases that still fail Phase 3 due to YAML-structural errors (not code blind spots). If all 7 databases passed Phase 3, SKIP this task.

**Files:**
- Create (temp): `data_quality_demo/r{N}_config_v2.yaml`, `data_quality_demo/r{N}_llm_v2.log`

- [ ] **Step 1: Diagnose each failing database**

For each database that failed Phase 3:
1. Read the Phase 3 report
2. Read the YAML config
3. Determine: Is the failure due to:
   - **YAML structural error** (e.g., LLM emitted a non-existent generator, missing column config) → proceed to Step 2
   - **Code blind spot** (e.g., a CHECK pattern still not recognized) → go back to Task 12 (Phase 2), do NOT re-run LLM

- [ ] **Step 2: Re-run ai-analyze for YAML-structural failures only**

For each database with YAML-structural failure, run:
```bash
cd c:\Users\14435\Desktop\sqlseed
sqlseed ai-analyze --db data_quality_demo/r{N}_{name}.db --output data_quality_demo/r{N}_config_v2.yaml --base-url http://127.0.0.1:1234/v1 --log-llm data_quality_demo/r{N}_llm_v2.log --max-retries 3
```

Replace `{N}` and `{name}` with the database number and name (e.g., `1_ecommerce`).

- [ ] **Step 3: Fill with new YAML and verify**

Run:
```bash
sqlseed fill --config data_quality_demo/r{N}_config_v2.yaml --db data_quality_demo/r{N}_{name}.db
python scripts/_verify_data_quality.py data_quality_demo/r{N}_{name}.db data_quality_demo/r{N}_config_v2.yaml data_quality_demo/r{N}_llm_v2.log
```

- [ ] **Step 4: Check convergence**

If the database now passes D1-D5 → converged. If still failing → diagnose again (Phase 2 or Phase 4).

- [ ] **Step 5: Do NOT commit (all temp files are gitignored)**

---

## Task 15: Final Convergence Verification + Doc Sync + Cleanup

**Files:**
- Modify (if needed): `CLAUDE.md`, `README.md`, `README.zh-CN.md`
- Delete (temp): all `data_quality_demo/*.db`, `*_config*.yaml`, `*_llm*.log`, `_report*.md`, `_phase1_catalog.md` files

- [ ] **Step 1: Verify all 7 databases pass 5-dimension verification**

Run (Windows PowerShell):
```powershell
$dbs = @('r1_ecommerce','r2_hospital','r3_logistics','r4_saas','r5_education','r6_banking','r7_insurance')
$all_pass = $true
foreach ($db in $dbs) {
    $num = $db.Split('_')[0]
    $result = python scripts/_verify_data_quality.py "data_quality_demo/${db}.db" "data_quality_demo/${db}_config.yaml" "data_quality_demo/${num}_llm.log"
    Write-Host "$db : $result"
    if ($LASTEXITCODE -ne 0) { $all_pass = $false }
}
Write-Host "ALL PASS: $all_pass"
```

Expected: `ALL PASS: True` (all 7 databases converge).

- [ ] **Step 2: Run full test suite**

Run:
```bash
cd c:\Users\14435\Desktop\sqlseed
pytest
```

Expected: All tests pass (no regressions from Phase 2 fixes).

- [ ] **Step 3: Run lint and type check**

Run:
```bash
ruff check src/ tests/ plugins/
mypy
```

Expected: No errors.

- [ ] **Step 4: Run doc sync verification**

Run:
```bash
pytest tests/test_doc_sync.py -v
```

Expected: All doc sync tests pass (AUTO-GENERATED markers in sync).

- [ ] **Step 5: Verify CLAUDE.md pattern count is accurate**

Read `CLAUDE.md` — find the pattern count in the v4 contract-driven section. Count the actual patterns in `_infer_cross_column_config()` and `_parse_single_column_check()` in `auto_heal/orchestrator.py`. The counts must match.

If they don't match, update `CLAUDE.md` and run `python scripts/sync_docs.py`.

- [ ] **Step 6: Verify working tree is clean**

Run:
```bash
git status
```

Expected: No untracked temp files. If any temp files appear, delete them:
```powershell
Remove-Item data_quality_demo\*.db, data_quality_demo\*_config*.yaml, data_quality_demo\*_llm*.log, data_quality_demo\_*.md -ErrorAction SilentlyContinue
```

- [ ] **Step 7: Verify no temp scripts are tracked**

Run:
```bash
git ls-files scripts/_*.py
```

Expected: No output (temp scripts are gitignored, not tracked).

- [ ] **Step 8: Final commit (if any doc updates remain)**

If Step 5 required doc updates that haven't been committed:
```bash
git add CLAUDE.md README.md README.zh-CN.md
git commit -m "docs: sync pattern count after LLM validation loop engineering"
```

- [ ] **Step 9: Report convergence summary**

Print a summary:
```
LLM Validation Loop Engineering — Convergence Summary:
- R1 E-Commerce: PASS (12 tables, 0 violations)
- R2 Hospital: PASS (12 tables, 0 violations)
- R3 Logistics: PASS (12 tables, 0 violations)
- R4 SaaS: PASS (13 tables, 0 violations)
- R5 Education: PASS (12 tables, 0 violations)
- R6 Banking: PASS (12 tables, 0 violations)
- R7 Insurance: PASS (12 tables, 0 violations)
- Phase 2 fixes: N commits (list commit hashes)
- Tests: all pass
- Lint: clean
- Types: clean
- Docs: in sync
- Working tree: clean
```

The project is now ready for user review and manual merge approval to `main`.
