"""Installer subprocesses retain the environment lock independently of the parent."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
from tests.assertions import assert_empty

from sqlseed_web.plugin_environment import EnvironmentLock
from sqlseed_web.plugin_process import run_installer


@pytest.mark.skipif(os.name == "nt", reason="Managed package operations require POSIX process groups")
def test_installer_keeps_environment_locked_after_parent_descriptor_closes(tmp_path: Path) -> None:
    lock = EnvironmentLock(tmp_path, exclusive=True)
    lock.acquire()
    ready = threading.Event()
    finish = tmp_path / "finish"
    results: list[int] = []
    failures: list[Exception] = []
    descriptor = lock.fileno()
    script = (
        "import pathlib,sys,time; print('ready',flush=True)\nwhile not "
        "pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)"
    )

    def run() -> None:
        try:
            results.append(
                run_installer(
                    [sys.executable, "-c", script, str(finish)],
                    lambda text: ready.set(),
                    timeout=10,
                    lock_descriptor=descriptor,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # Forward arbitrary thread failures to the test assertion instead of losing them.
            failures.append(exc)
            ready.set()

    thread = threading.Thread(target=run)
    thread.start()
    contender = EnvironmentLock(tmp_path, exclusive=True)
    try:
        assert ready.wait(5)
        assert_empty(failures, list)
        lock.release()
        with pytest.raises(RuntimeError):
            contender.acquire()
    finally:
        finish.touch()
        thread.join(15)
        lock.release()
        contender.release()
    assert not thread.is_alive()
    assert results == [0]
    contender.acquire()
    contender.release()
