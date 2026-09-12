"""Shared runtime factories keep AI construction independent of CLI handling."""

from __future__ import annotations

import builtins
import importlib
import json
from typing import TYPE_CHECKING

import httpx
import pytest

from tests._helpers import clear_llm_env
from tests.llm_helpers import no_network_openai_client
from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("sqlseed_ai")

ai_config = importlib.import_module("sqlseed_ai.config")
AIBackend, AIConfig = ai_config.AIBackend, ai_config.AIConfig


@pytest.fixture(autouse=True)
def isolated_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_env(monkeypatch)
    monkeypatch.delenv("SQLSEED_AI_TOOL_CALLING_PROTOCOL", raising=False)


def test_runtime_config_preserves_env_backend_and_explicit_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
    monkeypatch.setenv("SQLSEED_AI_MODEL", "env-model")
    monkeypatch.setenv("SQLSEED_AI_TIMEOUT", "180")
    monkeypatch.setenv("SQLSEED_AI_TOOL_CALLING_PROTOCOL", "none")

    config = runtime.build_ai_config(model="requested-model", timeout=75, log_llm=True)

    assert config.backend is AIBackend.OLLAMA
    assert config.resolve_base_url() == "http://localhost:11434/v1"
    assert config.resolve_api_key() == "ollama"
    assert config.resolve_model() == "requested-model"
    assert config.timeout == 75
    assert config.log_llm_interactions is True
    assert config.tool_calling_protocol == "none"
    defaults = runtime.build_ai_config()
    assert defaults.model == "env-model"
    assert defaults.timeout == 0.0  # Existing command default overrides the env timeout.
    assert defaults.log_llm_interactions is False


@pytest.mark.parametrize(
    ("backend", "base_url", "key"),
    [
        (AIBackend.GOOGLE_AI_STUDIO, "https://generativelanguage.googleapis.com/v1beta/openai/", "test-key"),
        (AIBackend.LM_STUDIO, "http://127.0.0.1:1234/v1/", "lm-studio"),
        (AIBackend.OLLAMA, "http://localhost:11434/v1/", "ollama"),
        (AIBackend.OPENAI_COMPAT, "https://example.invalid/v1/", "test-key"),
    ],
)
def test_runtime_client_uses_selected_backend_and_parses_completion(
    monkeypatch: pytest.MonkeyPatch, backend: AIBackend, base_url: str, key: str
) -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    import openai

    sdk_client = openai.OpenAI
    config = AIConfig(
        backend=backend,
        api_key=None if backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA) else key,
        base_url=base_url if backend is AIBackend.OPENAI_COMPAT else None,
        model="requested-model",
        timeout=75,
    )
    before = config.model_dump()

    def completion(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == base_url + "chat/completions"
        assert request.headers["Authorization"] == f"Bearer {key}"
        body = json.loads(request.content)
        assert body["model"] == "requested-model"
        assert body["max_tokens"] == 17
        assert request.extensions["timeout"]["read"] == 75
        return httpx.Response(
            200,
            json={
                "id": "fixed-completion",
                "created": 0,
                "object": "chat.completion",
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixed-result"}}],
            },
        )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: sdk_client(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(completion), trust_env=False),
        ),
    )
    client = runtime.build_llm_client(config)
    try:
        result = client.chat_completions_create(
            model=config.resolve_model(),
            messages=[{"role": "user", "content": "test"}],
            temperature=0.3,
            max_tokens=17,
        )
        assert result.choices[0].message.content == "fixed-result"
        assert config.model_dump() == before
    finally:
        client._client.close()


def test_runtime_missing_credentials_raises_value_error_without_console_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    config = AIConfig(backend=AIBackend.OPENAI_COMPAT, base_url="https://example.invalid/v1")
    with pytest.raises(ValueError, match="AI API key not configured") as error:
        runtime.build_llm_client(config)
    assert "--auto-heal" not in str(error.value)
    assert capsys.readouterr() == ("", "")


