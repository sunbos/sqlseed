"""Bounded JSON RPC over inherited anonymous pipes, never an HTTP control port."""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
from collections.abc import Callable
from concurrent.futures import Future
from multiprocessing.connection import Connection
from typing import Any

from fastapi import HTTPException
from sqlseed._utils.daemon_task import DaemonTask

_CONTROL_CLOSED = "服务控制通道已关闭。"

MAX_MESSAGE_BYTES = 2_000_000
Handler = Callable[[str, dict[str, Any]], dict[str, Any]]


class ControlMessageTooLarge(RuntimeError):
    """A payload cannot fit in one bounded control message."""


def _encode_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ControlMessageTooLarge("会话信息超过安全传输上限，未执行环境变更。")
    return payload


def validate_control_result(result: dict[str, Any]) -> None:
    """Include the fixed request identifier and response envelope in the bound."""
    _encode_message({"id": "0" * 24, "result": result})


class ControlError(RuntimeError):
    """A public, credential-free control failure."""

    def __init__(self, detail: Any, status_code: int = 503) -> None:
        super().__init__(detail.get("message", "控制请求未完成") if isinstance(detail, dict) else str(detail))
        self.detail = detail
        self.status_code = status_code


class ControlChannel:
    """A duplex RPC endpoint whose reader never blocks on request execution."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._pending: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._answers: dict[str, Future[dict[str, Any]] | None] = {}

    def start(self, handler: Handler) -> None:
        self._handler = handler
        threading.Thread(target=self._read, name="sqlseed-control-reader", daemon=True).start()

    def _send(self, message: dict[str, Any]) -> None:
        payload = _encode_message(message)
        with self._send_lock:
            if self._closed.is_set():
                raise RuntimeError(_CONTROL_CLOSED)
            try:
                self.connection.send_bytes(payload)
            except OSError as exc:
                raise RuntimeError(_CONTROL_CLOSED) from exc

    def call(self, method: str, params: dict[str, Any], *, timeout: float = 15) -> dict[str, Any]:
        identifier = secrets.token_hex(12)
        event = threading.Event()
        result: dict[str, Any] = {}
        with self._lock:
            if len(self._pending) >= 32 or self._closed.is_set():
                raise RuntimeError("服务控制通道暂不可用。")
            self._pending[identifier] = event, result
        try:
            self._send({"id": identifier, "method": method, "params": params})
            if not event.wait(timeout):
                raise RuntimeError("控制请求未完成，请稍后检查服务状态。")
            if "error" in result:
                error = result["error"]
                raise ControlError(error["detail"], error["status_code"])
            value = result.get("result")
            if not isinstance(value, dict):
                # An invalid IPC reply follows the existing RuntimeError channel-failure contract.
                raise RuntimeError(_CONTROL_CLOSED)  # noqa: TRY004
            return value
        finally:
            with self._lock:
                self._pending.pop(identifier, None)

    def _dispatch_message(self, message: dict[str, Any]) -> None:
        if "method" in message:
            if not isinstance(message["method"], str) or not isinstance(message.get("params"), dict):
                raise ValueError("invalid control request")
            if not self._start_answer(message):
                self._send({"id": message["id"], "error": {"status_code": 503, "detail": "服务控制通道繁忙。"}})
        else:
            with self._lock:
                if pending := self._pending.get(message["id"]):
                    pending[1].update(message)
                    pending[0].set()

    def _read(self) -> None:
        try:
            while not self._closed.is_set():
                message = json.loads(self.connection.recv_bytes(MAX_MESSAGE_BYTES))
                if not isinstance(message, dict) or not isinstance(message.get("id"), str):
                    # Malformed wire values use ValueError, handled by the channel shutdown below.
                    raise ValueError("invalid control message")  # noqa: TRY004
                self._dispatch_message(message)
        except (OSError, EOFError, ValueError, TypeError, RuntimeError):
            self.close()

    def _start_answer(self, message: dict[str, Any]) -> bool:
        """Own each bounded reply from reservation through response publication."""
        identifier = message["id"]
        with self._lock:
            if len(self._answers) >= 8 or identifier in self._answers:
                return False
            self._answers[identifier] = None
            try:
                self._answers[identifier] = DaemonTask(
                    lambda: self._handler(message["method"], message["params"]),
                    name="sqlseed-control-answer",
                    on_done=lambda task: self._answer(identifier, task),
                )
            except BaseException:
                self._answers.pop(identifier, None)
                raise
        return True

    def _answer(self, identifier: str, task: Future[dict[str, Any]]) -> None:
        response: dict[str, Any] = {"id": identifier}
        if (error := task.exception()) is None:
            response["result"] = task.result()
        elif isinstance(error, (HTTPException, ControlError)):
            response["error"] = {"status_code": error.status_code, "detail": error.detail}
        else:
            response["error"] = {"status_code": 503, "detail": "控制请求未完成，请检查服务状态。"}
        try:
            self._send(response)
        except ControlMessageTooLarge:
            try:
                self._send(
                    {
                        "id": identifier,
                        "error": {
                            "status_code": 503,
                            "detail": {
                                "code": "control_response_too_large",
                                "message": "服务状态超过传输上限，请减少连接后重试。",
                            },
                        },
                    }
                )
            except (OSError, RuntimeError):
                pass
        except (OSError, RuntimeError):
            pass
        finally:
            with self._lock:
                self._answers.pop(identifier, None)

    def close(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()
            for event, _ in self._pending.values():
                event.set()
        with self._send_lock:
            if os.name != "nt":
                # Wake a reader blocked in recv_bytes and notify the peer even
                # when another thread currently holds a reference to this fd.
                endpoint = socket.socket(fileno=self.connection.fileno())
                try:
                    endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                finally:
                    endpoint.detach()
            self.connection.close()

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._closed.wait(timeout)
