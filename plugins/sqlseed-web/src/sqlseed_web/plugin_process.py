"""Bounded installer subprocess execution; never expose raw output or secrets."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import IO, Any, Protocol

from sqlseed._utils.daemon_task import DaemonTask

from sqlseed_web.messages import message as tr


class InstallerLifetime(Protocol):
    arguments: list[str]
    startupinfo: Any

    def spawned(self) -> None: ...
    def stop(self, process: subprocess.Popen[bytes]) -> None: ...
    def close(self) -> None: ...


OUTPUT_LIMIT = 24_000


class InstallerCleanupPending(RuntimeError):
    """Keep process/job ownership until cleanup can be positively confirmed."""

    def __init__(self, stop: Callable[[], None], resources: ExitStack) -> None:
        super().__init__(tr("backend.plugin_process.installer_cleanup_has_not_been_confirmed_application"))
        self._stop = stop
        self._resources = resources
        self._stopped = False

    def hold(self, resources: ExitStack) -> None:
        self._resources.callback(resources.close)

    def retry(self) -> None:
        if not self._stopped:
            self._stop()
            self._stopped = True
        self._resources.close()


def _sanitized(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?i)\b(?:https?|ftp|file)://\S+", "[地址已隐藏]", text)
    text = re.sub(
        r"(?i)\b(?:authorization|password|passwd|token|api[_-]?key|secret)\b\s*[:=]\s*\S+", "[敏感信息已隐藏]", text
    )
    for name, value in os.environ.items():
        if len(value) >= 6 and re.search(r"(?i)(key|token|password|secret|credential)", name):
            text = text.replace(value, "[敏感信息已隐藏]")
    return "".join(character for character in text if character in "\n\t" or ord(character) >= 32)


def _installer_lines(stream: IO[bytes]) -> Iterator[tuple[bytes, int]]:
    """Drain complete lines, dropping an oversized line through its newline."""
    pending = b""
    dropping_line = False
    while chunk := os.read(stream.fileno(), 1024):
        if dropping_line:
            if b"\n" not in chunk:
                continue
            _, chunk = chunk.split(b"\n", 1)
            dropping_line = False
        pending += chunk
        while b"\n" in pending or len(pending) > 4096:
            if b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
            else:
                # Discard overlong lines as a whole: do not reveal split credentials/URLs.
                pending = b""
                dropping_line = True
                line = b"[overlong installer output omitted]"
            yield line, 2000
    if pending:
        # A final partial line retains the existing overall-budget truncation.
        yield pending, OUTPUT_LIMIT


def _read_installer_output(stream: IO[bytes], output: Callable[[str], None]) -> None:
    remaining = OUTPUT_LIMIT
    for line, line_limit in _installer_lines(stream):
        if remaining <= 0:
            continue
        if clean := _sanitized(line.decode("utf-8", errors="replace"))[: min(remaining, line_limit)]:
            output(clean)
            remaining -= len(clean)
        if remaining <= 0:
            output(tr("backend.plugin_process.the_output_length_limit_was_reached_further"))


def _wait_installer(
    process: subprocess.Popen[bytes],
    reader: DaemonTask[None],
    arguments: list[str],
    output: Callable[[str], None],
    timeout: float,
) -> int:
    """Bound process and output completion by the same deadline."""
    deadline = time.monotonic() + timeout
    try:
        result = process.wait(timeout=timeout)
        if not reader.wait(max(0, deadline - time.monotonic())):
            raise subprocess.TimeoutExpired(arguments, timeout)
    except subprocess.TimeoutExpired:
        output(tr("backend.plugin_process.the_installer_timed_out_and_is_being"))
        return -1
    if (error := reader.exception()) is not None:
        raise RuntimeError(tr("backend.plugin_process.cannot_read_installer_output")) from error
    return result


def run_installer(
    arguments: list[str], output: Callable[[str], None], *, timeout: float = 300, lock_descriptor: int | None = None
) -> int:
    """Stream bounded text, kill a timed-out process group, then reap the child."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("PIP_", "UV_", "PYTHON")) and name != "VIRTUAL_ENV"
    }
    environment.update({"PIP_CONFIG_FILE": os.devnull, "PYTHONNOUSERSITE": "1", "NO_COLOR": "1"})
    with ExitStack() as cleanup:
        directory = cleanup.enter_context(tempfile.TemporaryDirectory(prefix="sqlseed-plugin-process-"))
        windows: InstallerLifetime | None = None
        if sys.platform == "win32":
            from sqlseed_web._windows_process import WindowsInstaller

            windows = WindowsInstaller(arguments, lock_descriptor)
            cleanup.callback(windows.close)
        process = cleanup.enter_context(
            subprocess.Popen(
                windows.arguments if windows is not None else arguments,
                stdin=subprocess.PIPE if windows is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=directory,
                env=environment,
                start_new_session=os.name != "nt",
                startupinfo=windows.startupinfo if windows is not None else None,
                creationflags=0x08000000 if windows is not None else 0,  # CREATE_NO_WINDOW
                # Children retain the environment lock until they have exited.
                pass_fds=(lock_descriptor,) if os.name != "nt" and lock_descriptor is not None else (),
            )
        )
        if windows is not None:
            windows.spawned()
        reader: DaemonTask[None] | None = None
        try:
            if (stream := process.stdout) is None:
                raise RuntimeError(tr("backend.plugin_process.cannot_read_installer_output"))
            reader = DaemonTask(lambda: _read_installer_output(stream, output), name="sqlseed-plugin-output")
            return _wait_installer(process, reader, arguments, output, timeout)
        finally:
            # Startup and output failures own the same cleanup as timeouts.
            # Terminate before Popen.__exit__ waits, including inherited pipes.
            # The process group can outlive its leader while holding pipes
            # and the environment lock, including after a successful exit.
            def stop() -> None:
                _stop_installer(process, windows)
                if reader is not None:
                    reader.wait(2)

            try:
                stop()
            except (OSError, subprocess.SubprocessError) as error:
                # Closing the job only requests termination; it does not prove
                # the descendants have finished pending environment writes.
                raise InstallerCleanupPending(stop, cleanup.pop_all()) from error


def _stop_installer(process: subprocess.Popen[bytes], windows: InstallerLifetime | None = None) -> None:
    if windows is not None:
        windows.stop(process)
        return
    if sys.platform == "win32":
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()
