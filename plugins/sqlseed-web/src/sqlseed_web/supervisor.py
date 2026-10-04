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
from sqlseed._utils.logger import get_logger

from sqlseed_web.managed_worker import WorkerLifecycleError, run_worker
from sqlseed_web.messages import message as tr
from sqlseed_web.plugin_environment import InheritedEnvironmentLock
from sqlseed_web.plugin_management import ExecuteRequest, PlanRequest
from sqlseed_web.supervised_plugins import SupervisedPluginManager
from sqlseed_web.worker_control import ControlChannel, ControlError

logger = get_logger(__name__)
WORKER_START_TIMEOUT = 20
WORKER_STOP_TIMEOUT = 20


class Supervisor:
    """One supervised app owns its environment, children, and listening socket."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8630) -> None:
        """Initialize lifecycle ownership without opening a listener or starting workers."""
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
        self._business_ready = False
        self._startup_phase = "boot"
        self._startup_failed = False

    def start(self) -> None:
        if self.manager.environment.reason is None:
            self.manager.start()
        if self.manager.environment.reason is None and self.manager._environment_lock is None:
            raise RuntimeError(tr("backend.supervisor.another_web_service_is_using_this_python"))
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
            raise RuntimeError(tr("backend.supervisor.the_application_process_is_temporarily_unavailable"))
        try:
            return self.channel.call(method, params or {})
        except ControlError as exc:
            raise HTTPException(exc.status_code, detail=exc.detail) from exc

    def _handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Validate worker lifecycle reports and dispatch private management requests."""
        if method in {"worker_starting", "worker_failed"}:
            phase = params.get("phase")
            if params.get("mode") != self.mode or phase not in {"session", "application", "http"}:
                raise ValueError("invalid worker startup status")
            self._startup_phase = phase
            self._startup_failed = method == "worker_failed"
            return {}
        if method == "worker_ready":
            if params.get("mode") != self.mode:
                raise ValueError("unexpected worker readiness")
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
        """Start an unowned worker and confirm business admission before returning restoration results."""
        if self.listener is None:
            raise RuntimeError(tr("backend.supervisor.the_service_listening_port_is_unavailable"))
        if self.process is not None:
            raise self._failure("worker_stop_pending", time.monotonic(), phase="shutdown")
        self._ready.clear()
        self._restoration = {}
        self._business_ready = False
        self._startup_phase = "boot"
        self._startup_failed = False
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        channel = ControlChannel(parent)
        lock_descriptor = None
        if self.manager._environment_lock is not None:
            lock_descriptor = InheritedEnvironmentLock(self.manager._environment_lock.fileno())
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
        started = time.monotonic()
        try:
            process.start()
        except (OSError, RuntimeError, ValueError):
            error = self._failure("worker_startup_failed", started)
            channel.close()
            self.channel, self.process, self.mode = None, None, None
            raise error from None
        finally:
            child.close()
        channel.start(self._handle)
        self._wait_for_worker_ready(process, channel, started)
        if mode == "business":
            self._startup_phase = "resume"
            try:
                self._request("resume")
            except (HTTPException, OSError, RuntimeError, ValueError):
                # The worker may have resumed before its acknowledgement was
                # lost. Keep ownership so recovery drains it before replacement.
                raise self._failure("worker_resume_failed", started) from None
            self._business_ready = True
        return dict(self._restoration)

    def _wait_for_worker_ready(self, process: SpawnProcess, channel: ControlChannel, started: float) -> None:
        """Bound pre-admission startup and retain ownership until failed workers have exited."""
        deadline = time.monotonic() + WORKER_START_TIMEOUT
        while not self._ready.wait(0.05):
            if not self._startup_failed and process.is_alive() and time.monotonic() < deadline:
                continue
            if self._startup_failed:
                code = "worker_startup_failed"
            elif process.is_alive():
                code = "worker_startup_timeout"
            else:
                code = "worker_exited_before_ready"
            error = self._failure(code, started)
            # No public API was admitted before readiness. A failed boot
            # can be stopped without interrupting a generation transaction.
            if process.is_alive():
                process.kill()
            process.join(timeout=3)
            channel.close()
            if not process.is_alive():
                self.channel, self.process, self.mode = None, None, None
            raise error

    def _failure(self, code: str, started: float, *, phase: str | None = None) -> WorkerLifecycleError:
        """Record credential-free lifecycle facts for the task result and diagnostic log."""
        error = WorkerLifecycleError(
            code,
            mode=self.mode or "business",
            phase=phase or self._startup_phase,
            elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
            exit_code=self.process.exitcode if self.process is not None else None,
        )
        logger.warning(
            "worker_lifecycle_failed", **{key: value for key, value in error.detail.items() if key != "message"}
        )
        return error

    def _stop_worker(self) -> None:
        """Request a natural drain, keeping process ownership when shutdown is not yet confirmed."""
        if (process := self.process) is None:
            return
        started = time.monotonic()
        self._business_ready = False
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
            process.join(timeout=WORKER_STOP_TIMEOUT)
            if process.is_alive():
                raise self._failure("worker_shutdown_timeout", started, phase="shutdown")
        if self.channel is not None:
            self.channel.close()
        self.channel, self.process, self.mode = None, None, None

    def pause(self) -> None:
        if self.mode != "business":
            raise HTTPException(
                409,
                detail={
                    "code": "service_not_ready",
                    "message": tr("backend.supervisor.the_application_is_not_ready_yet"),
                },
            )
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
        """Resume or replace the business worker, restoring maintenance only after a safe shutdown."""
        with self._lifecycle_lock:
            if (
                self.mode == "business"
                and self.process is not None
                and self.process.is_alive()
                and not self._shutdown_requested
                and self._business_ready
            ):
                self.resume()
                return {"restored_connections": 0, "failed_connections": [], "service_restarted": False}
            self._stop_worker()
            try:
                restored = self._spawn("business")
            except Exception:
                # A failed resume acknowledgement does not mean the new worker
                # exited. Never overwrite its process/channel or share its
                # listener with maintenance until natural shutdown is confirmed.
                self._stop_worker()
                self._spawn("maintenance")
                raise
            self._session = {}
            return {**restored, **self._lost_session_summary(), "service_restarted": True}

    def _lost_session_summary(self) -> dict[str, Any]:
        if not self._session_lost:
            return {}
        return {
            "session_lost": True,
            "message": tr("backend.supervisor.the_application_process_stopped_unexpectedly_reconfigure_connections"),
        }

    def ensure_worker(self) -> None:
        """Keep a recovery page available after an unexpected worker exit."""
        with self._lifecycle_lock:
            with self.manager._lock:
                if (
                    self.manager.phase not in {"ready", "recovery_failed"}
                    or self.process is None
                    or self.process.is_alive()
                    or (self.manager._worker is not None and self.manager._worker.is_alive())
                ):
                    return
                if self.manager.phase == "ready":
                    self.manager.phase = "recovery_failed"
                    self._session_lost = True
                    self._session = {}
                    self.manager.session_restore = self._lost_session_summary()
                    self.manager._task = None
                # A retained worker can finish draining after recovery already
                # reported a timeout. Restore the maintenance listener once it
                # exits, preserving the saved session and package task for retry.
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