def test_runtime_missing_sdk_is_an_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    original_import = builtins.__import__

    def without_sdk(name: str, *args: object, **kwargs: object) -> object:
        if name == "openai":
            raise ImportError("OpenAI SDK unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdk)
    config = AIConfig(backend=AIBackend.OLLAMA, model="fixed-model")
    with pytest.raises(ImportError, match="OpenAI SDK unavailable"):
        runtime.build_llm_client(config)


def test_runtime_client_close_releases_sdk_transport() -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    client = runtime.build_llm_client(AIConfig(backend=AIBackend.OLLAMA, model="fixed-model"))
    try:
        client.close()
        assert client._client.is_closed()
    finally:
        client._client.close()


@pytest.mark.parametrize("command", ["ai-analyze", "auto-heal"])
@pytest.mark.parametrize("failure", [None, "construct", "run"])
def test_cli_releases_owned_client_on_success_and_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    failure: str | None,
) -> None:
    from click.testing import CliRunner
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.cli import ai_commands
    from sqlseed_ai.healer._client import OpenAICompatAdapter

    path = tmp_path / "cli.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(value INTEGER NOT NULL)")
    config_path = tmp_path / "rules.yaml"
    config_path.write_text("tables:\n- name: items\n  columns:\n  - name: value\n    generator: integer\n")

    transport_client, sdk_client = no_network_openai_client()
    monkeypatch.setattr(ai_commands, "_build_llm_client", lambda _config: OpenAICompatAdapter(sdk_client))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("controlled runtime failure")

    if failure == "construct":
        monkeypatch.setattr(ai_commands, "_build_heal_orchestrator", fail)
    elif failure == "run":
        monkeypatch.setattr(AutoHealOrchestrator, "run", fail)
    arguments = ["--db", str(path), "--model", "fixed-model"]
    if command == "auto-heal":
        arguments.extend(["--config", str(config_path)])
    callback = ai_commands.ai_analyze if command == "ai-analyze" else ai_commands.auto_heal
    try:
        result = CliRunner().invoke(callback, arguments, env={"SQLSEED_AI_BACKEND": "ollama"})
        assert result.exit_code == (1 if failure else 0), result.output
        assert transport_client.is_closed
        if failure:
            assert "controlled runtime failure" in str(result.exception) + result.output
        elif command == "ai-analyze":
            assert "items" in result.output
        else:
            assert config_path.with_name("rules_healed.yaml").is_file()
    finally:
        sdk_client.close()


@pytest.mark.parametrize("budget,elapsed,exhausted", [(0.0, 0.0, True), (5.0, 5.0, True), (5.0, 4.0, False)])
def test_runtime_healer_repairs_real_schema_with_fixed_model_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: float, elapsed: float, exhausted: bool
) -> None:
    runtime = importlib.import_module("sqlseed_ai.runtime")
    from openai.types.chat import ChatCompletion
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.main import FastValidator
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    path = tmp_path / "runtime.db"
    with sqlite_connection(path) as db:
        db.execute("CREATE TABLE items(value INTEGER NOT NULL)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = FastValidator(ContractResolver(set(BUILTIN_VIOLATIONS), set()), db_path=str(path))
    broken = {"tables": [{"name": "items", "count": 2, "columns": [{"name": "value", "generator": "string"}]}]}
    repaired = {"tables": [{"name": "items", "count": 2, "columns": [{"name": "value", "generator": "integer"}]}]}
    violations = validator.validate(broken, snapshot).violations
    assert violations

    class FixedClient:
        def chat_completions_create(self, *, model: str, **kwargs: object) -> ChatCompletion:
            assert model == "fixed-model"
            return ChatCompletion.model_validate(
                {
                    "id": "fixed",
                    "created": 0,
                    "model": model,
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(repaired),
                            },
                        }
                    ],
                }
            )

    healer = runtime.build_heal_orchestrator(
        AIConfig(model="fixed-model"),
        FixedClient(),
        snapshot,
        validator,
        schema_hash=snapshot.schema_hash,
        max_retries=1,
    )
    result = healer.heal(SubgraphTask(task_id="items", tables=["items"]), violations, broken)
    assert result.success
    assert result.level_used == 1
    assert result.config["tables"][0]["columns"][0]["generator"] == "integer"
    assert validator.validate(result.config, snapshot).is_clean

    no_rounds = runtime.build_heal_orchestrator(
        AIConfig(model="fixed-model"), FixedClient(), snapshot, validator, max_retries=0
    )
    degraded = no_rounds.heal(SubgraphTask(task_id="items", tables=["items"]), violations, broken)
    assert degraded.level_used == 4
    assert degraded.total_attempts == 0

    expired = runtime.build_heal_orchestrator(
        AIConfig(model="fixed-model"), FixedClient(), snapshot, validator, time_budget_seconds=budget
    )
    ticks = iter((100.0, 100.0 + elapsed))
    monkeypatch.setattr("sqlseed_ai.healer.orchestrator.time.monotonic", lambda: next(ticks, 100.0 + elapsed))
    timed_out = expired.heal(SubgraphTask(task_id="items", tables=["items"]), violations, broken)
    if exhausted:
        assert timed_out.level_used == 4
        assert not timed_out.attempts
        assert {reason.value for reason in timed_out.degrade_reasons.values()} == {"time_budget_exhausted"}
    else:
        assert timed_out.success
        assert timed_out.level_used == 1
        assert validator.validate(timed_out.config, snapshot).is_clean
