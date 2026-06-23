"""Tests for orchestrator-adapter integration."""

from __future__ import annotations

from sqlseed.core.orchestrator import DataOrchestrator, _is_db_url
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter


class TestOrchestratorAdapter:
    """Tests the adapter dispatch logic of the orchestrator."""

    def test_is_db_url_with_postgresql(self) -> None:
        """_is_db_url("postgresql://...") returns True."""
        assert _is_db_url("postgresql://user:pass@host/db") is True

    def test_is_db_url_with_mysql(self) -> None:
        """_is_db_url("mysql://...") returns True."""
        assert _is_db_url("mysql://user:pass@host/db") is True

    def test_is_db_url_with_sqlite_url(self) -> None:
        """_is_db_url("sqlite:///path.db") returns True."""
        assert _is_db_url("sqlite:///path/to/db.db") is True

    def test_is_db_url_with_file_path(self) -> None:
        """_is_db_url("/path/to/db.sqlite") returns False."""
        assert _is_db_url("/path/to/db.sqlite") is False

    def test_is_db_url_with_relative_path(self) -> None:
        """_is_db_url("app.db") returns False."""
        assert _is_db_url("app.db") is False

    def test_is_db_url_with_windows_path(self) -> None:
        """_is_db_url("C:\\path\\to\\db.db") returns False."""
        assert _is_db_url("C:\\path\\to\\db.db") is False

    def test_create_adapter_returns_sqlalchemy_for_file(self, tmp_db: str) -> None:
        """File path input returns a SQLAlchemyAdapter instance."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            adapter = orch._core.db
            assert isinstance(adapter, SQLAlchemyAdapter)

    def test_create_adapter_returns_sqlalchemy_for_url(self, tmp_db: str) -> None:
        """URL input returns a SQLAlchemyAdapter instance."""
        url = f"sqlite:///{tmp_db}"
        with DataOrchestrator(url, provider_name="base") as orch:
            orch._ensure_connected()
            adapter = orch._core.db
            assert isinstance(adapter, SQLAlchemyAdapter)

    def test_get_dialect_name_sqlite(self, tmp_db: str) -> None:
        """SQLite file returns "sqlite"."""
        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            assert orch._get_dialect_name() == "sqlite"

    def test_get_dialect_name_sqlite_url(self, tmp_db: str) -> None:
        """SQLite URL returns "sqlite"."""
        url = f"sqlite:///{tmp_db}"
        with DataOrchestrator(url, provider_name="base") as orch:
            orch._ensure_connected()
            assert orch._get_dialect_name() == "sqlite"
