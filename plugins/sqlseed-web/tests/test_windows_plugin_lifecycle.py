"""Real Windows installer trees; all writers and locks use temporary paths."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from sqlseed_web.plugin_environment import EnvironmentLock
from sqlseed_web.plugin_process import run_installer

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 Job Object process-tree ownership")


def _writer_tree(root: Path, *, parent_waits: bool) -> Path:
    writer = root / "writer.py"
    writer.write_text(
        "import os,sys,time\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1]); deadline=time.monotonic()+15\n"
        "while time.monotonic()<deadline and not (root/'stop').exists():\n"
        "    with (root/'writes').open('ab') as stream: stream.write(b'x'); stream.flush()\n"
        "    print('writer alive',flush=True)\n"
        "    time.sleep(.01)\n",
        encoding="utf-8",
    )
    intermediate = root / "intermediate.py"
    intermediate.write_text(
        "import subprocess,sys\nsubprocess.Popen([sys.executable,'-I',sys.argv[1],sys.argv[2]])\n",
        encoding="utf-8",
    )
    installer = root / "installer.py"
    installer.write_text(
        "import subprocess,sys,time\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1])\n"
        "subprocess.run([sys.executable,'-I',str(root/'intermediate.py'),str(root/'writer.py'),str(root)],check=True)\n"
        "deadline=time.monotonic()+5\n"
        "while not (root/'writes').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        + ("time.sleep(15)\n" if parent_waits else ""),
        encoding="utf-8",
    )
    return installer


def _wait_for_owner_progress(
    path: Path,
    process: subprocess.Popen[bytes],
    diagnostics: Path,
    *,
    timeout: float,
    minimum_size: int,
    phase: str,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        returncode = process.poll()
        if returncode is not None or time.monotonic() >= deadline:
            output = diagnostics.read_text(encoding="utf-8", errors="replace")
            pytest.fail(f"{phase}; owner exit code: {returncode}\n{output}")
        if path.exists() and path.stat().st_size >= minimum_size:
            return
        time.sleep(0.01)


def _acquire_after_cleanup(lock: EnvironmentLock) -> None:
    deadline = time.monotonic() + 8
    while True:
        try:
            lock.acquire()
            return
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _assert_writer_stopped(path: Path) -> None:
    before = path.read_bytes()
    assert before, "The test must have exercised an actual descendant writer"
    time.sleep(0.2)
    assert path.read_bytes() == before, "No old writer may modify the environment after cleanup"


@pytest.mark.parametrize("parent_waits", [False, True])
def test_installer_exit_and_timeout_reap_grandchildren_holding_stdout(tmp_path: Path, parent_waits: bool) -> None:
    installer = _writer_tree(tmp_path, parent_waits=parent_waits)
    owner = EnvironmentLock(tmp_path, exclusive=True)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    owner.acquire()
    output: list[str] = []
    try:
        started = time.monotonic()
        result = run_installer(
            [sys.executable, "-I", str(installer), str(tmp_path)],
            output.append,
            timeout=3,
            lock_descriptor=owner.fileno(),
        )
        assert result == (-1 if parent_waits else 0), output
        assert time.monotonic() - started < 10, "Inherited stdout must not hang process cleanup"
        owner.release()
        _acquire_after_cleanup(contender)
        _assert_writer_stopped(tmp_path / "writes")
    finally:
        (tmp_path / "stop").touch()
        owner.release()
        contender.release()


def test_hard_exit_of_installer_owner_keeps_lock_until_descendant_writes_stop(tmp_path: Path) -> None:
    installer = _writer_tree(tmp_path, parent_waits=True)
    owner_script = tmp_path / "owner.py"
    owner_script.write_text(
        "import os,sys,threading,time\n"
        "from pathlib import Path\n"
        "from sqlseed_web.plugin_environment import EnvironmentLock\n"
        "from sqlseed_web.plugin_process import run_installer\n"
        "root=Path(sys.argv[1]); lock=EnvironmentLock(root,exclusive=True); lock.acquire()\n"
        "def crash():\n"
        "    deadline=time.monotonic()+12\n"
        "    while not (root/'die').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "    os._exit(0)\n"
        "threading.Thread(target=crash,daemon=True).start()\n"
        "(root/'owner-ready').touch()\n"
        "run_installer([sys.executable,'-I',str(root/'installer.py'),str(root)],"
        "lambda line: print(line,file=sys.stderr,flush=True),"
        "timeout=15,lock_descriptor=lock.fileno())\n",
        encoding="utf-8",
    )
    assert installer.exists()
    contender = EnvironmentLock(tmp_path, exclusive=True)
    diagnostics = tmp_path / "owner-output.log"
    with (
        diagnostics.open("wb") as output,
        subprocess.Popen(
            [sys.executable, "-I", str(owner_script), str(tmp_path)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as process,
    ):
        try:
            # Cold imports must not consume the descendant's original startup budget.
            _wait_for_owner_progress(
                tmp_path / "owner-ready",
                process,
                diagnostics,
                timeout=30,
                minimum_size=0,
                phase="The isolated owner did not acquire its environment lock",
            )
            _wait_for_owner_progress(
                tmp_path / "writes",
                process,
                diagnostics,
                timeout=8,
                minimum_size=2,
                phase="The isolated descendant did not begin writing",
            )
            with pytest.raises(RuntimeError):
                contender.acquire()
            (tmp_path / "die").touch()
            assert process.wait(timeout=8) == 0, diagnostics.read_text(encoding="utf-8", errors="replace")
            _acquire_after_cleanup(contender)
            _assert_writer_stopped(tmp_path / "writes")
        finally:
            (tmp_path / "stop").touch()
            (tmp_path / "die").touch()
            contender.release()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_job_assignment_failure_never_executes_the_actual_installer(tmp_path: Path) -> None:
    launcher = tmp_path / "assignment_failure.py"
    marker = tmp_path / "must-not-exist"
    launcher.write_text(
        "import sys\n"
        "from sqlseed_web._windows_process import WindowsJob,_child\n"
        "def deny(self): raise OSError('Job assignment denied')\n"
        "WindowsJob.assign_current=deny\n"
        "job=WindowsJob()\n"
        "try:\n"
        "    _child(job,0,[sys.executable,'-I','-c',"
        "\"import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('executed')\",sys.argv[1]])\n"
        "except OSError:\n"
        "    sys.exit(23)\n"
        "finally:\n"
        "    job.close()\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-I", str(launcher), str(marker)],
        capture_output=True,
        timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    assert not marker.exists()
