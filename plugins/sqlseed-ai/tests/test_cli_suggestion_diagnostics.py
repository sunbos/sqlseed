"""Real completions preserve CLI failure reasons and the existing request budget."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

from tests._helpers import clear_llm_env
from tests.sqlite_helpers import sqlite_connection

try:
    from sqlseed_ai import AIBackend, AIConfig, SchemaAnalyzer
    from sqlseed_ai._json_utils import JSONResponseError
    from sqlseed_ai.cli.ai_commands import ai_suggest
except ModuleNotFoundError as exc:
    if exc.name != "sqlseed_ai":
        raise
    pytest.skip("sqlseed-ai is not installed", allow_module_level=True)

from click.testing import CliRunner

from .test_refiner_json_recovery import _completion_server

if TYPE_CHECKING:
    from pathlib import Path

_VALID_JSON = json.dumps(
    {
        "name": "events",
        "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
    }
)
_INVALID_JSON = 'PRIVATE_RESPONSE_MARKER {"name":"events","columns":INVALID}'


@pytest.fixture(autouse=True)
def isolated_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.delenv("SQLSEED_AI_TOOL_CALLING_PROTOCOL", raising=False)
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")


@pytest.fixture(name="files")
def fixture_files(tmp_path: Path) -> tuple[Path, Path, bytes]:
    database, output = tmp_path / "events.db", tmp_path / "suggested.yaml"
    with sqlite_connection(database) as db:
        db.execute("CREATE TABLE events(value INTEGER)")
        db.execute("INSERT INTO events VALUES (19)")
    output.write_text("user-owned output", encoding="utf-8")
    return database, output, database.read_bytes()


def _arguments(database: Path, output: Path, base_url: str, options: list[str]) -> list[str]:
    return [
        str(database),
        "--table",
        "events",
        "--output",
        str(output),
        "--base-url",
        base_url,
        "--model",
        "google/gemma-4-e2b",
        "--no-cache",
        *options,
    ]


@pytest.mark.parametrize("options", [["--no-verify"], ["--max-retries", "0"]])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "content,finish_reason,diagnostic",
    [
        (None, "stop", "no answer content"),
        (" ", "stop", "no answer content"),
        (_INVALID_JSON, "stop", "not valid JSON"),
        (_VALID_JSON, "length", "output limit before completion"),
        ("{}", "stop", "empty configuration object"),
    ],
)
def test_ultra_compact_failure_is_specific_and_does_not_retry_or_overwrite(
    files: tuple[Path, Path, bytes],
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
    finish_reason: str,
    diagnostic: str,
    options: list[str],
    streaming: bool,
) -> None:
    database, output, before = files
    monkeypatch.setattr(AIConfig, "should_use_streaming", lambda self: streaming)
    requests: list[dict[str, object]] = []
    # The first request is the CLI's existing ten-token speed probe.
    with _completion_server([("OK", "stop"), (content, finish_reason)], requests) as base_url:
        result = CliRunner().invoke(ai_suggest, _arguments(database, output, base_url, options))

    assert result.exit_code == 1, result.output
    assert diagnostic in result.output
    assert "retrying" not in result.output.lower()
    assert "PRIVATE_RESPONSE_MARKER" not in result.output
    assert "--timeout 180" not in result.output
    assert "deepseek" not in result.output.lower()
    assert "gpt-4o-mini" not in result.output
    assert len(requests) == 2
    assert requests[0]["max_tokens"] == 10
    assert requests[1]["max_tokens"] == 4096
    assert bool(requests[1].get("stream")) == streaming
    assert output.read_text(encoding="utf-8") == "user-owned output"
    assert database.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
def test_prompt_fallback_uses_only_three_levels_then_exports_the_success(
    files: tuple[Path, Path, bytes], monkeypatch: pytest.MonkeyPatch, streaming: bool
) -> None:
    database, output, before = files
    # Exercise the existing full -> compact -> ultra sequence with the real
    # transport/parser. E2B normally selects ultra directly; no LLM is mocked.
    monkeypatch.setattr(AIConfig, "should_use_ultra_compact", lambda self: False)
    monkeypatch.setattr(AIConfig, "should_use_streaming", lambda self: streaming)
    requests: list[dict[str, object]] = []
    with _completion_server(
        [("OK", "stop"), (_INVALID_JSON, "stop"), (None, "stop"), (_VALID_JSON, "stop")], requests
    ) as base_url:
        result = CliRunner().invoke(ai_suggest, _arguments(database, output, base_url, ["--no-verify"]))

    assert result.exit_code == 0, result.output
    assert result.output.lower().count("retrying with") == 2
    assert len(requests) == 4
    assert all(bool(request.get("stream")) == streaming for request in requests[1:])
    assert all(request["max_tokens"] == 4096 for request in requests[1:])
    exported = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert exported["tables"][0]["name"] == "events"
    assert exported["tables"][0]["columns"][0]["params"] == {"min_value": 7, "max_value": 7}
    assert database.read_bytes() == before


@pytest.mark.parametrize("streaming", [False, True])
def test_exhausted_full_prompt_budget_keeps_last_failure_and_existing_files(
    files: tuple[Path, Path, bytes], monkeypatch: pytest.MonkeyPatch, streaming: bool
) -> None:
    database, output, before = files
    monkeypatch.setattr(AIConfig, "should_use_ultra_compact", lambda self: False)
    monkeypatch.setattr(AIConfig, "should_use_streaming", lambda self: streaming)
    requests: list[dict[str, object]] = []
    with _completion_server(
        [("OK", "stop"), (None, "stop"), (_INVALID_JSON, "stop"), (_VALID_JSON, "length")], requests
    ) as base_url:
        result = CliRunner().invoke(ai_suggest, _arguments(database, output, base_url, ["--no-verify"]))

    assert result.exit_code == 1, result.output
    assert result.output.lower().count("retrying with") == 2
    assert "output limit before completion" in result.output
    assert "PRIVATE_RESPONSE_MARKER" not in result.output
    assert len(requests) == 4
    assert output.read_text(encoding="utf-8") == "user-owned output"
    assert database.read_bytes() == before


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("finish_reason", ["stop", "length"])
def test_streaming_strict_mode_checks_the_empty_terminal_chunk_without_changing_default(
    files: tuple[Path, Path, bytes], strict: bool, finish_reason: str
) -> None:
    database, output, before = files
    requests: list[dict[str, object]] = []
    with _completion_server([(_VALID_JSON, finish_reason)], requests, split_finish_chunk=True) as base_url:
        analyzer = SchemaAnalyzer(
            AIConfig(backend=AIBackend.LM_STUDIO, model="stream-diagnostic-test", base_url=base_url, timeout=5)
        )
        messages = [{"role": "user", "content": "Generate the events table configuration."}]
        if strict and finish_reason == "length":
            with pytest.raises(JSONResponseError) as error:
                analyzer.call_llm_streaming(messages, preserve_names=True, strict_json=True)
            assert error.value.code == "truncated_response"
        else:
            if strict:
                result = analyzer.call_llm_streaming(messages, preserve_names=True, strict_json=True)
            else:
                result = analyzer.call_llm_streaming(messages, preserve_names=True)
            assert result == json.loads(_VALID_JSON)
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert output.read_text(encoding="utf-8") == "user-owned output"
    assert database.read_bytes() == before


@pytest.mark.parametrize("split_finish_chunk", [False, True])
@pytest.mark.parametrize("content", [_VALID_JSON, _VALID_JSON[:-1]])
def test_verified_streaming_rejects_output_limit_without_overwriting_existing_files(
    files: tuple[Path, Path, bytes], monkeypatch: pytest.MonkeyPatch, content: str, split_finish_chunk: bool
) -> None:
    database, output, before = files
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "openai_compat")
    monkeypatch.setenv("SQLSEED_AI_API_KEY", "fixed-test-key")
    monkeypatch.setenv("SQLSEED_AI_TOOL_CALLING_PROTOCOL", "none")
    requests: list[dict[str, object]] = []
    with _completion_server([(content, "length")], requests, split_finish_chunk=split_finish_chunk) as base_url:
        result = CliRunner().invoke(
            ai_suggest, _arguments(database, output, base_url, ["--verify", "--max-retries", "1"])
        )

    assert result.exit_code == 1, result.output
    assert "output limit before completion" in result.output
    assert len(requests) == 2  # One initial attempt and the configured single retry.
    assert all(request["stream"] is True for request in requests)
    assert output.read_text(encoding="utf-8") == "user-owned output"
    assert database.read_bytes() == before
