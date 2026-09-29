"""Preserve SQLite's existing pool, URI, and memory lifetime contracts."""

from __future__ import annotations

import warnings
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.exc import SAWarning
from sqlalchemy.pool import QueuePool, SingletonThreadPool, StaticPool

from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import URL


def _write_marker(adapter: SQLAlchemyAdapter) -> None:
    with closing(adapter.execute("CREATE TABLE marker(value INTEGER NOT NULL)")):
        pass
    with closing(adapter.execute("INSERT INTO marker VALUES(7)")):
        pass


def _read_marker(adapter: SQLAlchemyAdapter) -> list[tuple[int]]:
    with closing(adapter.execute("SELECT value FROM marker")) as cursor:
        return cursor.fetchall()


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+pysqlite"])
@pytest.mark.parametrize("shared", [False, True])
def test_named_memory_preserves_data_sharing_and_connection_lifetime(driver: str, shared: bool) -> None:
    cache = "shared" if shared else "private"
    target = f"{driver}:///file:pool-policy-{cache}?mode=memory&cache={cache}&uri=true&timeout=1.25"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with SQLAlchemyAdapter() as one, SQLAlchemyAdapter() as two:
            one.connect(target)
            assert isinstance(one._get_engine().pool, SingletonThreadPool)
            _write_marker(one)
            assert _read_marker(one) == [(7,)]
            with closing(one.execute("PRAGMA busy_timeout")) as cursor:
                assert cursor.fetchall() == [(1250,)]
            with closing(one.execute("PRAGMA database_list")) as cursor:
                assert cursor.fetchall()[0][2] == ""
            two.connect(target)
            if shared:
                assert _read_marker(two) == [(7,)]
                one.close()
                assert _read_marker(two) == [(7,)]
            else:
                assert two.get_table_names() == []
        with SQLAlchemyAdapter() as reopened:
            reopened.connect(target)
            assert reopened.get_table_names() == []


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+pysqlite"])
def test_plain_memory_keeps_the_dialect_default(driver: str) -> None:
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(f"{driver}:///:memory:")
        assert isinstance(adapter._get_engine().pool, SingletonThreadPool)
        _write_marker(adapter)
        assert _read_marker(adapter) == [(7,)]


@pytest.mark.parametrize("driver", ["sqlite", "sqlite+pysqlite"])
def test_disk_uri_keeps_queue_pool_and_durable_data(tmp_path: Path, driver: str) -> None:
    path = tmp_path / "pool %41.db"
    target = f"{driver}:///{path.as_uri()}?mode=rwc&uri=true"
    with SQLAlchemyAdapter() as adapter:
        adapter.connect(target)
        assert isinstance(adapter._get_engine().pool, QueuePool)
        _write_marker(adapter)
    with SQLAlchemyAdapter() as reopened:
        reopened.connect(target)
        assert _read_marker(reopened) == [(7,)]
    assert list(tmp_path.iterdir()) == [path]


class _CustomSQLiteDialect(SQLiteDialect_pysqlite):
    supports_statement_cache = True

    @classmethod
    def get_pool_class(cls, url: URL) -> type[StaticPool]:
        return StaticPool


def test_another_sqlite_driver_keeps_its_own_pool_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.impls, "sqlite.poolprobe", lambda: _CustomSQLiteDialect)
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        with SQLAlchemyAdapter() as adapter:
            adapter.connect("sqlite+poolprobe:///file:custom-pool?mode=memory&uri=true")
            assert isinstance(adapter._get_engine().pool, StaticPool)
            _write_marker(adapter)
            assert _read_marker(adapter) == [(7,)]


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg"])
def test_postgresql_engine_configuration_keeps_its_pool_policy(driver: str) -> None:
    pytest.importorskip("psycopg")
    # Engine construction is lazy: no PostgreSQL server or user database is opened.
    engine = SQLAlchemyAdapter._create_engine_for_url(f"{driver}://localhost/test?mode=memory")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.query == {"mode": "memory"}
        assert isinstance(engine.pool, QueuePool)
    finally:
        engine.dispose()
