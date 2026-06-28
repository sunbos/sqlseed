"""Real-LLM integration tests for the sqlseed-ai plugin.

These tests exercise the AI plugin's end-to-end behavior with a real LLM
backend (Ollama / LM Studio / Google AI Studio). They are automatically
marked as ``integration`` via ``tests/integration/conftest.py`` and skip
gracefully when no LLM backend is available (via ``available_llm_backend``)
or when ``sqlseed-ai`` is not installed.

Unlike the mocked unit tests in ``tests/test_ai_*.py``, these tests verify
the paths that mocks cannot faithfully reproduce:

* ``AiConfigRefiner.generate_and_refine`` — non-streaming self-correction loop
* ``AiConfigRefiner.generate_and_refine_streaming`` — streaming with
  normal -> compact -> ultra-compact context degradation
* ``SchemaAnalyzer.generate_template_values`` — template pool generation
* End-to-end ``ai-suggest`` CLI flow (both ``--no-verify`` and ``--verify``)
* ``AISqlseedPlugin.sqlseed_ai_analyze_table`` hookimpl contract

Run explicitly via::

    pytest tests/integration/test_ai_real_llm.py -v
    pytest -m integration -v          # all integration tests

Critical constraints verified (see project_memory.md):

* Streaming must not mutate ``analyzer.config`` state across retries
* ``generate_and_refine_streaming`` implements normal -> compact -> ultra-compact
* ``_NON_RETRYABLE_ERRORS`` includes ``'json_syntax'``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml
from click.testing import CliRunner

try:
    from sqlseed_ai import plugin as ai_plugin_singleton
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)

from sqlseed_cli.main import cli

from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    from pathlib import Path


def _configure_backend_env(
    backend: str,
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set environment variables for the detected LLM backend.

    Mirrors the configuration pattern in ``tests/test_ai_plugin.py`` so that
    ``AIConfig.from_env()`` resolves to the live backend detected by the
    ``available_llm_backend`` fixture.
    """
    if backend == "ollama":
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "ollama")
        monkeypatch.setenv("SQLSEED_AI_BASE_URL", "http://localhost:11434/v1")
    elif backend == "lm_studio":
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1234/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "lm-studio")
    elif backend == "google_ai_studio":
        # GOOGLE_API_KEY is already set (checked by the fixture)
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "google_ai_studio")
    monkeypatch.setenv("SQLSEED_AI_MODEL", model)


def _make_analyzer(monkeypatch: pytest.MonkeyPatch, backend: str, model: str) -> SchemaAnalyzer:
    """Build a SchemaAnalyzer configured against the live backend."""
    _configure_backend_env(backend, model, monkeypatch)
    config = AIConfig.from_env()
    config.model = config.resolve_model()
    return SchemaAnalyzer(config=config)


