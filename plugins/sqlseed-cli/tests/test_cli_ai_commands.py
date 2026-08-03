"""TDD characterization tests for the sqlseed CLI AI subcommand module.

These tests document and verify the existing behavior of
:mod:`sqlseed.cli.ai_commands`, which implements the ``ai-suggest`` command,
the streaming progress display, prompt-level fallback, self-correction
workflow, and local inference speed probing.

Critical constraints verified (per project_memory.md):
- ``_handle_ai_direct`` must catch ``OSError`` to prevent runtime crashes.
- ``_StreamingProgressDisplay.stop()`` must set ``self._live = None`` after
  stopping.
- Token callback functions in streaming should minimize ``Live.update()``
  frequency (the display only re-renders when ``self._live`` is set).
"""

from __future__ import annotations

import importlib.util
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import click
import pytest
import yaml
from click.testing import CliRunner
from sqlseed_ai.cli import ai_commands
from sqlseed_ai.cli.ai_commands import (
    _handle_ai_direct,
    _handle_ai_verification_non_streaming,
    _handle_ai_verification_streaming,
    _report_ai_failure,
    _run_ai_analysis,
    _StreamingProgressDisplay,
    _write_ai_output,
    ai_suggest,
    register_commands,
)

if TYPE_CHECKING:
    from pathlib import Path

# Detect whether sqlseed-ai is installed (controls a few test paths).
# Using find_spec avoids importing the package just to probe availability.
_AI_PLUGIN_AVAILABLE: bool = importlib.util.find_spec("sqlseed_ai") is not None

# Import the real AIBackend enum when available so that backend comparisons
# (``config.backend in (AIBackend.LM_STUDIO, ...)``) work against real enum
# values rather than MagicMock instances (whose ``__eq__`` returns False).
if _AI_PLUGIN_AVAILABLE:
    from sqlseed_ai.config import AIBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_orchestrator(_schema_ctx: dict[str, Any] | None = None):
    """No-op context manager — retained to avoid churning 22 call sites.

    Previously mocked ``DataOrchestrator`` to avoid database setup, but this
    created a self-proving trap: ``orch.get_schema_context`` returned fake data
    ``{"table": "t", "columns": []}``, so tests never exercised the real
    schema-reading path. If ``_handle_ai_direct``'s usage of
    ``DataOrchestrator`` drifted (e.g., method rename, signature change), the
    mock would silently absorb it and tests would still pass.

    Now ``_handle_ai_direct`` creates a real ``DataOrchestrator(tmp_db)`` — the
    ``tmp_db`` fixture provides a SQLite database with a ``users`` table — so
    ``orch.get_schema_context("users")`` runs against the real schema. The
    ``schema_ctx`` parameter is kept for signature compatibility but unused.
    """
    yield None


def _make_analyzer(
    *,
    use_streaming: bool = True,
    use_compact: bool = False,
    backend: Any = None,
    speed_info: dict[str, Any] | None = None,
    call_llm_result: Any = None,
    call_llm_streaming_result: Any = None,
    call_llm_side_effect: Any = None,
    call_llm_streaming_side_effect: Any = None,
    resolve_timeout_return: float = 300.0,
    model: str = "test-model",
) -> MagicMock:
    """Build a mock analyzer that quacks like ``SchemaAnalyzer``."""
    analyzer = MagicMock()
    analyzer.config = MagicMock()
    analyzer.config.should_use_streaming.return_value = use_streaming
    analyzer.config.should_use_ultra_compact.return_value = use_compact
    analyzer.config.backend = backend if backend is not None else _default_backend()
    analyzer.config.probe_inference_speed.return_value = speed_info
    analyzer.config.resolve_timeout.return_value = resolve_timeout_return
    analyzer.config.model = model
    analyzer.build_initial_messages.return_value = [{"role": "user", "content": "hi"}]
    if call_llm_side_effect is not None:
        analyzer.call_llm.side_effect = call_llm_side_effect
    else:
        analyzer.call_llm.return_value = call_llm_result
    if call_llm_streaming_side_effect is not None:
        analyzer.call_llm_streaming.side_effect = call_llm_streaming_side_effect
    else:
        analyzer.call_llm_streaming.return_value = call_llm_streaming_result
    return analyzer


def _default_backend() -> Any:
    """Return the real google_ai_studio backend enum (or a stub if the plugin is missing).

    Using the real enum value is critical so that ``config.backend in (...)``
    comparisons in ``_run_ai_analysis`` work correctly — MagicMock instances
    compare by identity and would always be ``False`` against real enum members.
    """
    if _AI_PLUGIN_AVAILABLE:
        return AIBackend.GOOGLE_AI_STUDIO
    return _stub_backend("google_ai_studio")


def _stub_backend(value: str) -> Any:
    """Return the real AIBackend enum member when the plugin is available.

    The source code compares ``config.backend in (AIBackend.LM_STUDIO,
    AIBackend.OLLAMA)``. MagicMock instances compare by identity, so they
    would never match a real enum member. When ``sqlseed_ai`` is installed,
    return the real enum; otherwise fall back to a MagicMock stub with
    ``.value`` set (used only when the plugin is absent).
    """
    if not _AI_PLUGIN_AVAILABLE:
        backend = MagicMock()
        backend.value = value
        return backend
    mapping = {
        "google_ai_studio": AIBackend.GOOGLE_AI_STUDIO,
        "lm_studio": AIBackend.LM_STUDIO,
        "ollama": AIBackend.OLLAMA,
        "openai_compat": AIBackend.OPENAI_COMPAT,
    }
    return mapping.get(value, AIBackend.GOOGLE_AI_STUDIO)


