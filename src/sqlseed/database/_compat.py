from __future__ import annotations

import sqlite3
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

try:
    import sqlite_utils as _sqlite_utils

    HAS_SQLITE_UTILS: bool = True
    sqlite_utils: Any = _sqlite_utils
except ImportError:
    HAS_SQLITE_UTILS = False
    sqlite_utils = None

__all__ = ["HAS_SQLITE_UTILS", "sqlite_utils"]


def read_table_names(db_path: str) -> list[str]:
    if HAS_SQLITE_UTILS:
        db = sqlite_utils.Database(db_path)
        try:
            return [t for t in db.table_names() if not t.startswith("sqlite_")]
        finally:
            db.close()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()
