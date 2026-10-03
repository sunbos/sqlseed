"""Fresh business and maintenance workers controlled by the stable launcher."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import HTTPException

from sqlseed_web.messages import message as tr
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.worker_control import (
    ControlChannel,
    ControlError,
    ControlMessageTooLarge,
    ControlTransport,
    validate_control_result,
)

if TYPE_CHECKING:
    import uvicorn

    from sqlseed_web.runtime_lifecycle import RuntimeGate


class WorkerLifecycleError(RuntimeError):
    """Only fixed lifecycle facts may cross the public recovery boundary."""

    def __init__(self, code: str, *, mode: str, phase: str, elapsed_ms: int, exit_code: int | None) -> None:
        messages = {
            "worker_startup_timeout": tr("backend.supervisor.worker_startup_timeout"),
            "worker_exited_before_ready": tr("backend.supervisor.worker_exited_before_ready"),
            "worker_startup_failed": tr("backend.supervisor.worker_startup_failed"),
            "worker_resume_failed": tr("backend.supervisor.worker_resume_failed"),
            "worker_shutdown_timeout": tr("backend.supervisor.worker_shutdown_timeout"),
            "worker_stop_pending": tr("backend.supervisor.worker_stop_pending"),
        }
        message = messages[code]
        super().__init__(message)
        self.detail: dict[str, Any] = {
            "code": code,
            "message": message,
            "worker_mode": mode,
            "phase": phase,
            "elapsed_ms": elapsed_ms,
            "exit_code": exit_code,
        }


class RemotePluginManager:
    """The HTTP worker cannot execute package operations itself."""

    enabled = True

    def __init__(self, channel: ControlChannel, token: str) -> None:
        self.channel = channel
        self.token = token

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.channel.call(method, params)
        except ControlError as exc:
            raise HTTPException(exc.status_code, detail=exc.detail) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(
                503,
                detail={
                    "code": "supervisor_unavailable",
                    "message": tr("backend.managed_worker.the_service_is_switching_please_retry_shortly"),
                },
            ) from exc

    def status(self) -> dict[str, Any]:
        return self._call("management", {})

    def plan(self, body: PlanRequest) -> dict[str, Any]:
        return self._call("plan", body.model_dump())

    def execute(self, body: ExecuteRequest) -> dict[str, Any]:
        return self._call("execute", body.model_dump())

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        return self._call("task", {"task_id": task_id})

    def recover(self) -> dict[str, Any]:
        return self._call("recover", {})


class InheritedDescriptor(Protocol):
    def detach(self) -> int: ...


def prepare_runtime_session() -> dict[str, Any]:
    """Pause only if the complete recovery snapshot can be transferred safely."""
    from sqlseed_web.runtime_lifecycle import runtime_gate
    from sqlseed_web.runtime_session import export_session

    runtime_gate.pause_if_idle()
    try:
        snapshot = export_session()
        try:
            validate_control_result(snapshot)
        except ControlMessageTooLarge as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "plugin_session_too_large",
                    "message": tr("backend.managed_worker.too_many_connections_or_session_details_to"),
                },
            ) from exc
        return snapshot
    except Exception:
        runtime_gate.resume()
        raise


def _worker_control(method: str, mode: str, server: uvicorn.Server | None, gate: RuntimeGate) -> dict[str, Any]:
    if method == "activity":
        return gate.activity()
    if method == "prepare":
        return prepare_runtime_session()
    if method == "resume":
        gate.resume()
        return {}
    if method == "shutdown":
        if mode == "business":
            from sqlseed_web.runtime_session import close_session

            gate.pause_if_idle()
            close_session()
        if server is not None:
            server.should_exit = True
        return {}
    raise ValueError("unsupported worker control method")


def _drain_worker_runtime(mode: str, gate: RuntimeGate) -> None:
    """Close admission and finish existing leases before closing database sessions."""
    gate.close_admission()
    while any(gate.activity().values()):
        time.sleep(0.05)
    if mode == "business":
        from sqlseed_web.runtime_session import close_session

        close_session()


def _serve_worker(server: uvicorn.Server, listener: socket.socket) -> None:
    if sys.platform != "win32":
        server.run(sockets=[listener])
        return
    # A duplicated listener cannot be attached to a new IOCP after a worker
    # swap. Selector owns no IOCP association; package/IPC subprocesses remain
    # in synchronous threads, so they do not need Proactor subprocess support.
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.serve(sockets=[listener]))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        asyncio.set_event_loop(None)


def run_worker(
    listener: socket.socket,
    connection: ControlTransport,
    mode: str,
    session: dict[str, Any],
    token: str,
    lock_descriptor: InheritedDescriptor | None = None,
) -> None:
    """Spawn target: the parent owns signals, listener lifetime, and package state."""
    import uvicorn

    from sqlseed_web._application import create_app
    from sqlseed_web.runtime_lifecycle import runtime_gate

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    channel = ControlChannel(connection)
    manager = RemotePluginManager(channel, token)
    result: dict[str, Any] = {}
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    lock_fd = lock_descriptor.detach() if lock_descriptor is not None else None

    def control(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return _worker_control(method, mode, server, runtime_gate)

    channel.start(control)
    stage = "session"
    announced_ready = False
    try:
        channel.call("worker_starting", {"mode": mode, "phase": stage})
        runtime_gate.pause_if_idle()
        if mode == "business":
            from sqlseed_web.runtime_session import restore_session

            result = (
                restore_session(session)
                if session
                else {
                    "restored_connections": 0,
                    "failed_connections": [],
                    "ai_session_restored": True,
                }
            )
        stage = "application"
        channel.call("worker_starting", {"mode": mode, "phase": stage})
        app = create_app(manage_plugins=mode == "maintenance", management_service=manager, supervised_worker=True)
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, lifespan="on", timeout_graceful_shutdown=None
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=_serve_worker, args=(server, listener), daemon=False, name="sqlseed-http-worker"
        )
        stage = "http"
        channel.call("worker_starting", {"mode": mode, "phase": stage})
        thread.start()
        while thread.is_alive() and not server.started:
            time.sleep(0.01)
        if server.started:
            channel.call("worker_ready", {"mode": mode, "restoration": result})
            announced_ready = True
        else:
            raise RuntimeError(tr("backend.supervisor.worker_startup_failed"))
        while thread.is_alive():
            if channel.wait_closed(0.1):
                break
    except (HTTPException, ImportError, OSError, RuntimeError, TypeError, ValueError):
        if not announced_ready:
            try:
                channel.call("worker_failed", {"mode": mode, "phase": stage})
            except (OSError, RuntimeError):
                pass
        # Import/ASGI failures may contain credentials or driver parameters.
        raise RuntimeError(tr("backend.supervisor.worker_startup_failed")) from None
    finally:
        _drain_worker_runtime(mode, runtime_gate)
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join()
        channel.close()
        listener.close()
        if lock_fd is not None:
            os.close(lock_fd)
