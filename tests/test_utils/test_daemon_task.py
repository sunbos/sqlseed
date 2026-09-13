"""Thread outcomes must survive timeouts and cross the Future boundary intact."""

from __future__ import annotations

import threading
from concurrent.futures import TimeoutError as FutureTimeoutError

import pytest

from sqlseed._utils.daemon_task import DaemonTask


def test_daemon_task_publishes_result_and_callbacks() -> None:
    task = DaemonTask(lambda: (threading.current_thread().daemon, 42))
    observed = []
    task.add_done_callback(lambda completed: observed.append(completed.result()))
    assert task.wait(2)
    assert task.result() == (True, 42)
    assert observed == [(True, 42)]


@pytest.mark.parametrize("error", [ValueError("invalid"), LookupError("missing"), KeyboardInterrupt(), SystemExit(9)])
def test_daemon_task_relays_original_error(error: BaseException) -> None:
    def fail() -> None:
        raise error

    task = DaemonTask(fail)
    assert task.wait(2)
    with pytest.raises(type(error)) as caught:
        task.result()
    assert caught.value is error
    assert task.exception() is error


def test_timeout_does_not_complete_or_cancel_running_work() -> None:
    release = threading.Event()
    task = DaemonTask(lambda: release.wait(2))
    try:
        assert not task.wait(0.001)
        with pytest.raises(FutureTimeoutError):
            task.result(timeout=0.001)
        assert not task.done()
        assert not task.cancel()
    finally:
        release.set()
    assert task.wait(2)
    assert task.result() is True


def test_completion_callback_is_registered_before_fast_worker_starts() -> None:
    caller = threading.get_ident()
    observed = []

    def completed(future) -> None:
        observed.append((threading.get_ident(), future.result()))

    task = DaemonTask(lambda: 17, on_done=completed)
    assert task.wait(2)
    assert len(observed) == 1
    assert observed[0][0] != caller
    assert observed[0][1] == 17
