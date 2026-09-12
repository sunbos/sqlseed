"""Bounded, cancellable delivery of synchronous AI work without a database lease."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future
from queue import Empty, Full, Queue
from threading import Event, Lock
from time import monotonic
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlseed._utils.daemon_task import DaemonTask

from sqlseed_web import runtime_lifecycle

ANALYSIS_TIMEOUT = 180.0
_active: set[str] = set()
_active_lock = Lock()
Analysis = Callable[[Callable[[str, str], None], Callable[[], None]], dict[str, Any]]


def _error(exc: HTTPException) -> dict[str, Any]:
    detail = exc.detail
    return {
        "type": "error",
        "code": detail.get("code", "ai_analysis_failed") if isinstance(detail, dict) else "ai_analysis_failed",
        "message": detail.get("message", "AI 分析失败，请重试。") if isinstance(detail, dict) else str(detail),
        "status": exc.status_code,
    }


class AnalysisOperation:
    """Own the in-flight gate until the worker actually exits, even after disconnect."""

    def __init__(self, conn_id: str, run: Analysis) -> None:
        self.cancelled = Event()
        self.deadline = monotonic() + ANALYSIS_TIMEOUT
        self.queue: Queue[dict[str, Any]] = Queue(maxsize=16)
        with _active_lock:
            if conn_id in _active:
                raise HTTPException(
                    409, detail={"code": "ai_busy", "message": "此连接的 AI 分析尚未结束，请稍后重试。"}
                )
            _active.add(conn_id)

        gate = runtime_lifecycle.runtime_gate
        try:
            gate.acquire("ai_analyses")
        except BaseException:
            with _active_lock:
                _active.discard(conn_id)
            raise

        def worker() -> dict[str, Any]:
            self.check_cancelled()
            result = run(self.progress, self.check_cancelled)
            self.check_cancelled()
            return result

        def finished(task: Future[dict[str, Any]]) -> None:
            try:
                if (failure := task.exception()) is None:
                    self.publish({"type": "result", "result": task.result()})
                elif isinstance(failure, HTTPException):
                    self.publish(_error(failure))
                else:
                    self.publish(
                        _error(
                            HTTPException(
                                500,
                                detail={
                                    "code": "ai_analysis_failed",
                                    "message": "AI 分析未完成，请重试；当前规则未改变。",
                                },
                            )
                        )
                    )
            finally:
                with _active_lock:
                    _active.discard(conn_id)
                gate.release("ai_analyses")

        try:
            self.task = DaemonTask(worker, name="sqlseed-ai-analysis", on_done=finished)
        except BaseException:
            gate.release("ai_analyses")
            with _active_lock:
                _active.discard(conn_id)
            raise

    def publish(self, event: dict[str, Any]) -> None:
        # There are four phase events and one terminal event. Keep the queue
        # bounded even if a future caller reports more frequently.
        try:
            self.queue.put_nowait(event)
        except Full:
            try:
                self.queue.get_nowait()
            except Empty:
                pass
            self.queue.put_nowait(event)

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise HTTPException(499, detail={"code": "ai_cancelled", "message": "分析已取消。"})
        if monotonic() >= self.deadline:
            raise HTTPException(504, detail={"code": "ai_timeout", "message": "分析超过时间限制，请缩小范围后重试。"})

    def progress(self, stage: str, message: str) -> None:
        self.check_cancelled()
        self.publish({"type": "progress", "stage": stage, "message": message})

    async def events(self, request: Request | None = None) -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                if request is not None and await request.is_disconnected():
                    return
                if monotonic() >= self.deadline:
                    yield _error(
                        HTTPException(
                            504, detail={"code": "ai_timeout", "message": "分析超过时间限制，请缩小范围后重试。"}
                        )
                    )
                    return
                try:
                    event = self.queue.get_nowait()
                except Empty:
                    await asyncio.sleep(0.025)
                    continue
                yield event
                if event["type"] in {"result", "error"}:
                    return
        finally:
            # This does not pretend to interrupt an SDK network call. The worker
            # checks the flag when that call returns, before any further DB work.
            self.cancelled.set()

    async def ndjson(self, request: Request | None = None) -> AsyncIterator[str]:
        try:
            async for event in self.events(request):
                yield (
                    json.dumps(
                        {key: value for key, value in event.items() if key != "status"}, ensure_ascii=False, default=str
                    )
                    + "\n"
                )
        finally:
            self.cancelled.set()


async def analysis_response(conn_id: str, run: Analysis, request: Request) -> dict[str, Any] | Response:
    operation = AnalysisOperation(conn_id, run)
    if "application/x-ndjson" in request.headers.get("accept", ""):
        # ASGI < 2.4 is watched by StreamingResponse itself. Newer ASGI
        # relies on send errors, so poll disconnect while the model is silent.
        spec = tuple(int(part) for part in request.scope.get("asgi", {}).get("spec_version", "2.0").split("."))
        watched_request = request if spec >= (2, 4) else None
        return StreamingResponse(
            operation.ndjson(watched_request),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    async for event in operation.events(request):
        if event["type"] == "result":
            return dict(event["result"])
        if event["type"] == "error":
            raise HTTPException(event["status"], detail={"code": event["code"], "message": event["message"]})
    raise HTTPException(499, detail={"code": "ai_cancelled", "message": "分析已取消。"})
