from __future__ import annotations

import sqlite3


def assert_fk_integrity(db_path: str, fk_query: str, ref_query: str) -> None:
    conn = sqlite3.connect(db_path)
    fk_values = {r[0] for r in conn.execute(fk_query).fetchall() if r[0] is not None}
    ref_values = {r[0] for r in conn.execute(ref_query).fetchall()}
    conn.close()
    assert fk_values.issubset(ref_values)
