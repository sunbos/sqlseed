"""Atomic runtime admission and leases held until real request/worker exit."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RuntimeGate:
    """Reject a runtime pause while any admitted work still owns a lease."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paused = False
        self._counts = {"requests": 0, "background_jobs": 0, "ai_analyses": 0}

    def activity(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def close_admission(self) -> dict[str, int]:
        """Reject new work immediately while existing leases drain normally."""
        with self._lock:
            self._paused = True
            return dict(self._counts)

    def pause_if_idle(self) -> dict[str, int]:
        with self._lock:
            activity = dict(self._counts)
            if any(activity.values()):
                raise HTTPException(
                    409,
                    detail={
                        "code": "plugin_management_busy",
                        "message": "当前仍有请求或后台任务运行，请等待完成后再管理插件。",
                        "activity": activity,
                    },
                )
            self._paused = True
            return activity

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def acquire(self, category: Literal["requests", "background_jobs", "ai_analyses"]) -> None:
        with self._lock:
            if self._paused:
                raise HTTPException(
                    503,
                    detail={
                        "code": "plugin_runtime_paused",
                        "message": "正在更新插件，服务恢复后即可继续使用。",
                    },
                )
            self._counts[category] += 1

    def release(self, category: Literal["requests", "background_jobs", "ai_analyses"]) -> None:
        with self._lock:
            if self._counts[category] <= 0:
                raise RuntimeError("A runtime lease cannot be released twice")
            self._counts[category] -= 1

    @contextmanager
    def request(self) -> Iterator[None]:
        self.acquire("requests")
        try:
            yield
        finally:
            self.release("requests")


runtime_gate = RuntimeGate()


class RuntimeAdmissionMiddleware:
    """Count complete ASGI calls, including streams and response background work."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/api/settings/plugins/"):
            await self.app(scope, receive, send)
            return
        gate = runtime_gate
        try:
            gate.acquire("requests")
        except HTTPException as exc:
            await JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            gate.release("requests")


def start_background(
    *,
    target: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    category: Literal["job", "ai"],
    daemon: bool = True,
    name: str | None = None,
) -> threading.Thread:
    """Reserve before startup; release only when the target has actually exited."""
    gate = runtime_gate
    lease: Literal["background_jobs", "ai_analyses"] = "ai_analyses" if category == "ai" else "background_jobs"
    gate.acquire(lease)

    def run() -> None:
        try:
            target(*args, **(kwargs or {}))
        finally:
            gate.release(lease)

    try:
        thread = threading.Thread(target=run, daemon=daemon, name=name)
        thread.start()
    except BaseException:
        gate.release(lease)
        raise
    return thread
