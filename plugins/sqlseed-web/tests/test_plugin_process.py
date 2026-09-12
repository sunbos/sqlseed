"""Installer subprocesses retain the environment lock independently of the parent."""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
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
