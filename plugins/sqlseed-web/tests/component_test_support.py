"""Recorded protocol boundaries and bounded resources for component tests."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Semaphore
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException


class HTTPExchange:
    """A single recorded HTTP exchange with fresh response bytes per request."""

    sock = None

    def __init__(self, *, status: int, body: bytes = b"") -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[Any, ...]] = []
        self.closed: list[bool] = []

    def connection(self, host: str, timeout: float) -> HTTPExchange:
        self.calls.append((host, timeout))
        return self

    def request(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.calls.append((method, path, headers))

    def getresponse(self) -> SimpleNamespace:
        return SimpleNamespace(status=self.status, read1=io.BytesIO(self.body).read1)

    def close(self) -> None:
        self.closed.append(True)


class RecordingController:
    """Record lifecycle order while allowing explicit busy/restore failures."""

    def __init__(self, *, restored: dict[str, Any], calls: list[str] | None = None) -> None:
        self.calls = [] if calls is None else calls
        self.restored = restored
        self.busy = False
        self.restoration_error = False

    def pause(self) -> None:
        if self.busy:
            raise HTTPException(409, detail={"code": "plugin_management_busy", "message": "正在生成数据。"})
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def enter_maintenance(self) -> None:
        self.calls.append("maintenance")

    def restore_business(self) -> dict[str, Any]:
        self.calls.append("restore")
        if self.restoration_error:
            raise RuntimeError("private-error")
        return self.restored.copy()


@contextmanager
def acquired_with_timeout(semaphore: Semaphore, *, timeout: float) -> Iterator[None]:
    """Bound acquisition and release ownership even if the protected assertion fails."""
    if not semaphore.acquire(timeout=timeout):
        raise AssertionError(f"Semaphore was not released within {timeout} seconds")
    try:
        yield
    finally:
        semaphore.release()


@contextmanager
def bounded_process(arguments: list[str], *, creationflags: int = 0) -> Iterator[subprocess.Popen[bytes]]:
    """Reap a direct child without Popen.__exit__'s unbounded wait."""
    process = subprocess.Popen(arguments, creationflags=creationflags)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
