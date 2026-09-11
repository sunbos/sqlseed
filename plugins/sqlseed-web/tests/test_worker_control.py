"""The supervisor channel is private, bounded, and supports nested requests."""

from __future__ import annotations

import importlib
import multiprocessing
from typing import Any

import pytest


def test_duplex_control_can_answer_a_request_while_waiting_for_peer() -> None:
    module = importlib.import_module("sqlseed_web.worker_control")
    first, second = multiprocessing.Pipe()
    left = module.ControlChannel(first)
    right = module.ControlChannel(second)

    def on_left(method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "outer"
        return left.call("inner", {"value": params["value"] + 1})

    left.start(on_left)
    right.start(lambda method, params: {"value": params["value"] * 2})
    try:
        assert right.call("outer", {"value": 4}) == {"value": 10}
    finally:
        left.close()
        right.close()


def test_private_control_errors_are_sanitized_and_closed_peer_fails_promptly() -> None:
    module = importlib.import_module("sqlseed_web.worker_control")
    first, second = multiprocessing.Pipe()
    left, right = module.ControlChannel(first), module.ControlChannel(second)

    def failure(method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("private-password")

    left.start(failure)
    right.start(failure)
    try:
        with pytest.raises(RuntimeError, match="控制请求未完成") as error:
            right.call("error", {})
        assert "private-password" not in str(error.value)
        left.close()
        assert right.wait_closed(1), "closing a parent endpoint must wake the worker's EOF watchdog"
        with pytest.raises(RuntimeError):
            right.call("closed", {}, timeout=0.1)
    finally:
        left.close()
        right.close()


def test_oversized_response_reports_bounded_error_without_timing_out_or_closing_channel() -> None:
    module = importlib.import_module("sqlseed_web.worker_control")
    first, second = multiprocessing.Pipe()
    left, right = module.ControlChannel(first), module.ControlChannel(second)
    left.start(
        lambda method, params: (
            {"secret": "private-password" * module.MAX_MESSAGE_BYTES} if method == "large" else {"ok": True}
        )
    )
    right.start(lambda method, params: {})
    try:
        with pytest.raises(module.ControlError) as error:
            right.call("large", {}, timeout=1)
        assert "private-password" not in str(error.value)
        assert right.call("small", {}) == {"ok": True}
    finally:
        left.close()
        right.close()
