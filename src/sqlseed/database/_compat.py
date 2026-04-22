from __future__ import annotations

from typing import Any

try:
    import sqlite_utils as _sqlite_utils

    HAS_SQLITE_UTILS: bool = True
    sqlite_utils: Any = _sqlite_utils
except ImportError:
    HAS_SQLITE_UTILS = False
    sqlite_utils = None

__all__ = ["HAS_SQLITE_UTILS", "sqlite_utils"]
