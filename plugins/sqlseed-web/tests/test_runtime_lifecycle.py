"""Runtime leases survive response cancellation and real worker cleanup."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest
from fastapi import HTTPException

from sqlseed_web import runtime_lifecycle, workbench_ai_stream
from sqlseed_web.runtime_lifecycle import RuntimeAdmissionMiddleware, RuntimeGate, start_background


@pytest.fixture(name="gate")
def fixture_gate(monkeypatch: pytest.MonkeyPatch) -> RuntimeGate:
    value = RuntimeGate()
    monkeypatch.setattr(runtime_lifecycle, "runtime_gate", value)
    return value


def test_idle_pause_is_atomic_idempotent_and_resume_allows_new_work(gate: RuntimeGate) -> None:
    assert gate.pause_if_idle() == {"requests": 0, "background_jobs": 0, "ai_analyses": 0}
    assert gate.pause_if_idle() == gate.activity()
    with pytest.raises(HTTPException) as rejected:
        start_background(target=lambda: None, category="job")
    assert rejected.value.status_code == 503
    gate.resume()
    worker = start_background(target=lambda: None, category="job")
    worker.join(5)
    assert not worker.is_alive()
    assert gate.activity() == {"requests": 0, "background_jobs": 0, "ai_analyses": 0}


def test_close_admission_rejects_new_work_while_existing_leases_finish(gate: RuntimeGate) -> None:
    entered, finish = threading.Event(), threading.Event()

    def work() -> None:
        entered.set()
        assert finish.wait(5)

    worker = start_background(target=work, category="job")
    try:
        assert entered.wait(5)
        with gate.request():
            assert gate.close_admission() == {"requests": 1, "background_jobs": 1, "ai_analyses": 0}
            assert gate.close_admission() == gate.activity()
            with pytest.raises(HTTPException) as rejected, gate.request():
                pytest.fail("A new request entered after admission closed")
            assert rejected.value.status_code == 503
            with pytest.raises(HTTPException):
                start_background(target=lambda: None, category="ai")
        assert gate.activity() == {"requests": 0, "background_jobs": 1, "ai_analyses": 0}
    finally:
        finish.set()
        worker.join(5)
    assert not worker.is_alive()
    assert gate.pause_if_idle() == {"requests": 0, "background_jobs": 0, "ai_analyses": 0}


@pytest.mark.parametrize("category, counter", [("job", "background_jobs"), ("ai", "ai_analyses")])
def test_background_lease_outlives_published_completion_and_releases_after_cleanup(
    gate: RuntimeGate, category: str, counter: str
) -> None:
    published, release = threading.Event(), threading.Event()
    status: list[str] = []

    def work() -> None:
        status.append("done")
        published.set()
        assert release.wait(5)

    worker = start_background(target=work, category=category)
    try:
        assert published.wait(5)
        assert status == ["done"]
        assert gate.activity()[counter] == 1
        with pytest.raises(HTTPException) as rejected:
            gate.pause_if_idle()
        assert rejected.value.status_code == 409
        assert rejected.value.detail["code"] == "plugin_management_busy"
        assert rejected.value.detail["activity"][counter] == 1
    finally:
        release.set()
        worker.join(5)
    assert gate.pause_if_idle()[counter] == 0


def test_start_failure_releases_lease_registered_before_thread_start(
    gate: RuntimeGate, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, int]] = []

    class FailedThread:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(gate.activity())

        def start(self) -> None:
            raise RuntimeError("cannot start worker")

    monkeypatch.setattr(runtime_lifecycle.threading, "Thread", FailedThread)
    with pytest.raises(RuntimeError, match="cannot start worker"):
        start_background(target=lambda: None, category="job")
    assert seen == [{"requests": 0, "background_jobs": 1, "ai_analyses": 0}]
    assert gate.pause_if_idle()["background_jobs"] == 0


def test_a_worker_exception_releases_its_lease(gate: RuntimeGate, monkeypatch: pytest.MonkeyPatch) -> None:
    failures: list[type[BaseException]] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: failures.append(args.exc_type))

    def work() -> None:
        raise RuntimeError("failed work")

    worker = start_background(target=work, category="job")
    worker.join(5)
    assert failures == [RuntimeError]
    assert gate.pause_if_idle()["background_jobs"] == 0


def test_middleware_tracks_the_whole_stream_including_post_response_cleanup(gate: RuntimeGate) -> None:
    async def scenario() -> None:
        started, finish_body, sent_body, finish_app = (asyncio.Event() for _ in range(4))
        messages: list[dict[str, Any]] = []

        async def application(scope: Any, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"progress", "more_body": True})
            started.set()
            await finish_body.wait()
            await send({"type": "http.response.body", "body": b"complete"})
            sent_body.set()
            await finish_app.wait()

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        task = asyncio.create_task(
            RuntimeAdmissionMiddleware(application)({"type": "http", "path": "/api/data"}, receive, send)
        )
        await started.wait()
        assert gate.activity()["requests"] == 1
        with pytest.raises(HTTPException):
            gate.pause_if_idle()
        finish_body.set()
        await sent_body.wait()
        assert messages[-1]["body"] == b"complete"
        assert gate.activity()["requests"] == 1
        finish_app.set()
        await task
        assert gate.pause_if_idle()["requests"] == 0

    asyncio.run(scenario())


def test_paused_middleware_admits_management_only_and_resume_restores_business(gate: RuntimeGate) -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def application(scope: Any, receive: Any, send: Any) -> None:
            calls.append(scope["path"])
            assert gate.activity()["requests"] == (0 if scope["path"].startswith("/api/settings/plugins/") else 1)
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b""}

        wrapper = RuntimeAdmissionMiddleware(application)
        gate.pause_if_idle()
        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        for path, status in (
            ("/api/settings/plugins/management", 204),
            ("/api/workbench/preview", 503),
            ("/static/app.js", 503),
            ("/api/settings/plugins-extra", 503),
        ):
            messages.clear()
            await wrapper({"type": "http", "path": path}, receive, send)
            assert messages[0]["status"] == status
        assert calls == ["/api/settings/plugins/management"]
        gate.resume()
        await wrapper({"type": "http", "path": "/api/data"}, receive, send)
        assert calls[-1] == "/api/data"
        assert gate.activity()["requests"] == 0

    asyncio.run(scenario())


def test_cancelled_http_request_releases_only_the_request_lease(gate: RuntimeGate) -> None:
    entered, release = threading.Event(), threading.Event()
    operation = workbench_ai_stream.AnalysisOperation(
        "lease-test", lambda progress, check: (entered.set(), release.wait(5), {})[-1]
    )
    assert entered.wait(5)

    async def scenario() -> None:
        started = asyncio.Event()

        async def application(scope: Any, receive: Any, send: Any) -> None:
            started.set()
            await asyncio.Event().wait()

        async def unused(*args: Any) -> Any:
            return None

        task = asyncio.create_task(
            RuntimeAdmissionMiddleware(application)({"type": "http", "path": "/api/ai"}, unused, unused)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        operation.cancelled.set()
        assert gate.activity() == {"requests": 0, "background_jobs": 0, "ai_analyses": 1}
        with pytest.raises(HTTPException):
            gate.pause_if_idle()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        operation.task.wait(5)
    assert gate.pause_if_idle()["ai_analyses"] == 0


def test_analysis_worker_fatal_exit_publishes_one_error_and_releases_admission(gate: RuntimeGate) -> None:
    class WorkerStopped(BaseException):
        pass

    def run(progress: Any, check: Any) -> dict[str, Any]:
        raise WorkerStopped("private-runtime-secret")

    operation = workbench_ai_stream.AnalysisOperation("fatal-analysis", run)
    assert operation.task.wait(3)

    async def events() -> list[dict[str, Any]]:
        return [event async for event in operation.events()]

    result = asyncio.run(events())
    assert len(result) == 1
    assert result[0]["type"] == "error"
    assert result[0]["code"] == "ai_analysis_failed"
    assert "private-runtime-secret" not in str(result)
    assert gate.pause_if_idle()["ai_analyses"] == 0
    gate.resume()
    retry = workbench_ai_stream.AnalysisOperation("fatal-analysis", lambda progress, check: {"ok": True})
    assert retry.task.wait(3)
    assert retry.queue.get_nowait() == {"type": "result", "result": {"ok": True}}
