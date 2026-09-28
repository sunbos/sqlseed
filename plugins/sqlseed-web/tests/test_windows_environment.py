"""Real Win32 file-object ownership, including a spawning parent's hard exit."""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from sqlseed_web.plugin_environment import EnvironmentLock, _WindowsEnvironmentHandle

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 handle sharing semantics")


@pytest.mark.parametrize(
    "first,second,allowed", [(False, False, True), (False, True, False), (True, False, False), (True, True, False)]
)
def test_shared_and_exclusive_environment_handles(tmp_path: Path, first: bool, second: bool, allowed: bool) -> None:
    owner = EnvironmentLock(tmp_path, exclusive=first)
    contender = EnvironmentLock(tmp_path, exclusive=second)
    owner.acquire()
    try:
        if allowed:
            contender.acquire()
            contender.release()
        else:
            with pytest.raises(RuntimeError):
                contender.acquire()
    finally:
        owner.release()
        contender.release()
    # The same file remains in place; closing the final owner releases its sharing restriction.
    contender.acquire()
    contender.release()


def test_worker_holds_environment_after_spawning_parent_exits(tmp_path: Path) -> None:
    ready, finish = tmp_path / "ready", tmp_path / "finish"
    script = tmp_path / "spawn_owner.py"
    script.write_text(
        "import multiprocessing,os,sys,time\n"
        "from pathlib import Path\n"
        "from sqlseed_web.plugin_environment import EnvironmentLock,InheritedEnvironmentLock\n"
        "def hold(lock, root):\n"
        "    descriptor=lock.detach(); root=Path(root)\n"
        "    try:\n"
        "        (root/'ready').write_text(str(os.getpid()))\n"
        "        deadline=time.monotonic()+15\n"
        "        while not (root/'finish').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "    finally: os.close(descriptor)\n"
        "if __name__=='__main__':\n"
        "    root=Path(sys.argv[1]); lock=EnvironmentLock(root,exclusive=True); lock.acquire()\n"
        "    child=multiprocessing.get_context('spawn').Process(target=hold,args=(InheritedEnvironmentLock(lock.fileno()),str(root)))\n"
        "    child.start()\n"
        "    while not (root/'ready').exists(): time.sleep(.01)\n"
        "    os._exit(0)\n",
        encoding="utf-8",
    )
    contender = EnvironmentLock(tmp_path, exclusive=True)
    process = subprocess.Popen(
        [sys.executable, "-I", str(script), str(tmp_path)], creationflags=subprocess.CREATE_NO_WINDOW
    )
    try:
        assert process.wait(timeout=10) == 0
        assert ready.exists()
        with pytest.raises(RuntimeError):
            contender.acquire()
    finally:
        finish.touch()
        if process.poll() is None:
            process.kill()
            process.wait()
        deadline = time.monotonic() + 5
        while True:
            try:
                contender.acquire()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        contender.release()


def test_file_wrapper_failure_releases_native_environment_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    original = os.fdopen

    def broken_wrapper(*args: object, **kwargs: object) -> None:
        raise OSError("cannot allocate file wrapper")

    owner = EnvironmentLock(tmp_path, exclusive=True)
    monkeypatch.setattr(os, "fdopen", broken_wrapper)
    with pytest.raises(RuntimeError):
        owner.acquire()
    monkeypatch.setattr(os, "fdopen", original)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    contender.acquire()
    contender.release()


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_inherited_handle_conversion_failure_closes_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    import _winapi
    import msvcrt

    owner = EnvironmentLock(tmp_path, exclusive=True)
    contender = EnvironmentLock(tmp_path, exclusive=True)
    owner.acquire()
    duplicate = None
    try:
        process = _winapi.GetCurrentProcess()
        duplicate = _winapi.DuplicateHandle(
            process, msvcrt.get_osfhandle(owner.fileno()), process, 0, False, _winapi.DUPLICATE_SAME_ACCESS
        )
        inherited = _WindowsEnvironmentHandle(duplicate)

        def fail_conversion(handle: int, flags: int) -> int:
            raise error("cannot allocate file descriptor")

        with monkeypatch.context() as patch:
            patch.setattr(msvcrt, "open_osfhandle", fail_conversion)
            with pytest.raises(error, match="cannot allocate file descriptor"):
                inherited.detach()
        with pytest.raises(RuntimeError, match="already detached"):
            inherited.detach()

        # Even after the original owner exits, a leaked duplicate would retain
        # the native share-deny lock and prevent the new owner from opening it.
        owner.release()
        contender.acquire()
        duplicate = None  # The closed handle value may already belong to the contender.
    finally:
        contender.release()
        owner.release()
        if duplicate is not None:
            with suppress(OSError):
                _winapi.CloseHandle(duplicate)
