"""PostgreSQL test service selection and owned-container cleanup contracts."""

from __future__ import annotations

import pytest

import conftest as shared


def test_external_pg_service_does_not_require_or_start_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_TEST_URL", "postgresql+psycopg://localhost/isolated_test")
    monkeypatch.setattr(shared, "PostgresContainer", None)
    service = shared.pg_url.__wrapped__()
    try:
        assert next(service) == "postgresql+psycopg://localhost/isolated_test"
    except pytest.skip.Exception:
        pytest.fail("An explicitly configured PostgreSQL service must not require Docker")
    service.close()


def test_owned_container_is_stopped_when_startup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PG_TEST_URL", raising=False)
    stopped = []

    class FailedContainer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise ValueError("invalid database startup configuration")

        def stop(self) -> None:
            stopped.append(True)

    monkeypatch.setattr(shared, "PostgresContainer", FailedContainer)
    with pytest.raises(ValueError, match="invalid database startup configuration"):
        next(shared.pg_url.__wrapped__())
    assert stopped == [True]
