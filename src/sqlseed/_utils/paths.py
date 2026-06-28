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
    # SQLSEED_CACHE_DIR takes highest priority and overrides all platform defaults.
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


def validate_db_target(db_path: str) -> str:
    """Validate a database connection target (file path or URL).

    Used by both MCP server packages (``mcp-server-sqlseed`` and
    ``sqlseed-ai[mcp]``) to avoid duplicating validation logic across
    independent packages. Both packages depend on ``sqlseed`` core, so
    this shared helper preserves plugin independence (plugins import
    from core, never from each other — per ARCHITECTURE.md §4).

    .. note::
        This MCP server is designed for local use. Path traversal is not a
        realistic threat because the user invoking the server is the same
        user providing the db_path. No directory restriction is enforced.

    Args:
        db_path: Database file path or database URL
            (e.g., ``postgresql://user:pass@host/db``).

    Returns:
        The validated connection target string.

    Raises:
        ValueError: If a file path is invalid or the file does not exist.
    """
    # URL format (with scheme) passes through; validated later by SQLAlchemy
    if "://" in db_path:
        return db_path

    # File path: apply validation logic
    resolved = Path(db_path).resolve()
    valid_exts = (".db", ".sqlite", ".sqlite3")
    if not str(resolved).endswith(valid_exts):
        raise ValueError(
            f"Invalid database target: {db_path}. "
            "Must be a .db/.sqlite/.sqlite3 file or a database URL "
            "(e.g., postgresql://user:pass@host/db)."
        )
    if not resolved.exists():
        raise ValueError(f"Database file not found: {db_path}")
    return str(resolved)


def validate_table_name(table_name: str, allowed_tables: list[str]) -> str:
    """Validate that a table exists in the allowed list.

    Used by both MCP server packages to avoid duplicating validation logic.

    Args:
        table_name: The table name to validate.
        allowed_tables: The list of tables that exist in the database.

    Returns:
        The validated table name.

    Raises:
        ValueError: If ``table_name`` is not in ``allowed_tables``.
    """
    if table_name not in allowed_tables:
        raise ValueError(f"Table '{table_name}' does not exist in the database. Available: {allowed_tables}")
    return table_name
