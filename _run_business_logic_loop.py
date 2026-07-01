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
        categories.append("CHECK constraint violation - consider adding derive_from for cross-column CHECK")
    if "FK" in verify_output and "FAIL" in verify_output:
        categories.append("FK integrity violation - check topological fill order")
    if "UNIQUE" in verify_output and "FAIL" in verify_output:
        categories.append("UNIQUE constraint violation - ensure constraints.unique=true is set")
    if "GENERATED" in verify_output and "FAIL" in verify_output:
        categories.append("GENERATED column issue - ensure GENERATED columns are excluded from config")
    if "REALISM" in verify_output and "FAIL" in verify_output:
        categories.append("Data realism issue - check generator selection for name/email/phone columns")
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
