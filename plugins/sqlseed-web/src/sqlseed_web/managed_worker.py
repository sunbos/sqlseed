"""Fresh business and maintenance workers controlled by the stable launcher."""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from multiprocessing.connection import Connection
from typing import Any, Protocol

from fastapi import HTTPException

from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.worker_control import ControlChannel, ControlError, ControlMessageTooLarge, validate_control_result


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
                503, detail={"code": "supervisor_unavailable", "message": "服务正在切换，请稍后重试。"}
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
                    "message": "当前连接与会话信息过多，无法安全暂存；请减少连接后再管理插件。",
                },
            ) from exc
        return snapshot
    except Exception:
        runtime_gate.resume()
        raise


def run_worker(
    listener: socket.socket,
    connection: Connection,
    mode: str,
    session: dict[str, Any],
    token: str,
    lock_descriptor: InheritedDescriptor | None = None,
) -> None:
    """Spawn target: the parent owns signals, listener lifetime, and package state."""
    import uvicorn

    from sqlseed_web.app import create_app
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
        if method == "activity":
            return runtime_gate.activity()
        if method == "prepare":
            return prepare_runtime_session()
        if method == "resume":
            runtime_gate.resume()
            return {}
        if method == "shutdown":
            if mode == "business":
                from sqlseed_web.runtime_session import close_session

                runtime_gate.pause_if_idle()
                close_session()
            if server is not None:
                server.should_exit = True
            return {}
        raise ValueError("unsupported worker control method")

    channel.start(control)
    try:
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
        app = create_app(manage_plugins=mode == "maintenance", management_service=manager, supervised_worker=True)
        config = uvicorn.Config(
            app, log_level="warning", access_log=False, lifespan="on", timeout_graceful_shutdown=None
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [listener]}, daemon=False, name="sqlseed-http-worker"
        )
        thread.start()
        while thread.is_alive() and not server.started:
            time.sleep(0.01)
        if server.started:
            channel.call("worker_ready", {"mode": mode, "restoration": result})
        while thread.is_alive():
            if channel.wait_closed(0.1):
                break
    finally:
        runtime_gate.close_admission()
        while any(runtime_gate.activity().values()):
            time.sleep(0.05)
        if mode == "business":
            from sqlseed_web.runtime_session import close_session

            close_session()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join()
        channel.close()
        listener.close()
        if lock_fd is not None:
            os.close(lock_fd)
