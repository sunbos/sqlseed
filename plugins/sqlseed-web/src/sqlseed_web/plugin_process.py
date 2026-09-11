"""Bounded installer subprocess execution; never expose raw output or secrets."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable

OUTPUT_LIMIT = 24_000


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
    with tempfile.TemporaryDirectory(prefix="sqlseed-plugin-process-") as directory:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=directory,
            env=environment,
            start_new_session=os.name != "nt",
            # Keep the same flock alive if the supervisor dies while this
            # process is still changing packages. It closes on process exit.
            pass_fds=(lock_descriptor,) if os.name != "nt" and lock_descriptor is not None else (),
        )
        stream = process.stdout
        if stream is None:
            process.kill()
            process.wait()
            raise RuntimeError("无法读取安装工具输出。")

        def read() -> None:
            remaining = OUTPUT_LIMIT
            pending = b""
            dropping_line = False
            while chunk := os.read(stream.fileno(), 1024):
                if remaining <= 0:
                    continue
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
                    clean = _sanitized(line.decode("utf-8", errors="replace"))[: min(remaining, 2000)]
                    if clean:
                        output(clean)
                        remaining -= len(clean)
                if remaining <= 0:
                    output("输出已达到长度上限，后续输出已省略。")
            if remaining > 0 and pending:
                output(_sanitized(pending.decode("utf-8", errors="replace"))[:remaining])

        reader = threading.Thread(target=read, daemon=True, name="sqlseed-plugin-output")
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            result = process.wait(timeout=timeout)
            reader.join(timeout=max(0, deadline - time.monotonic()))
            if reader.is_alive():
                raise subprocess.TimeoutExpired(arguments, timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            result = -1
            output("安装工具运行超时，子进程已停止；请检查环境并重启 Web。")
        finally:
            reader.join(timeout=2)
            if not reader.is_alive():
                stream.close()
        return result
