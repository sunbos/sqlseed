"""Exercise worker startup reports and cleanup over real IPC and HTTP."""

from __future__ import annotations

import multiprocessing
import os
import signal
import socket
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import _application, managed_worker, runtime_lifecycle
from sqlseed_web.worker_control import ControlChannel, ControlTransport


@dataclass
class WorkerHarness:
    """Own the real transport and descriptors for one in-process worker."""

    listener: socket.socket
    parent: ControlChannel
    child: ControlTransport
    messages: list[tuple[str, dict[str, Any]]]
    ready: threading.Event
    gate: runtime_lifecycle.RuntimeGate
    descriptor: int
    descriptor_transferred: bool = False

    def detach(self) -> int:
        """Transfer descriptor ownership once so teardown cannot close a reused descriptor."""
        if self.descriptor_transferred:
            raise RuntimeError("Worker descriptor was already transferred")
        self.descriptor_transferred = True
        return self.descriptor

    def run(self) -> None:
        """Execute the real maintenance worker against this harness transport and listener."""
        managed_worker.run_worker(self.listener, self.child, "maintenance", {}, "test-token", self)


@pytest.fixture(name="worker_harness")
def fixture_worker_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkerHarness]:
    """Keep signal handlers, admission state, workspace and handles isolated."""
    import uvicorn

    # This worker shares pytest's process instead of owning a fresh interpreter.
    # Keep real Config/Server/HTTP behavior without reconfiguring host loggers.
    monkeypatch.setattr(uvicorn.Config, "configure_logging", lambda self: None)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    parent, child = multiprocessing.get_context("spawn").Pipe()
    channel = ControlChannel(parent)
    messages: list[tuple[str, dict[str, Any]]] = []
    ready = threading.Event()

    def receive(method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Record actual worker status messages and signal readiness to the HTTP observer."""
        messages.append((method, params))
        if method == "worker_ready":
            ready.set()
        return {}

    channel.start(receive)
    gate = runtime_lifecycle.RuntimeGate()
    monkeypatch.setattr(runtime_lifecycle, "runtime_gate", gate)
    monkeypatch.setenv("SQLSEED_WEB_WORKSPACE_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("SQLSEED_WEB_SETTINGS_PATH", str(tmp_path / "settings.json"))
    descriptor = os.open(tmp_path / "environment.lock", os.O_CREAT | os.O_RDWR)
    harness = WorkerHarness(listener, channel, child, messages, ready, gate, descriptor)
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield harness
    finally:
        channel.close()
        child.close()
        listener.close()
        if not harness.descriptor_transferred:
            with suppress(OSError):
                os.close(descriptor)
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)


def _assert_worker_closed(harness: WorkerHarness) -> None:
    """Require released descriptors, stopped HTTP threads and closed runtime admission."""
    assert harness.parent.wait_closed(5)
    assert harness.listener.fileno() == -1
    with pytest.raises(OSError):
        os.fstat(harness.descriptor)
    assert not any(harness.gate.activity().values())
    with pytest.raises(HTTPException) as paused:
        harness.gate.acquire("requests")
    assert paused.value.status_code == 503
    assert not any(thread.name == "sqlseed-http-worker" for thread in threading.enumerate())


def test_worker_announces_real_http_readiness_then_closes_owned_resources(worker_harness: WorkerHarness) -> None:
    """Verify startup phases precede real maintenance HTTP service and orderly resource release."""
    harness = worker_harness
    address = f"http://127.0.0.1:{harness.listener.getsockname()[1]}"

    def inspect_and_stop() -> None:
        """Check maintenance admission over HTTP before requesting shutdown through IPC."""
        try:
            assert harness.ready.wait(15), harness.messages
            with httpx.Client(base_url=address, timeout=5, trust_env=False) as client:
                response = client.get("/api/connections")
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "plugin_maintenance"
                assert client.get("/api/health").status_code == 200
            assert not harness.parent.call("shutdown", {}, timeout=5)
        finally:
            harness.parent.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        inspected = executor.submit(inspect_and_stop)
        harness.run()
        inspected.result(timeout=5)
    assert harness.messages == [
        ("worker_starting", {"mode": "maintenance", "phase": "session"}),
        ("worker_starting", {"mode": "maintenance", "phase": "application"}),
        ("worker_starting", {"mode": "maintenance", "phase": "http"}),
        ("worker_ready", {"mode": "maintenance", "restoration": {}}),
    ]
    _assert_worker_closed(harness)


@pytest.mark.parametrize(("mode", "with_session"), [("business", False), ("business", True), ("maintenance", True)])
def test_worker_session_restore_keeps_original_connection_and_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, with_session: bool
) -> None:
    """Restore business connection identity and data while maintenance ignores saved sessions."""
    from sqlseed_web import runtime_session
    from sqlseed_web.state import UIState

    registry = UIState()
    monkeypatch.setattr(runtime_session, "state", registry)
    database = tmp_path / "restored.sqlite3"
    with sqlite_connection(database) as connection:
        connection.executescript("CREATE TABLE records(id INTEGER PRIMARY KEY); INSERT INTO records VALUES (7);")
    saved = {"conn_id": "original-id", "target": str(database), "provider": "base", "locale": "en_US"}
    snapshot = {"connections": [saved], "ai_override": {"model": "preserved-model"}} if with_session else {}
    try:
        result = managed_worker._restore_worker_session(mode, snapshot)
        if mode == "maintenance":
            assert not result
            assert not registry.list_connections()
        else:
            assert result == {
                "restored_connections": int(with_session),
                "failed_connections": [],
                "ai_session_restored": True,
            }
            if with_session:
                restored = registry.get_connection("original-id")
                assert restored.provider == "base"
                assert restored.locale == "en_US"
                assert restored.orchestrator.get_row_count("records") == 1
                with restored.orchestrator._db._engine.connect() as reopened:
                    assert reopened.exec_driver_sql("SELECT id FROM records").fetchall() == [(7,)]
                assert registry.get_ai_override() == {"model": "preserved-model"}
            else:
                assert not registry.list_connections()
        with sqlite_connection(database) as connection:
            assert connection.execute("SELECT id FROM records").fetchall() == [(7,)]
    finally:
        runtime_session.close_session()


@pytest.mark.parametrize("failure", ["application", "http", "closed_control"])
def test_worker_startup_failure_reports_only_safe_phase_and_releases_resources(
    worker_harness: WorkerHarness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Keep initialization failures safe and release resources even after losing the control peer."""
    harness = worker_harness
    create_app = _application.create_app
    serve_worker = managed_worker._serve_worker
    secret = "private-password https://user:secret@example.test"
    startup_exits: list[int | str | None] = []

    def record_startup_exit(server: Any, listener: socket.socket) -> None:
        """Collect the expected Uvicorn startup exit without leaking a thread exception."""
        try:
            serve_worker(server, listener)
        except SystemExit as exc:
            # Newer Uvicorn exits with status 3 when lifespan startup fails;
            # older releases return with started=False. Assert either outcome
            # explicitly instead of leaking an expected exception from a thread.
            startup_exits.append(exc.code)

    class FailedLifespan:
        async def __aenter__(self) -> None:
            """Reject actual ASGI startup with a diagnostic that must not cross public IPC."""
            raise ValueError(secret)

        async def __aexit__(self, *args: object) -> None:
            """Provide the lifespan protocol without suppressing initialization errors."""

    def create_failing_app(**kwargs: Any) -> Any:
        """Inject failures at application construction or real ASGI lifespan startup."""
        if failure == "closed_control":
            harness.parent.close()
        if failure != "http":
            raise ValueError(secret)
        app = create_app(**kwargs)
        # Run actual Uvicorn startup against an ASGI lifespan that fails.
        app.router.lifespan_context = lambda app: FailedLifespan()
        return app

    monkeypatch.setattr(_application, "create_app", create_failing_app)
    monkeypatch.setattr(managed_worker, "_serve_worker", record_startup_exit)
    with pytest.raises(RuntimeError) as failed:
        harness.run()
    assert failed.value.__suppress_context__
    assert "private-password" not in str(failed.value)
    assert "user:secret" not in str(failed.value)
    assert not harness.ready.is_set()
    assert all(method != "worker_ready" for method, _ in harness.messages)
    if failure != "closed_control":
        assert harness.messages[-1] == ("worker_failed", {"mode": "maintenance", "phase": failure})
    assert "private-password" not in str(harness.messages)
    assert startup_exits in ([], [3])
    _assert_worker_closed(harness)
