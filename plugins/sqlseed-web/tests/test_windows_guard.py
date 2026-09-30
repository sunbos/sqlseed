"""Exercise guard context ownership with real Win32 jobs and isolated children."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest

from sqlseed_web import _windows_process as windows
from sqlseed_web.plugin_environment import EnvironmentLock

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Real Win32 guard and inherited Job handles")


@pytest.fixture(name="guard_job")
def fixture_guard_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[windows.WindowsJob]:
    with (tmp_path / "child-output.log").open("wb") as output:
        # Change this module's stream only, leaving pytest's global capture intact.
        monkeypatch.setattr(
            windows, "sys", SimpleNamespace(platform=sys.platform, stdout=SimpleNamespace(buffer=output))
        )
        job = windows.WindowsJob()
        try:
            os.set_handle_inheritable(job.handle, True)
            yield job
        finally:
            job.close()


def _child_command(job: windows.WindowsJob, root: Path) -> list[str]:
    worker = root / "worker.py"
    worker.write_text(
        "import sys,time\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1])\n"
        "print('worker started',flush=True)\n"
        "(root/'started').touch()\n"
        "deadline=time.monotonic()+20\n"
        "while not (root/'release').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "(root/'finished').write_text('normal exit')\n",
        encoding="utf-8",
    )
    # The private child loads only its stdlib script, assigns itself to the Job,
    # and then starts the actual worker, which inherits that Job membership.
    return [
        sys.executable,
        "-I",
        str(Path(windows.__file__).resolve()),
        "child",
        str(job.handle),
        "0",
        sys.executable,
        "-I",
        str(worker),
        str(root),
    ]


def _wait_for_started(process: subprocess.Popen[bytes], root: Path) -> None:
    deadline = time.monotonic() + 8
    while not (root / "started").exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            pytest.fail(f"Child did not start: {(root / 'child-output.log').read_text(encoding='utf-8')}")
        time.sleep(0.01)


def test_guard_normal_exit_drains_members_without_closing_parent_job(
    tmp_path: Path, guard_job: windows.WindowsJob
) -> None:
    parent_handle = guard_job.handle
    with windows._guard_child(guard_job, [parent_handle], _child_command(guard_job, tmp_path)) as process:
        _wait_for_started(process, tmp_path)
        with pytest.raises(TimeoutError, match="has not finished draining"):
            guard_job.wait_empty(timeout=0)
        (tmp_path / "release").touch()
        assert process.wait(timeout=8) == 0
    assert (tmp_path / "finished").read_text(encoding="utf-8") == "normal exit"
    assert (tmp_path / "child-output.log").read_text(encoding="utf-8").splitlines() == ["worker started"]
    assert guard_job.handle == parent_handle
    guard_job.wait_empty(timeout=1)


def test_guard_start_failure_preserves_error_parent_job_and_external_environment_lock(
    tmp_path: Path, guard_job: windows.WindowsJob
) -> None:
    owner = EnvironmentLock(tmp_path, exclusive=True)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    parent_handle = guard_job.handle
    with ExitStack() as cleanup:
        cleanup.callback(owner.release)
        cleanup.callback(contender.release)
        owner.acquire()
        missing = tmp_path / "nonexistent-installer.exe"
        with pytest.raises(FileNotFoundError) as raised, windows._guard_child(guard_job, [], [str(missing)]):
            pytest.fail("The missing executable must not enter the protected body")
        assert raised.value.winerror == 2
        assert raised.value.__cause__ is None
        assert guard_job.handle == parent_handle
        guard_job.wait_empty(timeout=1)
        with pytest.raises(RuntimeError):
            contender.acquire()
        owner.release()
        contender.acquire()


def test_guard_body_failure_reaps_running_children_before_propagating(
    tmp_path: Path, guard_job: windows.WindowsJob
) -> None:
    failure = ValueError("caller failed while the child was running")
    parent_handle = guard_job.handle
    with (
        pytest.raises(ValueError) as raised,
        windows._guard_child(guard_job, [parent_handle], _child_command(guard_job, tmp_path)) as process,
    ):
        _wait_for_started(process, tmp_path)
        with pytest.raises(TimeoutError, match="has not finished draining"):
            guard_job.wait_empty(timeout=0)
        raise failure
    assert raised.value is failure
    assert process.poll() is not None
    assert not (tmp_path / "finished").exists(), "The worker must be terminated before its natural completion"
    assert guard_job.handle == parent_handle
    guard_job.wait_empty(timeout=1)
