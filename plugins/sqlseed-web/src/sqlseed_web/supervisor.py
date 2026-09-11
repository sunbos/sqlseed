"""Stable listener and private supervisor for replaceable Web worker processes."""

from __future__ import annotations

import multiprocessing
import signal
import socket
import threading
import time
from multiprocessing.context import SpawnProcess
from typing import Any

from fastapi import HTTPException

from sqlseed_web.managed_worker import run_worker
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.supervised_plugins import SupervisedPluginManager
from sqlseed_web.worker_control import ControlChannel, ControlError


class Supervisor:
    """One supervised app owns its environment, children, and listening socket."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8630) -> None:
        self.host, self.port = host, port
        self.manager = SupervisedPluginManager(self)
        self.listener: socket.socket | None = None
        self.process: SpawnProcess | None = None
        self.channel: ControlChannel | None = None
        self.mode: str | None = None
        self._session: dict[str, Any] = {}
        self._ready = threading.Event()
        self._restoration: dict[str, Any] = {}
        self._lifecycle_lock = threading.RLock()
        self._shutdown_requested = False
        self._session_lost = False

    def start(self) -> None:
        if self.manager.environment.reason is None:
            self.manager.start()
        if self.manager.environment.reason is None and self.manager._environment_lock is None:
            raise RuntimeError("此 Python 环境正被另一个 Web 服务使用，无法启动受管服务。")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
            listener.listen(2048)
            self.port = listener.getsockname()[1]
            self.listener = listener
            self.manager.phase = "preparing"
            self._spawn("business")
            self.manager.phase = "ready"
        except Exception:
            self.stop()
            listener.close()
            raise

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.channel is None:
            raise RuntimeError("业务进程暂不可用。")
        try:
            return self.channel.call(method, params or {})
        except ControlError as exc:
            raise HTTPException(exc.status_code, detail=exc.detail) from exc

    def _handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "worker_ready":
            self._restoration = dict(params.get("restoration", {}))
            self._ready.set()
            return {}
        if method == "management":
            return self.manager.status()
        if method == "plan":
            return self.manager.plan(PlanRequest.model_validate(params))
        if method == "execute":
            return self.manager.execute(ExecuteRequest.model_validate(params))
        if method == "task":
            return self.manager.task_snapshot(params.get("task_id"))
        if method == "recover":
            return self.manager.recover()
        raise ValueError("unsupported supervisor method")

    def _spawn(self, mode: str) -> dict[str, Any]:
        if self.listener is None:
            raise RuntimeError("服务监听端口不可用。")
        self._ready.clear()
        self._restoration = {}
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        channel = ControlChannel(parent)
        lock_descriptor = None
        if self.manager._environment_lock is not None:
            from multiprocessing.reduction import DupFd

            lock_descriptor = DupFd(self.manager._environment_lock.fileno())
        process = context.Process(
            target=run_worker,
            args=(
                self.listener,
                child,
                mode,
                self._session if mode == "business" else {},
                self.manager.token,
                lock_descriptor,
            ),
            name=f"sqlseed-{mode}-worker",
            daemon=False,
        )
        self.channel, self.process, self.mode = channel, process, mode
        self._shutdown_requested = False
        process.start()
        child.close()
        channel.start(self._handle)
        deadline = time.monotonic() + 20
        while not self._ready.wait(0.05):
            if not process.is_alive() or time.monotonic() >= deadline:
                # No public API was admitted before readiness. A failed boot
                # can be stopped without interrupting a generation transaction.
                if process.is_alive():
                    process.kill()
                process.join(timeout=3)
                channel.close()
                self.channel, self.process, self.mode = None, None, None
                raise RuntimeError("业务服务启动未完成，请在页面重试恢复。")
        if mode == "business":
            self._request("resume")
        return dict(self._restoration)

    def _stop_worker(self) -> None:
        process = self.process
        if process is None:
            return
        if process.is_alive():
            if not self._shutdown_requested:
                try:
                    self._request("shutdown")
                except RuntimeError:
                    # EOF makes the owned worker close admission and drain;
                    # losing control never permits proceeding to installation.
                    if self.channel is not None:
                        self.channel.close()
                self._shutdown_requested = True
            process.join(timeout=20)
            if process.is_alive():
                raise RuntimeError("业务进程尚未自然退出，未执行环境变更。")
        if self.channel is not None:
            self.channel.close()
        self.channel, self.process, self.mode = None, None, None

    def pause(self) -> None:
        if self.mode != "business":
            raise HTTPException(409, detail={"code": "service_not_ready", "message": "业务服务尚未就绪。"})
        self._session = self._request("prepare")
        self._session_lost = False

    def resume(self) -> None:
        if self.mode == "business":
            self._request("resume")
        self._session = {}

    def enter_maintenance(self) -> None:
        with self._lifecycle_lock:
            self._stop_worker()
            self._spawn("maintenance")

    def restore_business(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            if (
                self.mode == "business"
                and self.process is not None
                and self.process.is_alive()
                and not self._shutdown_requested
            ):
                self.resume()
                return {"restored_connections": 0, "failed_connections": [], "service_restarted": False}
            self._stop_worker()
            try:
                restored = self._spawn("business")
            except Exception:
                self._spawn("maintenance")
                raise
            self._session = {}
            return {**restored, **self._lost_session_summary(), "service_restarted": True}

    def _lost_session_summary(self) -> dict[str, Any]:
        if not self._session_lost:
            return {}
        return {"session_lost": True, "message": "业务进程意外退出，原有连接与会话密钥需要重新配置。"}

    def ensure_worker(self) -> None:
        """Keep a recovery page available after an unexpected worker exit."""
        with self._lifecycle_lock:
            with self.manager._lock:
                if self.manager.phase != "ready" or self.process is None or self.process.is_alive():
                    return
                self.manager.phase = "recovery_failed"
                self._session_lost = True
                self._session = {}
                self.manager.session_restore = self._lost_session_summary()
                self.manager._task = None
            self._stop_worker()
            self._spawn("maintenance")

    def stop(self) -> None:
        if self.manager._worker is not None:
            self.manager._worker.join()
        with self._lifecycle_lock:
            while self.process is not None:
                try:
                    self._stop_worker()
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    # Explicit shutdown waits for existing work; it never
                    # kills running SQL or an SDK thread that has not exited.
                    time.sleep(0.1)
            self.manager.stop()
            if self.listener is not None:
                self.listener.close()
                self.listener = None


def run_supervised() -> None:
    """Default console launch: plugin changes and recovery remain in the page."""
    stopped = threading.Event()

    def stop(signum: int, frame: Any) -> None:
        stopped.set()

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    supervisor = Supervisor()
    try:
        supervisor.start()
        while not stopped.wait(0.25):
            supervisor.ensure_worker()
    finally:
        supervisor.stop()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