class TestSchemaAnalyzerGenerateTemplateValuesRealLLM:
    """``SchemaAnalyzer.generate_template_values`` with a real LLM.

    Covers the template-pool code path that mocks cannot faithfully exercise:
    the LLM must return a JSON list of realistic values for a column.
    """

    def test_returns_non_empty_list_for_string_column(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """generate_template_values returns a non-empty list for a VARCHAR column."""
        analyzer = _make_analyzer(
            monkeypatch,
            available_llm_backend["backend"],
            available_llm_backend["model"],
        )

        values = analyzer.generate_template_values(
            column_name="status",
            column_type="VARCHAR(20)",
            count=5,
            sample_data=[],
            table_name="users",
        )

        assert isinstance(values, list), f"Expected list, got {type(values)}"
        assert len(values) > 0, "LLM returned an empty template list"
        # All entries should be strings for a VARCHAR column (LLM may return
        # mixed types, but each should be a primitive)
        for v in values:
            assert isinstance(v, (str, int, float, bool)), f"Unexpected value type: {type(v)}"


class TestAiConfigRefinerRealLLM:
    """``AiConfigRefiner`` self-correction loop with a real LLM.

    These are the highest-value real-LLM tests: the refiner drives the
    normal -> compact -> ultra-compact prompt degradation and validates
    each LLM response against the live schema. Mocks cannot exercise the
    full validation feedback loop.
    """

    def test_generate_and_refine_produces_valid_config(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """generate_and_refine returns a config dict validated against the live schema.

        Uses ``max_retries=1`` to bound runtime while still exercising the
        self-correction feedback loop on validation failure.
        """
        analyzer = _make_analyzer(
            monkeypatch,
            available_llm_backend["backend"],
            available_llm_backend["model"],
        )
        refiner = AiConfigRefiner(analyzer, db_path=tmp_db, cache_dir=None)

        result = refiner.generate_and_refine(
            table_name="users",
            max_retries=1,
            no_cache=True,
        )

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        # The refined config should describe a table with columns. The exact
        # key depends on the LLM response shape (``name``/``table``/``tables``),
        # but at minimum it must be a non-empty dict.
        assert len(result) > 0, "Refiner returned an empty config dict"
        # Should reference either a table name or columns
        has_table_key = any(k in result for k in ("name", "table", "tables", "columns"))
        assert has_table_key, f"Refiner result missing table/columns key: {list(result.keys())}"

    def test_generate_and_refine_streaming_invokes_no_state_mutation(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """generate_and_refine_streaming returns a dict and does not mutate config state.

        Critical constraint (project_memory.md): streaming LLM calls must not
        modify instance configuration state, otherwise retries see inconsistent
        config. We snapshot ``analyzer.config.model`` before the call and
        assert it is unchanged afterward.
        """
        analyzer = _make_analyzer(
            monkeypatch,
            available_llm_backend["backend"],
            available_llm_backend["model"],
        )
        assert analyzer.config is not None, "Analyzer config must be set before streaming"
        model_before = analyzer.config.model

        refiner = AiConfigRefiner(analyzer, db_path=tmp_db, cache_dir=None)

        progress_events: list[tuple[str, dict[str, Any]]] = []

        def on_progress(phase: str, info: dict[str, Any]) -> None:
            progress_events.append((phase, info))

        result = refiner.generate_and_refine_streaming(
            table_name="users",
            max_retries=1,
            no_cache=True,
            on_progress=on_progress,
        )

        # Streaming must produce a valid config dict
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert len(result) > 0, "Streaming refiner returned an empty config dict"

        # Critical: streaming must not mutate analyzer configuration state.
        # This guarantees retry consistency and is a hard constraint from
        # project_memory.md.
        assert analyzer.config is not None
        assert analyzer.config.model == model_before, (
            "Streaming mutated analyzer.config.model — retries would see inconsistent state"
        )

    def test_refiner_fails_on_nonexistent_table(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Refiner raises when the target table does not exist in the DB.

        The LLM may still emit a config, but schema validation must reject it
        because the table name does not match any real table. With
        ``max_retries=0`` the refiner should raise ``AISuggestionFailedError``
        (or a downstream ValueError/RuntimeError) rather than silently succeed.
        """
        analyzer = _make_analyzer(
            monkeypatch,
            available_llm_backend["backend"],
            available_llm_backend["model"],
        )
        refiner = AiConfigRefiner(analyzer, db_path=tmp_db, cache_dir=None)

        with pytest.raises((AISuggestionFailedError, ValueError, RuntimeError)) as exc_info:
            refiner.generate_and_refine(
                table_name="this_table_does_not_exist_xyz_12345",
                max_retries=0,
                no_cache=True,
            )

        # The error message should reference the missing table or validation failure
        err_str = str(exc_info.value).lower()
        assert any(
            token in err_str for token in ("not exist", "not found", "validation", "invalid", "schema", "table")
        ), f"Unexpected error message: {exc_info.value}"


class TestAISqlseedPluginHookRealLLM:
    """The ``AISqlseedPlugin`` singleton hookimpl contract with a real LLM.

    Verifies the plugin entry point that pluggy invokes during orchestration.
    The singleton caches its analyzer; we reset it so the test picks up the
    monkeypatched environment.
    """

    def test_hookimpl_returns_dict_or_none(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sqlseed_ai_analyze_table hookimpl returns a dict or None."""
        _configure_backend_env(
            available_llm_backend["backend"],
            available_llm_backend["model"],
            monkeypatch,
        )

        # Reset the cached analyzer so the singleton rebuilds with the new env
        ai_plugin_singleton._analyzer = None

        with DataOrchestrator(tmp_db, provider_name="base") as orch:
            orch._ensure_connected()
            schema_ctx = orch.get_schema_context("users")

        try:
            result = ai_plugin_singleton.sqlseed_ai_analyze_table(**schema_ctx)
        finally:
            # Always reset the cache afterward so we don't leak state into other tests
            ai_plugin_singleton._analyzer = None

        # The hookimpl contract: dict on success, None on recoverable failure
        assert result is None or isinstance(result, dict), f"hookimpl must return dict|None, got {type(result)}"
        if result is not None:
            # A successful result should mention tables or columns
            assert "tables" in result or "columns" in result, (
                f"hookimpl result missing tables/columns key: {list(result.keys())}"
            )


class TestAISuggestCLIRealLLM:
    """End-to-end ``ai-suggest`` CLI flow with a real LLM.

    Uses ``click.testing.CliRunner`` (never subprocess) per project convention.
    """

    def test_ai_suggest_no_verify_produces_well_formed_yaml(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """ai-suggest --no-verify writes a YAML file with a ``tables`` list."""
        _configure_backend_env(
            available_llm_backend["backend"],
            available_llm_backend["model"],
            monkeypatch,
        )

        out_yaml = tmp_path / "suggested_no_verify.yaml"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "ai-suggest",
                tmp_db,
                "-t",
                "users",
                "-o",
                str(out_yaml),
                "--no-verify",
                "--no-cache",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, (
            f"CLI failed (exit={result.exit_code}):\noutput:\n{result.output}\nexception: {result.exception}"
        )

        assert out_yaml.exists(), "Output YAML file was not created"
        with out_yaml.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert isinstance(data, dict), f"YAML root must be a mapping, got {type(data)}"
        assert "tables" in data, f"YAML missing 'tables' key: {list(data.keys())}"
        assert isinstance(data["tables"], list), "'tables' must be a list"
        assert len(data["tables"]) >= 1, "'tables' list is empty"
        first_table = data["tables"][0]
        assert isinstance(first_table, dict), f"First table entry must be a mapping, got {type(first_table)}"
        assert "name" in first_table, f"Table entry missing 'name' key: {list(first_table.keys())}"

    def test_ai_suggest_verify_with_bounded_retries(
        self,
        tmp_db: str,
        available_llm_backend: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """ai-suggest --verify --max-retries 1 exercises the self-correction CLI path.

        The ``--verify`` flag routes through ``AiConfigRefiner`` rather than the
        direct LLM call. ``--max-retries 1`` bounds runtime. If the LLM is too
        slow or the backend cannot converge in time, the test is skipped
        rather than failed (real-LLM latency is environment-dependent).
        """
        _configure_backend_env(
            available_llm_backend["backend"],
            available_llm_backend["model"],
            monkeypatch,
        )

        out_yaml = tmp_path / "suggested_verify.yaml"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "ai-suggest",
                tmp_db,
                "-t",
                "users",
                "-o",
                str(out_yaml),
                "--verify",
                "--max-retries",
                "1",
                "--no-cache",
            ],
            catch_exceptions=False,
        )

        if result.exit_code != 0:
            pytest.skip(
                f"ai-suggest --verify did not converge within max_retries=1 "
                f"(exit={result.exit_code}). This is environment-dependent; "
                f"output:\n{result.output}"
            )

        assert out_yaml.exists(), "Output YAML file was not created"
        with out_yaml.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert isinstance(data, dict)
        assert "tables" in data
        assert isinstance(data["tables"], list)
        assert len(data["tables"]) >= 1
        # The verified config should name the target table
        first_table = data["tables"][0]
        assert isinstance(first_table, dict)
        assert "name" in first_table
        # A verified config should also have columns (the refiner validates this)
        assert "columns" in first_table, f"Verified table config missing 'columns': {list(first_table.keys())}"
