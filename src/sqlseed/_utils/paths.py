"""Platform-aware cache directory resolution for sqlseed.

Follows OS conventions:
  - macOS:   ``~/Library/Caches/sqlseed/``
  - Linux:   ``$XDG_CACHE_HOME/sqlseed/`` (defaults to ``~/.cache/sqlseed/``)
  - Windows: ``%LOCALAPPDATA%/sqlseed/``

All paths can be overridden via the ``SQLSEED_CACHE_DIR`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_CACHE_DIR_ENV = "SQLSEED_CACHE_DIR"


def get_cache_dir(subdir: str = "") -> Path:
    """Return the platform-specific cache directory for sqlseed.

    The returned path is **not** created automatically — callers must call
    ``path.mkdir(parents=True, exist_ok=True)`` before writing files.

    Args:
        subdir: Optional subdirectory to append (e.g. ``"snapshots"``).

    Returns:
        Absolute ``Path`` to the cache directory (may not exist on disk).
    """
    env_root = os.environ.get(_CACHE_DIR_ENV)
    if env_root:
        root = Path(env_root)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "sqlseed"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "sqlseed"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sqlseed"
    return root / subdir if subdir else root
