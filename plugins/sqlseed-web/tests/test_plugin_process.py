"""Installer subprocesses retain the environment lock independently of the parent."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import pytest

from sqlseed_web.plugin_environment import EnvironmentLock
from sqlseed_web.plugin_process import run_installer


@pytest.mark.skipif(os.name == "nt", reason="Managed package operations require POSIX process groups")
def test_installer_keeps_environment_locked_after_parent_descriptor_closes(tmp_path: Path) -> None:
    lock = EnvironmentLock(tmp_path, exclusive=True)
    lock.acquire()
    ready = threading.Event()
    finish = tmp_path / "finish"
    descriptor = lock.fileno()
    script = (
        "import pathlib,sys,time; print('ready',flush=True)\nwhile not "
        "pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)"
    )

    def run() -> int:
        try:
            return run_installer(
                [sys.executable, "-c", script, str(finish)],
                lambda text: ready.set(),
                timeout=10,
                lock_descriptor=descriptor,
            )
        finally:
            ready.set()

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(run)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    try:
        assert ready.wait(5)
        if future.done():
            future.result()
        lock.release()
        with pytest.raises(RuntimeError):
            contender.acquire()
    finally:
        finish.touch()
        executor.shutdown(wait=False, cancel_futures=True)
        try:
            result = future.result(timeout=15)
        finally:
            lock.release()
            contender.release()
    assert result == 0
    contender.acquire()
    contender.release()


def test_installer_reaps_child_when_output_worker_cannot_start(
    monkeypatch: pytest.MonkeyPatch, recorded_processes: list[subprocess.Popen[bytes]]
) -> None:
    children = recorded_processes

    def fail_start(self: threading.Thread) -> None:
        raise RuntimeError("cannot start output reader")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    try:
        with pytest.raises(RuntimeError, match="cannot start output reader"):
            run_installer([sys.executable, "-c", "import time; time.sleep(30)"], lambda text: None)
        assert len(children) == 1
        assert children[0].poll() is not None
        assert children[0].stdout is not None
        assert children[0].stdout.closed
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()


@pytest.mark.skipif(os.name == "nt", reason="Managed package operations require POSIX process groups")
@pytest.mark.parametrize("reject_repeated_signal", [False, True])
def test_output_start_failure_kills_descendant_after_installer_parent_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recorded_processes: list[subprocess.Popen[bytes]],
    reject_repeated_signal: bool,
) -> None:
    import errno
    import signal

    original_killpg = os.killpg
    signaled_groups: set[int] = set()

    def kill_group(group: int, requested_signal: int) -> None:
        if reject_repeated_signal and group in signaled_groups:
            raise PermissionError(errno.EPERM, "cannot signal an already terminated process group")
        original_killpg(group, requested_signal)
        signaled_groups.add(group)

    monkeypatch.setattr(os, "killpg", kill_group)
    lock = EnvironmentLock(tmp_path, exclusive=True)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    children = recorded_processes

    def fail_start(self: threading.Thread) -> None:
        children[0].wait(timeout=5)
        raise RuntimeError("output startup failed after installer exited")

    script = (
        "import subprocess,sys; descriptor=int(sys.argv[1]); "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],pass_fds=(descriptor,))"
    )
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with ExitStack() as cleanup:
        cleanup.callback(lock.release)
        cleanup.callback(contender.release)
        lock.acquire()
        descriptor = lock.fileno()
        descendants_exited = False
        try:
            with pytest.raises(RuntimeError, match="after installer exited"):
                run_installer(
                    [sys.executable, "-c", script, str(descriptor)], lambda text: None, lock_descriptor=descriptor
                )
            lock.release()
            _wait_for_environment_lock(contender)
            # The sleeping descendant retains its inherited descriptor until
            # termination. Reacquiring flock proves it no longer owns the lock.
            descendants_exited = True
        finally:
            for process in children:
                try:
                    if not descendants_exited:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait(timeout=5)
                finally:
                    if process.stdout is not None:
                        process.stdout.close()


def _wait_for_environment_lock(lock: EnvironmentLock) -> None:
    """SIGKILL delivery and the kernel's inherited flock release are asynchronous."""
    deadline = time.monotonic() + 2
    while True:
        try:
            lock.acquire()
            return
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@pytest.fixture(name="recorded_processes")
def fixture_recorded_processes(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    class RecordingProcess(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            children.append(self)

    monkeypatch.setattr(subprocess, "Popen", RecordingProcess)
    return children
