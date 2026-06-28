"""Query mutmut cache (SQLite) for surviving mutants and write a plain-text report.

One-shot helper script for the Phase 3 mutation-test audit. Run with:
    python scripts/_mutmut_report.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

CACHE = Path(".mutmut-cache")


def main() -> int:
    if not CACHE.exists():
        print("ERROR: .mutmut-cache not found. Run `python -m mutmut run ...` first.")
        return 1

    conn = sqlite3.connect(str(CACHE))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"cache tables: {tables}")

    # Schema discovery for Mutant table
    cols = [r[1] for r in cur.execute("PRAGMA table_info(Mutant)")]
    print(f"Mutant columns: {cols}")

    # Aggregate by status
    print("\n=== status counts ===")
    for row in cur.execute("SELECT status, COUNT(*) AS n FROM Mutant GROUP BY status ORDER BY n DESC"):
        print(f"  {row['status']}: {row['n']}")

    # Surviving mutants (status = 'bad_survived' in mutmut 2.x)
    print("\n=== surviving mutants (bad_survived) ===")
    line_cols = [r[1] for r in cur.execute("PRAGMA table_info(Line)")]
    print(f"Line columns: {line_cols}")
    survivors = list(
        cur.execute(
            "SELECT m.id, m.line, m.[index], m.status "
            "FROM Mutant m "
            "WHERE m.status = 'bad_survived' ORDER BY m.line, m.[index]"
        )
    )
    print(f"total survivors: {len(survivors)}")
    for row in survivors:
        print(f"  mutant_id={row['id']}  line_ref={row['line']}  idx={row['index']}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