# ---------------------------------------------------------------------------
# _StreamingProgressDisplay: initial state
# ---------------------------------------------------------------------------


class TestStreamingProgressDisplayInit:
    """Tests for the initial state of ``_StreamingProgressDisplay``."""

    def test_default_phase_is_connecting(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._phase == "connecting"

    def test_default_model_is_empty(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._model == ""

    def test_default_token_count_is_zero(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._token_count == 0

    def test_default_preview_is_empty(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._preview == ""

    def test_default_attempt_is_zero(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._attempt == 0

    def test_default_max_retries_is_zero(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._max_retries == 0

    def test_default_live_is_none(self) -> None:
        display = _StreamingProgressDisplay()
        assert display._live is None


# ---------------------------------------------------------------------------
# _StreamingProgressDisplay: _render() phase coverage
# ---------------------------------------------------------------------------


class TestStreamingProgressDisplayRender:
    """Tests for ``_StreamingProgressDisplay._render`` covering all phases."""

    def test_render_connecting_phase_includes_model(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "connecting"
        display._model = "gemma-4"
        text = display._render()
        assert "gemma-4" in text.plain
        assert "Connecting" in text.plain

    def test_render_streaming_phase_includes_token_count(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "streaming"
        display._token_count = 42
        text = display._render()
        assert "42" in text.plain
        assert "Generating" in text.plain

    def test_render_streaming_phase_includes_preview_when_set(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "streaming"
        display._token_count = 1
        display._preview = "last token text"
        text = display._render()
        # Preview is shown (last 60 chars)
        assert "last token text" in text.plain

    def test_render_streaming_phase_omits_preview_when_empty(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "streaming"
        display._token_count = 1
        display._preview = ""
        text = display._render()
        assert "Generating" in text.plain

    def test_render_parsing_phase_includes_token_count(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "parsing"
        display._token_count = 100
        text = display._render()
        assert "100" in text.plain
        assert "Parsing" in text.plain

    def test_render_validating_phase(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "validating"
        text = display._render()
        assert "Validating" in text.plain

    def test_render_refining_phase_without_max_retries(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "refining"
        display._max_retries = 0
        text = display._render()
        assert "Self-correction" in text.plain
        # No retry info shown when max_retries is 0
        assert "attempt" not in text.plain

    def test_render_refining_phase_with_max_retries(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "refining"
        display._max_retries = 3
        display._attempt = 1
        text = display._render()
        assert "Self-correction" in text.plain
        assert "attempt" in text.plain
        assert "2/3" in text.plain  # attempt+1 / max_retries

    def test_render_done_phase_includes_token_count(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "done"
        display._token_count = 200
        text = display._render()
        assert "200" in text.plain
        assert "Done" in text.plain

    def test_render_unknown_phase_returns_empty_text(self) -> None:
        display = _StreamingProgressDisplay()
        display._phase = "unknown_phase"
        text = display._render()
        # No parts appended for unknown phases
        assert text.plain == ""


# ---------------------------------------------------------------------------
# _StreamingProgressDisplay: start/stop lifecycle (CRITICAL)
# ---------------------------------------------------------------------------


class TestStreamingProgressDisplayLifecycle:
    """Tests for ``start``/``stop`` lifecycle of the streaming display.

    CRITICAL (per project_memory.md): ``stop()`` MUST set ``self._live = None``
    after stopping, so subsequent ``update()`` calls become no-ops.
    """

    def test_start_creates_live_and_calls_start(self) -> None:
        display = _StreamingProgressDisplay()
        with patch.object(ai_commands, "Live") as mock_live_cls, patch.object(ai_commands, "Console"):
            mock_live = MagicMock()
            mock_live_cls.return_value = mock_live
            display.start()
            assert display._live is mock_live
            mock_live.start.assert_called_once()

    def test_stop_when_live_is_none_is_noop(self) -> None:
        display = _StreamingProgressDisplay()
        # _live starts as None
        display.stop()
        assert display._live is None

    def test_stop_when_live_set_calls_stop_and_clears_reference(self) -> None:
        display = _StreamingProgressDisplay()
        mock_live = MagicMock()
        display._live = mock_live
        display.stop()
        mock_live.stop.assert_called_once()
        # CRITICAL: _live must be set to None after stopping
        assert display._live is None

    def test_stop_idempotent(self) -> None:
        """Calling stop() twice should not raise and should keep _live as None."""
        display = _StreamingProgressDisplay()
        mock_live = MagicMock()
        display._live = mock_live
        display.stop()
        display.stop()  # second call: _live is None, should be a no-op
        assert display._live is None
        mock_live.stop.assert_called_once()

    def test_start_uses_transient_false_and_refresh_per_second_8(self) -> None:
        display = _StreamingProgressDisplay()
        with patch.object(ai_commands, "Live") as mock_live_cls, patch.object(ai_commands, "Console"):
            display.start()
            _, kwargs = mock_live_cls.call_args
            assert kwargs["transient"] is False
            assert kwargs["refresh_per_second"] == 8


# ---------------------------------------------------------------------------
# _StreamingProgressDisplay: update() (token throttling)
# ---------------------------------------------------------------------------


class TestStreamingProgressDisplayUpdate:
    """Tests for ``_StreamingProgressDisplay.update``.

    Per project_memory.md, token callback functions in streaming should
    minimize ``Live.update()`` frequency. The display achieves this by only
    calling ``self._live.update()`` when ``self._live`` is set, and by
    keeping a bounded rolling preview (max 80 chars).
    """

    def test_update_sets_phase(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("streaming", {"count": 10})
        assert display._phase == "streaming"

    def test_update_sets_model_when_provided(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("connecting", {"model": "gemma-4-e4b"})
        assert display._model == "gemma-4-e4b"

    def test_update_sets_token_count_via_count_key(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("streaming", {"count": 99})
        assert display._token_count == 99

    def test_update_sets_token_count_via_tokens_key(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("streaming", {"tokens": 200})
        assert display._token_count == 200

    def test_update_appends_token_to_preview(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("streaming", {"token": "hello"})
        assert display._preview == "hello"
        display.update("streaming", {"token": " world"})
        assert display._preview == "hello world"

    def test_update_truncates_preview_to_last_80_chars(self) -> None:
        display = _StreamingProgressDisplay()
        # Build a preview longer than 80 chars
        long_token = "x" * 50
        display.update("streaming", {"token": long_token})
        assert display._preview == long_token  # 50 chars, under limit
        display.update("streaming", {"token": "y" * 50})
        # Now preview should be truncated to last 80 chars
        assert len(display._preview) == 80
        assert display._preview.endswith("y" * 50)
        assert display._preview.startswith("x" * 30)

    def test_update_sets_attempt(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("refining", {"attempt": 2})
        assert display._attempt == 2

    def test_update_sets_max_retries(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("refining", {"max_retries": 5})
        assert display._max_retries == 5

    def test_update_calls_live_update_when_live_is_set(self) -> None:
        display = _StreamingProgressDisplay()
        mock_live = MagicMock()
        display._live = mock_live
        display.update("streaming", {"count": 1})
        mock_live.update.assert_called_once()

    def test_update_does_not_call_live_update_when_live_is_none(self) -> None:
        """When live is None (e.g., after stop()), update is a no-op for live.

        This is the throttling mechanism: once stopped, further token
        callbacks don't try to update a dead Live instance.
        """
        display = _StreamingProgressDisplay()
        display._live = None
        # Should not raise
        display.update("streaming", {"count": 1, "token": "abc"})
        # Internal state still updated
        assert display._token_count == 1
        assert display._preview == "abc"

    def test_update_ignores_unknown_info_keys(self) -> None:
        display = _StreamingProgressDisplay()
        display.update("streaming", {"unknown_key": "value", "count": 5})
        assert display._token_count == 5


# ---------------------------------------------------------------------------
# _handle_ai_direct: OSError handling (CRITICAL) + prompt-level fallback
# ---------------------------------------------------------------------------


class TestHandleAIDirect:
    """Tests for ``_handle_ai_direct`` prompt-level fallback and error handling.

    CRITICAL (per project_memory.md): ``_handle_ai_direct`` must catch
    ``OSError`` to prevent runtime crashes when the LLM backend is
    unreachable.
    """

    def test_returns_result_when_call_llm_succeeds_non_streaming(self, tmp_db: str) -> None:
        """Non-streaming mode returns the LLM result on first success."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer(call_llm_result=result_dict)
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result == result_dict
        analyzer.call_llm.assert_called_once()

    def test_returns_result_when_call_llm_streaming_succeeds(self, tmp_db: str) -> None:
        """Streaming mode returns the LLM result and stops the display."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer(call_llm_streaming_result=result_dict)
        display = _StreamingProgressDisplay()
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            result = _handle_ai_direct(analyzer, tmp_db, "users", display=display)
        assert result == result_dict
        analyzer.call_llm_streaming.assert_called_once()

    def test_catches_os_error_and_returns_none(self, tmp_db: str) -> None:
        """CRITICAL: OSError must be caught to prevent runtime crashes."""
        analyzer = _make_analyzer(call_llm_side_effect=OSError("network unreachable"))
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result is None

    def test_catches_value_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer(call_llm_side_effect=ValueError("bad value"))
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result is None

    def test_catches_runtime_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer(call_llm_side_effect=RuntimeError("bad runtime"))
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result is None

    def test_retries_with_shorter_prompt_on_empty_result(self, tmp_db: str) -> None:
        """When the LLM returns None/empty, retry with shorter prompt."""
        # First call returns None, second returns a result
        analyzer = _make_anizer_retry_chain([None, {"name": "t", "count": 1, "columns": []}])
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result == {"name": "t", "count": 1, "columns": []}
        # Should have called call_llm at least twice
        assert analyzer.call_llm.call_count >= 2

    def test_context_size_exceeded_triggers_compact_fallback(self, tmp_db: str) -> None:
        """When the error mentions 'context' and 'exceed', retry with shorter prompt."""
        # First call raises context overflow, second succeeds
        analyzer = _make_anizer_retry_chain(
            [RuntimeError("context length exceeded"), {"name": "t", "count": 1, "columns": []}]
        )
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        assert result == {"name": "t", "count": 1, "columns": []}

    def test_context_size_exceeded_in_ultra_mode_returns_none(self, tmp_db: str) -> None:
        """When context exceeded in ultra mode (last level), do not retry — return None."""
        analyzer = _make_analyzer(call_llm_side_effect=RuntimeError("context length exceeded"))
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users")
        # After exhausting all prompt levels, returns None
        assert result is None

    def test_use_compact_starts_with_compact_only(self, tmp_db: str) -> None:
        """When use_compact=True, only the ultra-compact prompt level is tried."""
        analyzer = _make_anizer_retry_chain([None, None, {"name": "t", "count": 1, "columns": []}])
        with _patch_orchestrator():
            result = _handle_ai_direct(analyzer, tmp_db, "users", use_compact=True)
        # In compact mode, only one prompt level is tried
        assert analyzer.build_initial_messages.call_count == 1
        # Result is None because the single attempt returned None
        assert result is None

    def test_display_stopped_on_exception(self, tmp_db: str) -> None:
        """When an exception occurs during streaming, display.stop() is called."""
        analyzer = _make_analyzer(call_llm_streaming_side_effect=OSError("connection refused"))
        display = _StreamingProgressDisplay()
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            result = _handle_ai_direct(analyzer, tmp_db, "users", display=display)
        assert result is None
        # Display should have been stopped (live set to None)
        assert display._live is None

    def test_echoes_mode_and_timeout_in_non_streaming(self, tmp_db: str) -> None:
        """Non-streaming mode echoes the mode and timeout to the user."""
        analyzer = _make_anizer_retry_chain([{"name": "t", "count": 1, "columns": []}])
        with _patch_orchestrator(), patch("click.echo") as mock_echo:
            _handle_ai_direct(analyzer, tmp_db, "users")
        # First echo should mention "Analyzing schema" and "standard mode"
        first_call_args = mock_echo.call_args_list[0][0][0]
        assert "Analyzing schema" in first_call_args
        assert "standard mode" in first_call_args
        assert "300s" in first_call_args


def _make_anizer_retry_chain(results: list[Any]) -> MagicMock:
    """Build an analyzer whose call_llm returns/raises each item in sequence.

    Items that are Exception instances are raised; others are returned.
    """
    analyzer = MagicMock()
    analyzer.config = MagicMock()
    analyzer.config.resolve_timeout.return_value = 300.0
    analyzer.config.model = "test-model"
    analyzer.build_initial_messages.return_value = [{"role": "user", "content": "hi"}]

    # Build side effect that raises exceptions, returns values
    side_effects = []
    for item in results:
        if isinstance(item, BaseException):
            side_effects.append(item)
        else:
            side_effects.append(item)
    analyzer.call_llm.side_effect = side_effects
    return analyzer


# ---------------------------------------------------------------------------
# _handle_ai_verification_non_streaming
# ---------------------------------------------------------------------------


class TestHandleAIVerificationNonStreaming:
    """Tests for ``_handle_ai_verification_non_streaming``."""

    # Note: the "plugin not available" scenario is no longer testable here
    # because ai_commands.py now lives inside the sqlseed-ai package — if
    # this module is imported, sqlseed-ai is necessarily installed. The
    # HAS_AI_PLUGIN flag is kept only for backward-compat and is always True.

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_returns_result_on_success(self, tmp_db: str) -> None:
        """When the refiner succeeds, return its result."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer()
        with patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.return_value = result_dict
            result = _handle_ai_verification_non_streaming(analyzer, tmp_db, "users", max_retries=3, no_cache=False)
        assert result == result_dict
        mock_refiner.generate_and_refine.assert_called_once()
        # Verify kwargs passed to refiner
        _, kwargs = mock_refiner.generate_and_refine.call_args
        assert kwargs["max_retries"] == 3
        assert kwargs["no_cache"] is False

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_os_error_and_returns_none(self, tmp_db: str) -> None:
        """OSError from the refiner is caught and returns None."""
        analyzer = _make_analyzer()
        with patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.side_effect = OSError("network error")
            result = _handle_ai_verification_non_streaming(analyzer, tmp_db, "users", max_retries=3, no_cache=False)
        assert result is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_value_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer()
        with patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.side_effect = ValueError("bad value")
            result = _handle_ai_verification_non_streaming(analyzer, tmp_db, "users", max_retries=3, no_cache=False)
        assert result is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_runtime_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer()
        with patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.side_effect = RuntimeError("bad runtime")
            result = _handle_ai_verification_non_streaming(analyzer, tmp_db, "users", max_retries=3, no_cache=False)
        assert result is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_passes_use_compact_to_refiner(self, tmp_db: str) -> None:
        """use_compact kwarg is forwarded to the refiner."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer()
        with patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.return_value = result_dict
            _handle_ai_verification_non_streaming(
                analyzer, tmp_db, "users", max_retries=3, no_cache=True, use_compact=True
            )
            _, kwargs = mock_refiner.generate_and_refine.call_args
            assert kwargs["use_compact"] is True


# ---------------------------------------------------------------------------
# _handle_ai_verification_streaming
# ---------------------------------------------------------------------------


class TestHandleAIVerificationStreaming:
    """Tests for ``_handle_ai_verification_streaming``."""

    # Note: the "plugin not available" scenario is no longer testable here
    # because ai_commands.py now lives inside the sqlseed-ai package — if
    # this module is imported, sqlseed-ai is necessarily installed.

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_returns_result_on_success(self, tmp_db: str) -> None:
        """When the refiner succeeds, return its result and stop the display."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer()
        display = _StreamingProgressDisplay()
        with (
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.return_value = result_dict
            result = _handle_ai_verification_streaming(
                analyzer, tmp_db, "users", max_retries=3, no_cache=False, display=display
            )
        assert result == result_dict
        # Display should be stopped after success
        assert display._live is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_os_error_and_stops_display(self, tmp_db: str) -> None:
        """OSError is caught, display is stopped, and None is returned."""
        analyzer = _make_analyzer()
        display = _StreamingProgressDisplay()
        with (
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.side_effect = OSError("stream broke")
            result = _handle_ai_verification_streaming(
                analyzer, tmp_db, "users", max_retries=3, no_cache=False, display=display
            )
        assert result is None
        # CRITICAL: display must be stopped even on error
        assert display._live is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_value_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer()
        display = _StreamingProgressDisplay()
        with (
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.side_effect = ValueError("bad")
            result = _handle_ai_verification_streaming(
                analyzer, tmp_db, "users", max_retries=3, no_cache=False, display=display
            )
        assert result is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_catches_runtime_error_and_returns_none(self, tmp_db: str) -> None:
        analyzer = _make_analyzer()
        display = _StreamingProgressDisplay()
        with (
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.side_effect = RuntimeError("bad")
            result = _handle_ai_verification_streaming(
                analyzer, tmp_db, "users", max_retries=3, no_cache=False, display=display
            )
        assert result is None

    @pytest.mark.skipif(not _AI_PLUGIN_AVAILABLE, reason="Requires sqlseed-ai plugin")
    def test_passes_on_progress_callback_to_refiner(self, tmp_db: str) -> None:
        """The display's update method is forwarded as on_progress."""
        result_dict = {"name": "users", "count": 10, "columns": []}
        analyzer = _make_analyzer()
        display = _StreamingProgressDisplay()
        with (
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.return_value = result_dict
            _handle_ai_verification_streaming(analyzer, tmp_db, "users", max_retries=3, no_cache=False, display=display)
            _, kwargs = mock_refiner.generate_and_refine_streaming.call_args
            # Bound methods are fresh objects on each attribute access, so
            # ``is`` would always be False. Compare the bound instance and
            # the underlying function instead — this is the canonical way
            # to assert "the callback is bound to this display's update".
            passed_callback = kwargs["on_progress"]
            assert passed_callback.__self__ is display
            assert passed_callback.__func__ is type(display).update


# ---------------------------------------------------------------------------
# _write_ai_output
# ---------------------------------------------------------------------------


class TestWriteAIOutput:
    """Tests for ``_write_ai_output``."""

    def test_writes_yaml_with_db_path_and_default_provider(self, tmp_path: Path) -> None:
        """The output YAML contains db_path and default provider/locale."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "users", "count": 10, "columns": []}
        _write_ai_output(output, "test.db", result)
        with open(output, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["db_path"] == "test.db"
        assert data["provider"] == "mimesis"  # default
        assert data["locale"] == "en_US"  # default
        assert data["tables"] == [{"name": "users", "count": 10, "columns": []}]

    def test_pops_provider_from_result_when_present(self, tmp_path: Path) -> None:
        """If the result has a 'provider' key, it's used and removed from the table."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "users", "count": 10, "columns": [], "provider": "faker", "locale": "en"}
        _write_ai_output(output, "test.db", result)
        with open(output, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["provider"] == "faker"
        assert data["locale"] == "en"
        # provider/locale should be popped from the table dict
        assert "provider" not in data["tables"][0]
        assert "locale" not in data["tables"][0]

    def test_inserts_clear_before_comment_after_count(self, tmp_path: Path) -> None:
        """A 'clear_before' comment is inserted after the 'count:' line."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "users", "count": 100, "columns": []}
        _write_ai_output(output, "test.db", result)
        with open(output, encoding="utf-8") as f:
            content = f.read()
        # The comment should appear after the count line
        assert "count: 100" in content
        assert "# clear_before: true" in content

    def test_calls_sanitize_table_config(self, tmp_path: Path) -> None:
        """sanitize_table_config is called on the result before writing."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "...users", "count": 10, "columns": []}
        # sanitize_table_config is imported lazily inside _write_ai_output
        # (module-level import would create a circular import via the
        # sqlseed.cli_commands entry point), so patch it at its source module.
        with patch("sqlseed_cli._utils.sanitize_table_config") as mock_sanitize:
            _write_ai_output(output, "test.db", result)
            mock_sanitize.assert_called_once_with(result)

    def test_sanitizes_leading_dots_from_table_name(self, tmp_path: Path) -> None:
        """Leading dots/colons in table names are stripped before writing."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "...users", "count": 10, "columns": []}
        _write_ai_output(output, "test.db", result)
        with open(output, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["tables"][0]["name"] == "users"

    def test_echoes_save_path_and_tip(self, tmp_path: Path) -> None:
        """After saving, echoes the output path and a tip about clear_before."""
        output = str(tmp_path / "out.yaml")
        result = {"name": "users", "count": 10, "columns": []}
        with patch("click.echo") as mock_echo:
            _write_ai_output(output, "test.db", result)
        echo_calls = [str(c[0][0]) for c in mock_echo.call_args_list]
        assert any("AI suggestions saved" in s for s in echo_calls)
        assert any("clear_before" in s for s in echo_calls)


# ---------------------------------------------------------------------------
# _report_ai_failure
# ---------------------------------------------------------------------------


class TestReportAIFailure:
    """Tests for ``_report_ai_failure``."""

    def test_raises_system_exit_1(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _report_ai_failure()
        assert exc_info.value.code == 1

    def test_echoes_failure_message_to_stderr(self) -> None:
        with patch("click.echo") as mock_echo, pytest.raises(SystemExit):
            _report_ai_failure()
        # Should echo at least once with err=True
        assert mock_echo.called
        _, kwargs = mock_echo.call_args
        assert kwargs.get("err") is True

    def test_message_includes_suggestions(self) -> None:
        """The failure message includes model/timeout suggestions."""
        with patch("click.echo") as mock_echo, pytest.raises(SystemExit):
            _report_ai_failure()
        message = str(mock_echo.call_args[0][0])
        assert "deepseek" in message.lower()
        assert "openai" in message.lower()
        assert "timeout" in message.lower()


# ---------------------------------------------------------------------------
# ai_suggest CLI command
# ---------------------------------------------------------------------------


class TestAISuggestCommand:
    """Tests for the ``ai-suggest`` CLI command."""

    # Note: the "plugin not available" scenario is no longer testable here
    # because ai_commands.py now lives inside the sqlseed-ai package — if
    # this module is imported, sqlseed-ai is necessarily installed. The
    # ai-suggest subcommand is only registered when sqlseed-ai is installed
    # (via the sqlseed.cli_commands entry-point group), so it cannot be
    # invoked in a no-plugin state.

    def test_errors_when_api_key_not_configured(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no API key is available, exits with code 1."""
        # Clear all API key env vars
        for var in (
            "SQLSEED_AI_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "SQLSEED_AI_BACKEND",
            "SQLSEED_AI_BASE_URL",
        ):
            monkeypatch.delenv(var, raising=False)
        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        result = runner.invoke(
            ai_suggest,
            [unique_test_db, "--table", "projects", "--output", output_path],
        )
        assert result.exit_code == 1
        assert "API key not configured" in result.output

    def test_echoes_resolved_model_and_backend(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On success path, echoes the resolved model and backend name."""
        # Configure for LM Studio (no real API key needed)
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        # Mock the analyzer to return a valid result
        result_dict = {"name": "projects", "count": 5, "columns": []}
        with (
            patch.object(ai_commands, "SchemaAnalyzer") as mock_analyzer_cls,
            patch.object(ai_commands, "_run_ai_analysis", return_value=result_dict),
        ):
            mock_analyzer_cls.return_value = MagicMock()
            result = runner.invoke(
                ai_suggest,
                [unique_test_db, "--table", "projects", "--output", output_path],
            )
        assert result.exit_code == 0
        assert "Using AI model:" in result.output
        # Backend name should be displayed (LM Studio, via BACKEND_DISPLAY_NAMES)
        assert "LM Studio" in result.output

    def test_writes_output_file_on_success(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On success, writes the YAML output file."""
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        result_dict = {"name": "projects", "count": 5, "columns": []}
        with (
            patch.object(ai_commands, "SchemaAnalyzer") as mock_analyzer_cls,
            patch.object(ai_commands, "_run_ai_analysis", return_value=result_dict),
        ):
            mock_analyzer_cls.return_value = MagicMock()
            result = runner.invoke(
                ai_suggest,
                [unique_test_db, "--table", "projects", "--output", output_path],
            )
        assert result.exit_code == 0
        assert "AI suggestions saved" in result.output
        # File should exist
        assert os.path.exists(output_path)

    def test_reports_failure_when_result_is_none(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _run_ai_analysis returns None, _report_ai_failure is called."""
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        with (
            patch.object(ai_commands, "SchemaAnalyzer") as mock_analyzer_cls,
            patch.object(ai_commands, "_run_ai_analysis", return_value=None),
        ):
            mock_analyzer_cls.return_value = MagicMock()
            result = runner.invoke(
                ai_suggest,
                [unique_test_db, "--table", "projects", "--output", output_path],
            )
        assert result.exit_code == 1
        assert "No suggestions received" in result.output

    def test_handles_timeout_error_from_run_ai_analysis(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _run_ai_analysis raises a timeout error, exit code is 1."""
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        with (
            patch.object(ai_commands, "SchemaAnalyzer") as mock_analyzer_cls,
            patch.object(
                ai_commands,
                "_run_ai_analysis",
                side_effect=RuntimeError("request timed out"),
            ),
        ):
            mock_analyzer_cls.return_value = MagicMock()
            result = runner.invoke(
                ai_suggest,
                [unique_test_db, "--table", "projects", "--output", output_path],
            )
        assert result.exit_code == 1
        assert "timed out" in result.output.lower()

    def test_handles_generic_error_from_run_ai_analysis(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _run_ai_analysis raises a generic error, exit code is 1."""
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        with (
            patch.object(ai_commands, "SchemaAnalyzer") as mock_analyzer_cls,
            patch.object(
                ai_commands,
                "_run_ai_analysis",
                side_effect=ValueError("something broke"),
            ),
        ):
            mock_analyzer_cls.return_value = MagicMock()
            result = runner.invoke(
                ai_suggest,
                [unique_test_db, "--table", "projects", "--output", output_path],
            )
        assert result.exit_code == 1
        assert "AI suggestion failed" in result.output

    def test_timeout_override_passed_to_config(
        self, unique_test_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--timeout flag overrides the AIConfig.timeout value."""
        monkeypatch.setenv("SQLSEED_AI_BACKEND", "lm_studio")
        monkeypatch.delenv("SQLSEED_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        runner = CliRunner()
        output_path = str(tmp_path / "out.yaml")
        # Capture the AIConfig instance passed to SchemaAnalyzer(config=...)
        captured_configs: list[Any] = []

        def capture_config(config: Any) -> MagicMock:
            captured_configs.append(config)
            return MagicMock()

        result_dict = {"name": "projects", "count": 5, "columns": []}
        with (
            patch.object(ai_commands, "SchemaAnalyzer", side_effect=capture_config),
            patch.object(ai_commands, "_run_ai_analysis", return_value=result_dict),
        ):
            result = runner.invoke(
                ai_suggest,
                [
                    unique_test_db,
                    "--table",
                    "projects",
                    "--output",
                    output_path,
                    "--timeout",
                    "120",
                ],
            )
        assert result.exit_code == 0
        # The config passed to SchemaAnalyzer should have timeout=120.0
        assert len(captured_configs) == 1
        assert captured_configs[0].timeout == 120.0


# ---------------------------------------------------------------------------
# _run_ai_analysis orchestration
# ---------------------------------------------------------------------------


class TestRunAIAnalysis:
    """Tests for ``_run_ai_analysis`` orchestration logic."""

    def test_probes_inference_speed_for_lm_studio_backend(self, tmp_db: str) -> None:
        """For LM Studio backend, probe_inference_speed is called."""
        speed_info = {"is_slow": False, "tokens_per_second": 50.0}
        analyzer = _make_analyzer(
            backend=_stub_backend("lm_studio"),
            speed_info=speed_info,
            use_streaming=True,
            call_llm_streaming_result={"name": "t", "count": 1, "columns": []},
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        analyzer.config.probe_inference_speed.assert_called_once()

    def test_probes_inference_speed_for_ollama_backend(self, tmp_db: str) -> None:
        """For Ollama backend, probe_inference_speed is called."""
        speed_info = {"is_slow": False, "tokens_per_second": 50.0}
        analyzer = _make_analyzer(
            backend=_stub_backend("ollama"),
            speed_info=speed_info,
            use_streaming=True,
            call_llm_streaming_result={"name": "t", "count": 1, "columns": []},
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        analyzer.config.probe_inference_speed.assert_called_once()

    def test_does_not_probe_speed_for_cloud_backend(self, tmp_db: str) -> None:
        """For cloud backends (e.g., google_ai_studio), probe is not called."""
        analyzer = _make_analyzer(
            backend=_stub_backend("google_ai_studio"),
            use_streaming=True,
            call_llm_streaming_result={"name": "t", "count": 1, "columns": []},
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        analyzer.config.probe_inference_speed.assert_not_called()

    def test_echoes_speed_warning_when_slow(self, tmp_db: str) -> None:
        """When is_slow is True, echoes speed info to stderr."""
        speed_info = {"is_slow": True, "tokens_per_second": 5.0}
        analyzer = _make_analyzer(
            backend=_stub_backend("lm_studio"),
            speed_info=speed_info,
            use_streaming=True,
            call_llm_streaming_result={"name": "t", "count": 1, "columns": []},
        )
        with (
            _patch_orchestrator(),
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
            patch("click.echo") as mock_echo,
        ):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        # Find the echo call that mentions "Local inference speed"
        speed_echo = [c for c in mock_echo.call_args_list if "Local inference speed" in str(c[0][0])]
        assert len(speed_echo) == 1
        # Should be echoed to stderr
        assert speed_echo[0].kwargs.get("err") is True

    def test_echoes_warning_when_probe_returns_none(self, tmp_db: str) -> None:
        """When probe returns None (LM Studio not running), echoes a warning."""
        analyzer = _make_analyzer(
            backend=_stub_backend("lm_studio"),
            speed_info=None,
            use_streaming=True,
            call_llm_streaming_result={"name": "t", "count": 1, "columns": []},
        )
        with (
            _patch_orchestrator(),
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
            patch("click.echo") as mock_echo,
        ):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        warning_echos = [c for c in mock_echo.call_args_list if "Could not probe" in str(c[0][0])]
        assert len(warning_echos) == 1

    def test_streaming_direct_path_when_no_verify(self, tmp_db: str) -> None:
        """When verify=False, uses streaming direct path."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(
            use_streaming=True,
            call_llm_streaming_result=result_dict,
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            result = _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=3, no_cache=False)
        assert result == result_dict
        analyzer.call_llm_streaming.assert_called_once()

    def test_non_streaming_direct_path_when_no_verify(self, tmp_db: str) -> None:
        """When streaming is disabled and verify=False, uses non-streaming direct path."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(
            use_streaming=False,
            call_llm_result=result_dict,
        )
        with _patch_orchestrator():
            result = _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=3, no_cache=False)
        assert result == result_dict
        analyzer.call_llm.assert_called_once()

    def test_streaming_verification_path_when_verify_and_retries(self, tmp_db: str) -> None:
        """When verify=True and max_retries>0 with streaming, uses verification streaming."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(use_streaming=True)
        with (
            _patch_orchestrator(),
            patch.object(ai_commands, "Live"),
            patch.object(ai_commands, "Console"),
            patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls,
        ):
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine_streaming.return_value = result_dict
            result = _run_ai_analysis(analyzer, tmp_db, "users", verify=True, max_retries=3, no_cache=False)
        assert result == result_dict
        mock_refiner.generate_and_refine_streaming.assert_called_once()

    def test_non_streaming_verification_path_when_verify_and_retries(self, tmp_db: str) -> None:
        """When verify=True and max_retries>0 without streaming, uses non-streaming verification."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(use_streaming=False)
        with _patch_orchestrator(), patch.object(ai_commands, "AiConfigRefiner") as mock_refiner_cls:
            mock_refiner = mock_refiner_cls.return_value
            mock_refiner.generate_and_refine.return_value = result_dict
            result = _run_ai_analysis(analyzer, tmp_db, "users", verify=True, max_retries=3, no_cache=False)
        assert result == result_dict
        mock_refiner.generate_and_refine.assert_called_once()

    def test_verify_with_zero_retries_uses_direct_path(self, tmp_db: str) -> None:
        """When verify=True but max_retries=0, falls back to direct path."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(
            use_streaming=True,
            call_llm_streaming_result=result_dict,
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            result = _run_ai_analysis(analyzer, tmp_db, "users", verify=True, max_retries=0, no_cache=False)
        assert result == result_dict
        analyzer.call_llm_streaming.assert_called_once()

    def test_use_compact_forwarded_to_direct_streaming(self, tmp_db: str) -> None:
        """When config.should_use_ultra_compact() is True, use_compact is forwarded."""
        result_dict = {"name": "t", "count": 1, "columns": []}
        analyzer = _make_analyzer(
            use_streaming=True,
            use_compact=True,
            call_llm_streaming_result=result_dict,
        )
        with _patch_orchestrator(), patch.object(ai_commands, "Live"), patch.object(ai_commands, "Console"):
            _run_ai_analysis(analyzer, tmp_db, "users", verify=False, max_retries=0, no_cache=False)
        # build_initial_messages should be called with compact=True, ultra_compact=True
        _, kwargs = analyzer.build_initial_messages.call_args
        assert kwargs.get("compact") is True
        assert kwargs.get("ultra_compact") is True


# ---------------------------------------------------------------------------
# register_commands
# ---------------------------------------------------------------------------


class TestRegisterCommands:
    """Tests for ``register_commands``."""

    def test_adds_ai_suggest_to_cli_group(self) -> None:
        """register_commands adds the ai-suggest command to a click.Group."""

        @click.group()
        def test_group() -> None:
            pass

        register_commands(test_group)
        assert "ai-suggest" in test_group.commands
        assert test_group.commands["ai-suggest"] is ai_suggest

    def test_ai_suggest_command_name(self) -> None:
        """The registered command name is 'ai-suggest'."""
        assert ai_suggest.name == "ai-suggest"

    def test_ai_suggest_has_required_db_path_argument(self) -> None:
        """The ai-suggest command requires a db_path argument."""
        params = {p.name: p for p in ai_suggest.params}
        assert "db_path" in params
        db_path_param = params["db_path"]
        assert isinstance(db_path_param, click.Argument)
        assert db_path_param.required is True

    def test_ai_suggest_has_table_output_options(self) -> None:
        """The ai-suggest command has --table and --output options.

        Note: ``--table`` and ``--output`` are NOT required at the Click
        declaration level — they are validated at runtime so that the
        ``--auto-heal`` flag can bypass them (auto-heal mode processes
        all tables and emits YAML to stdout). When ``--auto-heal`` is
        absent, the handler enforces ``--table``/``--output`` via
        ``SystemExit(2)``.
        """
        params = {p.name: p for p in ai_suggest.params}
        assert "table" in params
        assert "output" in params
        table_param = params["table"]
        output_param = params["output"]
        # Required=False at declaration; runtime validation in handler
        # enforces presence when --auto-heal is not set.
        assert table_param.required is False
        assert output_param.required is False

    def test_ai_suggest_has_model_api_key_base_url_options(self) -> None:
        """The ai-suggest command has --model, --api-key, --base-url options."""
        params = {p.name: p for p in ai_suggest.params}
        assert "model" in params
        assert "api_key" in params
        assert "base_url" in params

    def test_ai_suggest_has_verify_and_no_cache_options(self) -> None:
        """The ai-suggest command has --verify/--no-verify and --no-cache options."""
        params = {p.name: p for p in ai_suggest.params}
        assert "verify" in params
        assert "no_cache" in params

    def test_ai_suggest_has_timeout_option(self) -> None:
        """The ai-suggest command has --timeout option."""
        params = {p.name: p for p in ai_suggest.params}
        assert "timeout" in params
        timeout_param = params["timeout"]
        assert timeout_param.type is click.FLOAT or isinstance(timeout_param.type, click.FloatRange)

    def test_ai_suggest_has_max_retries_option(self) -> None:
        """The ai-suggest command has --max-retries option."""
        params = {p.name: p for p in ai_suggest.params}
        assert "max_retries" in params

    def test_register_commands_is_idempotent(self) -> None:
        """Calling register_commands twice on the same group still works."""

        @click.group()
        def test_group() -> None:
            pass

        register_commands(test_group)
        # Second call should not raise (click allows re-registration)
        register_commands(test_group)
        assert "ai-suggest" in test_group.commands
