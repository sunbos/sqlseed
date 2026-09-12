"""RPC failure classification and accounting without a network backend."""

from __future__ import annotations

import importlib
from importlib.util import find_spec
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

pytest.importorskip("sqlseed_ai")


class _FalseValueError(ValueError):
    def __bool__(self) -> bool:
        return False


class _NetworkValueError(OSError, ValueError):
    """A recoverable base must not override the network-error policy."""


class _PretendsNetworkError(ValueError):
    @property
    def __class__(self) -> type[OSError]:
        return OSError


class _Client:
    """An RPC endpoint with observable values, failures and resource ownership."""

    def __init__(
        self,
        events: list[str],
        *,
        response: object = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.response = response
        self.error = error
        self.requests: list[dict[str, object]] = []

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> object:
        self.events.append("rpc")
        self.requests.append(
            {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.events.append("close")


def _boundary() -> ModuleType:
    """Report a missing implementation as a test failure, never a collection error."""
    module_name = "sqlseed_ai.healer._llm_call"
    if find_spec(module_name) is None:
        pytest.fail("Shared LLM call boundary has not been implemented", pytrace=False)
    return importlib.import_module(module_name)


def _request(boundary: ModuleType, client: _Client, on_failure: Callable[[Exception], None]):
    return boundary.call_llm(
        lambda: client.chat_completions_create(
            model="chosen-model",
            messages=[
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "user text"},
            ],
            temperature=0.375,
            max_tokens=137,
        ),
        started_at=10.0,
        on_failure=on_failure,
    )


def _record_clock(monkeypatch: pytest.MonkeyPatch, boundary: ModuleType, events: list[str]) -> None:
    readings = iter([12.5])

    def monotonic() -> float:
        events.append("clock")
        return next(readings)

    monkeypatch.setattr(boundary.time, "monotonic", monotonic)


@pytest.mark.parametrize("response", [object(), None, False, 0, ""])
def test_success_returns_original_response_and_accounts_one_rpc(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> None:
    boundary = _boundary()
    events: list[str] = []
    client = _Client(events, response=response)
    _record_clock(monkeypatch, boundary, events)

    result = _request(boundary, client, lambda _error: events.append("log"))

    assert result.response is response
    assert result.error is None
    assert result.elapsed_seconds == 2.5
    assert events == ["rpc", "clock"]
    assert client.requests == [
        {
            "model": "chosen-model",
            "messages": [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "user text"},
            ],
            "temperature": 0.375,
            "max_tokens": 137,
        }
    ]


@pytest.mark.parametrize(
    "error_type", [RuntimeError, AttributeError, ValueError, _FalseValueError, _PretendsNetworkError]
)
def test_recoverable_error_keeps_identity_and_logs_before_accounting(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    boundary = _boundary()
    events: list[str] = []
    error = error_type("original RPC failure")
    client = _Client(events, error=error)
    reported: list[Exception] = []
    _record_clock(monkeypatch, boundary, events)

    def report_failure(failure: Exception) -> None:
        events.append("log")
        reported.append(failure)

    result = _request(boundary, client, report_failure)

    assert result.response is None
    assert result.error is error
    assert result.elapsed_seconds == 2.5
    assert len(reported) == 1
    assert reported[0] is error
    assert events == ["rpc", "log", "clock"]
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    "error_type",
    [
        pytest.param(OSError, id="network"),
        pytest.param(ConnectionError, id="connection"),
        pytest.param(_NetworkValueError, id="network-and-recoverable-bases"),
        pytest.param(KeyError, id="unknown-key"),
        pytest.param(TypeError, id="unknown-type"),
        pytest.param(BaseException, id="base-exception"),
        pytest.param(KeyboardInterrupt, id="interrupt"),
        pytest.param(SystemExit, id="system-exit"),
    ],
)
def test_unhandled_failures_propagate_without_logging_or_end_clock(
    monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException]
) -> None:
    boundary = _boundary()
    events: list[str] = []
    error = error_type("outside the recoverable contract")
    client = _Client(events, error=error)
    _record_clock(monkeypatch, boundary, events)

    with pytest.raises(error_type) as caught:
        _request(boundary, client, lambda _error: events.append("log"))

    assert caught.value is error
    assert events == ["rpc"]
    assert len(client.requests) == 1
    frames: list[str] = []
    traceback = caught.value.__traceback__
    while traceback is not None:
        frames.append(traceback.tb_frame.f_code.co_name)
        traceback = traceback.tb_next
    assert frames.count("call_llm") == 1
    assert frames[-1] == "chat_completions_create"


def test_failure_callback_exception_propagates_before_end_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _boundary()
    events: list[str] = []
    rpc_error = ValueError("RPC failed")
    logging_error = RuntimeError("logger failed")
    client = _Client(events, error=rpc_error)
    _record_clock(monkeypatch, boundary, events)

    def broken_logger(error: Exception) -> None:
        assert error is rpc_error
        events.append("log")
        raise logging_error

    with pytest.raises(RuntimeError) as caught:
        _request(boundary, client, broken_logger)

    assert caught.value is logging_error
    assert caught.value.__context__ is rpc_error
    assert events == ["rpc", "log"]


def test_response_access_stays_outside_the_rpc_failure_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _boundary()
    events: list[str] = []
    access_error = AttributeError("malformed response")

    class UnreadableResponse:
        @property
        def choices(self) -> object:
            events.append("content")
            raise access_error

    response = UnreadableResponse()
    client = _Client(events, response=response)
    _record_clock(monkeypatch, boundary, events)

    result = _request(boundary, client, lambda _error: events.append("log"))

    assert events == ["rpc", "clock"]
    with pytest.raises(AttributeError) as caught:
        _ = result.response.choices
    assert caught.value is access_error
    assert events == ["rpc", "clock", "content"]


@pytest.mark.parametrize("rpc_error", [None, ValueError("RPC failed")], ids=["success", "after-failure-log"])
def test_end_clock_failure_preserves_context_and_call_order(
    monkeypatch: pytest.MonkeyPatch, rpc_error: Exception | None
) -> None:
    boundary = _boundary()
    events: list[str] = []
    clock_error = RuntimeError("clock failed")
    client = _Client(events, response=object(), error=rpc_error)

    def broken_clock() -> float:
        events.append("clock")
        raise clock_error

    monkeypatch.setattr(boundary.time, "monotonic", broken_clock)

    with pytest.raises(RuntimeError) as caught:
        _request(boundary, client, lambda _error: events.append("log"))

    assert caught.value is clock_error
    assert caught.value.__context__ is rpc_error
    assert events == (["rpc", "clock"] if rpc_error is None else ["rpc", "log", "clock"])
    assert len(client.requests) == 1


def _healer_call(level: int, client: _Client, tmp_path: Path):
    from sqlseed_ai.healer.models import SubgraphTask

    from tests.sqlite_helpers import sqlite_connection

    from .scenario_helpers import product_price_config, product_price_violation

    task = SubgraphTask(task_id="accounting", tables=["products"])
    config = product_price_config()
    violation = product_price_violation()
    modules = ("level1_subgraph_healer", "level2_column_healer", "level3_compact_healer")
    classes = ("Level1SubgraphHealer", "Level2ColumnHealer", "Level3CompactHealer")
    module = importlib.import_module(f"sqlseed_ai.healer.{modules[level - 1]}")
    healer = getattr(module, classes[level - 1])(client=client, model="chosen-model")
    if level == 1:
        return module, healer, lambda: healer.heal(task, [violation], config)
    if level == 3:
        return module, healer, lambda: healer.heal_compact(task, [violation], config, "compact")

    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    path = tmp_path / "healer.db"
    with sqlite_connection(path) as connection:
        connection.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, price REAL CHECK(price > 0))")
    snapshot = SchemaSnapshot(db_path=str(path))
    return module, healer, lambda: healer.heal_column("products", "price", violation, config, snapshot)


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize("failure_site", ["rpc", "request_argument"])
def test_healer_callers_keep_falsy_errors_and_account_after_logging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, level: int, failure_site: str
) -> None:
    from types import SimpleNamespace

    events: list[str] = []
    error = _FalseValueError("original failure")
    client = _Client(events, error=error if failure_site == "rpc" else None)
    module, healer, invoke = _healer_call(level, client, tmp_path)
    readings = iter([10.0, 12.5])

    def monotonic() -> float:
        events.append("clock")
        return next(readings)

    def log_failure(event: str, **details: object) -> None:
        assert event == f"Level {level} LLM call failed"
        assert details["error"] == "original failure"
        events.append("log")

    if failure_site == "request_argument":

        def unavailable_model(_healer: object) -> str:
            events.append("argument")
            raise error

        monkeypatch.setattr(type(healer), "_model", property(unavailable_model), raising=False)

    monkeypatch.setattr(module.time, "monotonic", monotonic)
    monkeypatch.setattr(module, "logger", SimpleNamespace(warning=log_failure))

    result = invoke()

    assert result.success is False
    assert result.error is error
    assert result.config_patch is None
    assert result.elapsed_seconds == 2.5
    assert result.prompt_tokens > 0
    if level == 2:
        assert result.column == "price"
    elif level == 3:
        assert result.mode == "compact"
    if failure_site == "rpc":
        assert events == ["clock", "rpc", "log", "clock"]
        messages = client.requests[0]["messages"]
        assert result.prompt_tokens == sum(len(message["content"]) // 4 for message in messages)
    else:
        assert events == ["clock", "argument", "log", "clock"]
        assert not client.requests
