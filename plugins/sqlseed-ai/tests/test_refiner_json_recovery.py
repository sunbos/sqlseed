"""Real HTTP responses exercise parsing, retry feedback and SQLite validation."""

from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from threading import Thread
from typing import TYPE_CHECKING

import pytest

from sqlseed.config.models import TableConfig
from sqlseed.core.orchestrator import DataOrchestrator
from tests.sqlite_helpers import sqlite_connection

try:
    from sqlseed_ai import AIBackend, AIConfig, AiConfigRefiner, SchemaAnalyzer
    from sqlseed_ai.refiner import AISuggestionFailedError
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai is not installed", allow_module_level=True)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_VALID_CONFIG = {
    "name": "events",
    "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
}
_VALID_JSON = json.dumps(_VALID_CONFIG)
_BROKEN_JSON = "PRIVATE_RESPONSE_MARKER " + _VALID_JSON.replace('"min_value"', 'min_value"')


@contextmanager
def _completion_server(
    replies: list[tuple[str | None, str]], requests: list[dict[str, object]], *, split_finish_chunk: bool = False
) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            content, finish_reason = replies[min(len(requests) - 1, len(replies) - 1)]
            payload = json.dumps(
                {
                    "id": "refiner-format-regression",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "refiner-format-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": finish_reason,
                        }
                    ],
                }
            ).encode()
            content_type = "application/json"
            if requests[-1].get("stream"):
                chunk = {
                    "id": "refiner-format-regression",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "refiner-format-test",
                    "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish_reason}],
                }
                if split_finish_chunk:
                    chunk["choices"] = [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
                    terminal = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
                    payload = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(terminal)}\n\ndata: [DONE]\n\n".encode()
                else:
                    payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
                content_type = "text/event-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object, **kwargs: object) -> None:
            """Do not print synthetic HTTP requests."""

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def _refiner(database: Path, base_url: str) -> AiConfigRefiner:
    config = AIConfig(backend=AIBackend.LM_STUDIO, model="refiner-format-test", base_url=base_url, timeout=5)
    return AiConfigRefiner(SchemaAnalyzer(config), str(database), cache_dir=str(database.parent / "cache"))


@pytest.fixture(name="events_database")
def fixture_events_database(tmp_path: Path) -> Path:
    database = tmp_path / "events.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER NOT NULL CHECK(value=7))")
    return database


def _recover_after_response(
    database: Path, content: str | None, finish_reason: str, *, streaming: bool = False
) -> tuple[TableConfig, list[dict[str, object]]]:
    """Exercise one failed response and one valid response through the real SDK."""
    requests: list[dict[str, object]] = []
    with _completion_server([(content, finish_reason), (_VALID_JSON, "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        generate = refiner.generate_and_refine_streaming if streaming else refiner.generate_and_refine
        result = generate("events", max_retries=1, no_cache=True)
    assert len(requests) == 2
    return TableConfig.model_validate(result), requests


def _assert_generated_rows(database: Path, table: TableConfig) -> None:
    """Prove validation rolled back and explicit generation honors the repaired rule."""
    with DataOrchestrator(str(database), provider_name="base", optimize_pragma=False) as orch:
        assert orch.get_row_count("events") == 0
        generated = orch.fill_table("events", count=3, column_configs=table.columns, skip_ai=True)
        assert generated.count == 3
        assert not generated.errors
        assert orch.query("SELECT value FROM events") == [{"value": 7}] * 3


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "content,finish_reason,feedback",
    [
        (_BROKEN_JSON, "stop", "not valid JSON"),
        (None, "stop", "no answer content"),
        (" ", "stop", "no answer content"),
        ("{}", "stop", "empty configuration object"),
        (_VALID_JSON, "length", "output limit before completion"),
    ],
)
def test_response_failure_gets_safe_feedback_then_valid_config_generates_rows(
    events_database: Path, content: str | None, finish_reason: str, feedback: str, streaming: bool
) -> None:
    table, requests = _recover_after_response(events_database, content, finish_reason, streaming=streaming)
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assert all(left["role"] != right["role"] for left, right in pairwise(messages))
    assert messages[-1]["role"] == "user"
    assert "# Table: events" in messages[-1]["content"]
    assert feedback in messages[-1]["content"]
    assert "double-quoted property names" in messages[-1]["content"]
    assert "PRIVATE_RESPONSE_MARKER" not in json.dumps(requests[1])
    assert table.columns[0].params == {"min_value": 7, "max_value": 7}
    _assert_generated_rows(events_database, table)


@pytest.mark.parametrize("max_retries,expected_requests", [(0, 1), (3, 2)])
def test_bad_json_keeps_existing_attempt_limits_and_never_writes(
    tmp_path: Path, max_retries: int, expected_requests: int
) -> None:
    database = tmp_path / "events.db"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER)")
    requests: list[dict[str, object]] = []
    with _completion_server([(_BROKEN_JSON, "stop")], requests) as base_url:
        refiner = _refiner(database, base_url)
        with pytest.raises(AISuggestionFailedError, match="not valid JSON") as captured:
            refiner.generate_and_refine("events", max_retries=max_retries, no_cache=True)
    assert len(requests) == expected_requests
    assert "PRIVATE_RESPONSE_MARKER" not in str(captured.value)
    with sqlite_connection(database) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (0,)


def test_unknown_generator_is_feedback_instead_of_an_uncaught_exception(events_database: Path) -> None:
    bad_config = _VALID_JSON.replace('"integer"', '"random_int"')
    table, requests = _recover_after_response(events_database, bad_config, "stop")
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assert "Generator 'random_int' does not exist" in messages[-1]["content"]
    assert "unknown_generator" in messages[-1]["content"]
    assert table.columns[0].generator == "integer"
    _assert_generated_rows(events_database, table)


def test_unknown_generator_exhausts_original_budget_without_writing(events_database: Path) -> None:
    requests: list[dict[str, object]] = []
    bad_config = _VALID_JSON.replace('"integer"', '"random_int"')
    with _completion_server([(bad_config, "stop")], requests) as base_url:
        refiner = _refiner(events_database, base_url)
        with pytest.raises(AISuggestionFailedError, match=r"Failed after 1 retries.*random_int.*does not exist"):
            refiner.generate_and_refine("events", max_retries=1, no_cache=True)
    assert len(requests) == 2
    messages = requests[1]["messages"]
    assert isinstance(messages, list)
    assert "unknown_generator" in messages[-1]["content"]
    with sqlite_connection(events_database) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (0,)
