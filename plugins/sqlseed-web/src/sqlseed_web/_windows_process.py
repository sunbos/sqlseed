"""Win32 ownership primitives and the private installer guard (stdlib only).

The guard stays outside its job and keeps the environment handle until every
installer descendant exits. Parent EOF stops the job without abandoning that
lock; the parent also owns the job, covering unexpected guard failure.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

if sys.platform == "win32":

    def _kernel32() -> Any:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": (
                [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.HANDLE,
                ],
                wintypes.HANDLE,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateJobObjectW": ([wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID],
                wintypes.BOOL,
            ),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "GetCurrentProcess": ([], wintypes.HANDLE),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = arguments, result
        return kernel

    class _Limits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", _Limits),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    class _Accounting(ctypes.Structure):
        _fields_ = [
            ("user_time", ctypes.c_int64),
            ("kernel_time", ctypes.c_int64),
            ("period_user_time", ctypes.c_int64),
            ("period_kernel_time", ctypes.c_int64),
            ("page_faults", wintypes.DWORD),
            ("total", wintypes.DWORD),
            ("active", wintypes.DWORD),
            ("terminated", wintypes.DWORD),
        ]

    def open_environment_lock(path: Path, *, exclusive: bool) -> int:
        """Share-deny follows the file object across DuplicateHandle and parent exit."""
        import msvcrt

        kernel = _kernel32()
        access = 0x80000000 | (0x40000000 if exclusive else 0)  # GENERIC_READ / WRITE
        handle = kernel.CreateFileW(str(path), access, 0 if exclusive else 1, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(int(handle), os.O_BINARY | (os.O_RDWR if exclusive else os.O_RDONLY))
        except BaseException:
            kernel.CloseHandle(handle)
            raise

    class WindowsJob:
        def __init__(self, handle: int | None = None) -> None:
            self.kernel = _kernel32()
            self.handle = int(handle or self.kernel.CreateJobObjectW(None, None) or 0)
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if handle is None:
                limits = _ExtendedLimits()
                limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway
                if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                    error = ctypes.WinError(ctypes.get_last_error())
                    self.close()
                    raise error

        def assign_current(self) -> None:
            if not self.kernel.AssignProcessToJobObject(self.handle, self.kernel.GetCurrentProcess()):
                raise ctypes.WinError(ctypes.get_last_error())

        def terminate(self) -> None:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())

        def wait_empty(self, *, timeout: float | None = None) -> None:
            # TerminateJobObject is asynchronous. Do not allow service restoration
            # (or release the environment lock) while an installer still owns I/O.
            deadline = time.monotonic() + timeout if timeout is not None else None
            while True:
                accounting = _Accounting()
                if not self.kernel.QueryInformationJobObject(
                    self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not accounting.active:
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Installer job has not finished draining")
                time.sleep(0.01)

        def close(self) -> None:
            if self.handle:
                self.kernel.CloseHandle(self.handle)
                self.handle = 0

    def _duplicate(handle: int) -> int:
        from multiprocessing.reduction import duplicate

        copied = int(duplicate(handle, inheritable=True))
        return copied

    def _startup(handles: list[int]) -> subprocess.STARTUPINFO:
        info = subprocess.STARTUPINFO(lpAttributeList={"handle_list": handles})
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        return info

    class WindowsInstaller:
        """Parent-side handles are owned even if Popen or the output reader fails."""

        def __init__(self, arguments: list[str], lock_descriptor: int | None) -> None:
            import msvcrt

            self.job = WindowsJob()
            self.handles: list[int] = []
            try:
                job = _duplicate(self.job.handle)
                self.handles.append(job)
                lock = _duplicate(msvcrt.get_osfhandle(lock_descriptor)) if lock_descriptor is not None else 0
                if lock:
                    self.handles.append(lock)
                self.arguments = [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "guard",
                    str(job),
                    str(lock),
                    *arguments,
                ]
                self.startupinfo = _startup(self.handles)
            except BaseException:
                self.close()
                raise

        def spawned(self) -> None:
            for handle in self.handles:
                self.job.kernel.CloseHandle(handle)
            self.handles.clear()

        def stop(self, process: subprocess.Popen[bytes]) -> None:
            if process.stdin is not None:
                process.stdin.close()
            self.job.terminate()
            process.wait(timeout=10)
            self.job.wait_empty(timeout=10)

        def close(self) -> None:
            self.spawned()
            self.job.close()

    def _guard(job: WindowsJob, lock: int, arguments: list[str]) -> int:
        stopped = threading.Event()

        def watch_parent() -> None:
            try:
                os.read(sys.stdin.fileno(), 1)
            except OSError:
                pass
            finally:
                stopped.set()

        threading.Thread(target=watch_parent, daemon=True, name="sqlseed-installer-parent").start()
        handles = [job.handle, *([lock] if lock else [])]
        for handle in handles:
            os.set_handle_inheritable(handle, True)
        command = [sys.executable, "-I", str(Path(__file__).resolve()), "child", str(job.handle), str(lock), *arguments]
        process = None
        try:
            if stopped.is_set():
                return -1
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=sys.stdout.buffer,
                stderr=subprocess.STDOUT,
                close_fds=True,
                startupinfo=_startup(handles),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            while process.poll() is None:
                if stopped.wait(0.02):
                    job.terminate()
            return process.returncode
        finally:
            while True:
                try:
                    job.terminate()
                    if process is not None:
                        process.wait()
                    job.wait_empty()
                    break
                except OSError:
                    # A failed query/termination is not proof of an empty job.
                    # Keep the independent lock owner alive through parent loss.
                    time.sleep(0.1)

    def _child(job: WindowsJob, lock: int, arguments: list[str]) -> int:
        # No installer code runs before job assignment. The guard remains outside
        # the job to keep the environment locked through asynchronous termination.
        job.assign_current()
        job.close()
        handles = [lock] if lock else []
        if lock:
            os.set_handle_inheritable(lock, True)
        with subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=sys.stdout.buffer,
            stderr=subprocess.STDOUT,
            close_fds=True,
            startupinfo=_startup(handles),
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as process:
            return process.wait()

    def _main() -> int:
        mode, handle, lock_text, *arguments = sys.argv[1:]
        job, lock = WindowsJob(int(handle)), int(lock_text)
        try:
            return _guard(job, lock, arguments) if mode == "guard" else _child(job, lock, arguments)
        finally:
            job.close()
            if lock:
                _kernel32().CloseHandle(lock)

    if __name__ == "__main__":
        sys.exit(_main())
