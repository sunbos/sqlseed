"""Tests for the _validate_db_target function (formerly _validate_db_path)."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_server_sqlseed.server import _validate_db_target


class TestValidateDbPath:
    """Tests for the _validate_db_target function's URL and file path validation."""

    def test_validate_postgresql_url_passes_through(self) -> None:
        """A postgresql URL is returned directly without file existence checks."""
        url = "postgresql://user:pass@host:5432/db"
        assert _validate_db_target(url) == url

    def test_validate_sqlite_url_passes_through(self) -> None:
        """A sqlite URL is returned directly."""
        url = "sqlite:///path/to/db.sqlite"
        assert _validate_db_target(url) == url

    def test_validate_invalid_file_path_raises(self) -> None:
        """A path that is neither a URL nor a valid extension raises ValueError."""
        with pytest.raises(ValueError, match="Invalid database target"):
            _validate_db_target("not_a_url_or_valid_path")

    def test_validate_nonexistent_db_file_raises(self, tmp_path: Path) -> None:
        """A file with a valid extension that does not exist raises ValueError."""
        nonexistent = str(tmp_path / "missing.db")
        with pytest.raises(ValueError, match="Database file not found"):
            _validate_db_target(nonexistent)

    def test_validate_valid_sqlite_file_returns_resolved(self, tmp_sqlite_db: str) -> None:
        """A real .db file returns its absolute resolved path."""
        result = _validate_db_target(tmp_sqlite_db)
        assert result == str(Path(tmp_sqlite_db).resolve())

    def test_validate_url_with_special_chars(self) -> None:
        """A URL containing special characters (e.g. in the password) is handled correctly."""
        url = "postgresql://user:p@ss!w0rd@host:5432/db"
        assert _validate_db_target(url) == url

    def test_validate_url_scheme_only_no_authority(self) -> None:
        """Edge case: 'postgresql://' with no authority.

        Contains '://' so it is returned directly, and SQLAlchemy validates it later.
        """
        url = "postgresql://"
        assert _validate_db_target(url) == url
