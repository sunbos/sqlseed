"""Tests for sqlseed._utils.progress — backend selection, lifecycle, and Jupyter detection."""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

import sqlseed._utils.progress as progress_mod
from sqlseed._utils.progress import (
    NullProgressBackend,
    ProgressBackend,
    RichProgressBackend,
    TqdmNotebookBackend,
    _can_render_unicode,
    _check_tqdm,
    _detect_environment,
    create_progress,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


@contextmanager
def _redirectable_output(
    encoding: str,
) -> Generator[tuple[io.TextIOWrapper, io.TextIOWrapper, pytest.MonkeyPatch], None, None]:
    """Restore stdout before closing either strict stream, including on failure."""
    with (
        io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True) as utf8,
        io.TextIOWrapper(io.BytesIO(), encoding=encoding, write_through=True) as limited,
        pytest.MonkeyPatch.context() as patcher,
    ):
        patcher.setattr(sys, "stdout", utf8)
        yield utf8, limited, patcher


def _fail_generation(
    backend: RichProgressBackend, error: ValueError, before_failure: Callable[[RichProgressBackend], None]
) -> None:
    """Exercise the backend's exception cleanup with a known business error."""
    with backend:
        before_failure(backend)
        raise error


# ---------------------------------------------------------------------------
# _detect_environment
# ---------------------------------------------------------------------------


class TestDetectEnvironment:
    """Tests for runtime environment detection."""

    def test_terminal_when_no_ipython(self) -> None:
        """Standard Python interpreter → terminal."""
        with patch("builtins.get_ipython", side_effect=NameError, create=True):
            assert _detect_environment() == "terminal"

    def test_jupyter_zmq_shell(self) -> None:
        """Standard Jupyter / JupyterLab / VS Code Jupyter."""
        zmq_cls = type("ZMQInteractiveShell", (), {"config": {}})
        mock_shell = zmq_cls()
        with patch("builtins.get_ipython", return_value=mock_shell, create=True):
            assert _detect_environment() == "jupyter"

    def test_jupyter_colab(self) -> None:
        """Google Colab notebook."""
        colab_cls = type("Shell", (), {"__module__": "google.colab._shell", "config": {}})
        mock_shell = colab_cls()
        with patch("builtins.get_ipython", return_value=mock_shell, create=True):
            assert _detect_environment() == "jupyter"

    def test_jupyter_databricks(self) -> None:
        """Databricks notebook."""
        db_cls = type("DatabricksShell", (), {"config": {}})
        mock_shell = db_cls()
        with patch("builtins.get_ipython", return_value=mock_shell, create=True):
            assert _detect_environment() == "jupyter"

    def test_jupyter_ipkernel_fallback(self) -> None:
        """Kaggle / Papermill / other IPKernel-based environments."""
        custom_cls = type("SomeCustomShell", (), {"__module__": "some_module", "config": {"IPKernelApp": {}}})
        mock_shell = custom_cls()
        with patch("builtins.get_ipython", return_value=mock_shell, create=True):
            assert _detect_environment() == "jupyter"

    def test_terminal_ipython_interactive(self) -> None:
        """Plain IPython interactive shell (not a notebook)."""
        term_cls = type("TerminalInteractiveShell", (), {"__module__": "IPython.terminal", "config": {}})
        mock_shell = term_cls()
        with patch("builtins.get_ipython", return_value=mock_shell, create=True):
            assert _detect_environment() == "terminal"


# ---------------------------------------------------------------------------
# NullProgressBackend
# ---------------------------------------------------------------------------


class TestNullProgressBackend:
    """NullProgressBackend should be a zero-cost no-op."""

    def test_context_manager(self) -> None:
        backend = NullProgressBackend()
        with backend as b:
            assert b is backend

    def test_add_task_returns_int(self) -> None:
        with NullProgressBackend() as b:
            tid = b.add_task("test", total=100)
            assert isinstance(tid, int)

    def test_update_and_remove_are_silent(self) -> None:
        with NullProgressBackend() as b:
            tid = b.add_task("test", total=100)
            b.update(tid, advance=50)
            b.update(tid, advance=50, description="done")
            b.remove_task(tid)
            # No exception — success

    def test_is_progress_backend(self) -> None:
        assert isinstance(NullProgressBackend(), ProgressBackend)


# ---------------------------------------------------------------------------
# RichProgressBackend
# ---------------------------------------------------------------------------


class TestRichProgressBackend:
    """RichProgressBackend wraps Rich Progress for terminal use."""

    @pytest.mark.parametrize("ascii_only", [False, True], ids=["unicode", "ascii"])
    def test_context_manager_lifecycle(self, ascii_only: bool) -> None:
        backend = RichProgressBackend(ascii_only=ascii_only)
        with backend as b:
            assert isinstance(b, RichProgressBackend)

    @pytest.mark.parametrize("ascii_only", [False, True], ids=["unicode", "ascii"])
    def test_full_lifecycle(self, ascii_only: bool) -> None:
        with RichProgressBackend(ascii_only=ascii_only) as b:
            prep = b.add_task("Preparing...", total=None)
            b.update(prep, description="Resolving schema...")
            b.remove_task(prep)

            gen = b.add_task("Generating", total=100)
            for _ in range(10):
                b.update(gen, advance=10)

    @pytest.mark.parametrize("ascii_only", [False, True], ids=["unicode", "ascii"])
    def test_is_progress_backend(self, ascii_only: bool) -> None:
        assert isinstance(RichProgressBackend(ascii_only=ascii_only), ProgressBackend)

    def test_default_is_unicode_mode(self) -> None:
        backend = RichProgressBackend()
        assert isinstance(backend, RichProgressBackend)

    def test_missing_console_factory_reports_optional_dependency(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report the optional Rich dependency when its console entry point is unavailable."""
        monkeypatch.setattr(progress_mod, "_GET_CONSOLE", None)
        with pytest.raises(RuntimeError, match="rich is not installed"):
            RichProgressBackend()

    def test_module_remains_usable_when_rich_cannot_be_imported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep task lifecycle operations usable after the optional Rich import fails."""
        original_import = progress_mod.importlib.import_module

        def without_rich(name: str, package: str | None = None) -> object:
            """Emulate the missing optional package at the import boundary only."""
            if name == "rich" or name.startswith("rich."):
                raise ImportError("optional rich package is absent")
            return original_import(name, package)

        monkeypatch.setattr(progress_mod.importlib, "import_module", without_rich)
        spec = importlib.util.spec_from_file_location("progress_without_rich", progress_mod.__file__)
        assert spec is not None
        assert spec.loader is not None
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        with isolated.create_progress() as backend:
            assert isinstance(backend, isolated.NullProgressBackend)
            task = backend.add_task("Generate without Rich", total=2)
            backend.update(task, advance=2)
            backend.remove_task(task)
        with pytest.raises(RuntimeError, match="rich is not installed"):
            isolated.RichProgressBackend()


# ---------------------------------------------------------------------------
# TqdmNotebookBackend
# ---------------------------------------------------------------------------


class TestTqdmNotebookBackend:
    """TqdmNotebookBackend uses tqdm.auto for Jupyter environments."""

    def test_context_manager(self) -> None:
        pytest.importorskip("tqdm")
        backend = TqdmNotebookBackend()
        with backend as b:
            assert b is backend

    def test_full_lifecycle(self) -> None:
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("Generating test", total=50)
            for _ in range(5):
                b.update(tid, advance=10)

    def test_indeterminate_task_no_bar(self) -> None:
        """Tasks with total=None should not create a bar."""
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("Preparing...", total=None)
            assert tid not in b._bars
            assert tid not in b._pending

    def test_determinate_task_pending_until_update(self) -> None:
        """Tasks with a total should be pending until first update."""
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("Generating", total=100)
            assert tid not in b._bars
            assert tid in b._pending
            b.update(tid, advance=10)
            assert tid in b._bars
            assert tid not in b._pending

    def test_remove_task_closes_bar(self) -> None:
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("test", total=10)
            b.update(tid, advance=1)
            b.remove_task(tid)
            assert tid not in b._bars

    def test_remove_pending_task(self) -> None:
        """Removing a task before its bar is created should clear the pending entry."""
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("test", total=10)
            assert tid in b._pending
            b.remove_task(tid)
            assert tid not in b._pending
            assert tid not in b._bars

    def test_update_nonexistent_task_is_noop(self) -> None:
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            b.update(999, advance=10)  # should not raise

    def test_description_update(self) -> None:
        pytest.importorskip("tqdm")
        with TqdmNotebookBackend() as b:
            tid = b.add_task("phase 1", total=10)
            b.update(tid, advance=1, description="phase 2")
            assert b._bars[tid].desc.startswith("phase 2")

    def test_exit_clears_bars(self) -> None:
        pytest.importorskip("tqdm")
        backend = TqdmNotebookBackend()
        with backend:
            backend.add_task("a", total=10)
            backend.add_task("b", total=20)
        assert len(backend._bars) == 0
        assert len(backend._pending) == 0

    def test_is_progress_backend(self) -> None:
        assert isinstance(TqdmNotebookBackend(), ProgressBackend)


# ---------------------------------------------------------------------------
# create_progress factory
# ---------------------------------------------------------------------------


class TestCreateProgress:
    """Test the factory function's backend selection logic."""

    def test_disabled_returns_null(self) -> None:
        result = create_progress(disable=True)
        assert isinstance(result, NullProgressBackend)

    def test_terminal_returns_rich(self) -> None:
        with patch("sqlseed._utils.progress._detect_environment", return_value="terminal"):
            result = create_progress()
            assert isinstance(result, RichProgressBackend)

    def test_jupyter_with_tqdm_returns_tqdm(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="jupyter"),
            patch("sqlseed._utils.progress._check_tqdm", return_value=True),
        ):
            result = create_progress()
            assert isinstance(result, TqdmNotebookBackend)

    def test_jupyter_without_tqdm_returns_null(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="jupyter"),
            patch("sqlseed._utils.progress._check_tqdm", return_value=False),
        ):
            result = create_progress()
            assert isinstance(result, NullProgressBackend)

    def test_jupyter_without_tqdm_logs_warning(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="jupyter"),
            patch("sqlseed._utils.progress._check_tqdm", return_value=False),
            patch("sqlseed._utils.progress.logger") as mock_logger,
        ):
            create_progress()
            mock_logger.warning.assert_called_once()
            assert "tqdm" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# _check_tqdm caching
# ---------------------------------------------------------------------------


class TestCheckTqdm:
    """_check_tqdm should cache its result after the first call."""

    @pytest.fixture(autouse=True)
    def _reset_tqdm_cache(self) -> Generator[None, None, None]:
        """Reset tqdm check cache before and after each test."""
        progress_mod._check_tqdm.cache_clear()
        yield
        progress_mod._check_tqdm.cache_clear()

    def test_returns_bool(self) -> None:
        result = _check_tqdm()
        assert isinstance(result, bool)

    def test_caches_result(self) -> None:
        first = _check_tqdm()
        second = _check_tqdm()
        assert first == second

    def test_true_when_tqdm_available(self) -> None:
        pytest.importorskip("tqdm")
        result = _check_tqdm()
        assert result is True


# ---------------------------------------------------------------------------
# _can_render_unicode
# ---------------------------------------------------------------------------


class TestCanRenderUnicode:
    """_can_render_unicode probes whether stdout can encode Rich's Unicode chars."""

    def test_returns_bool(self) -> None:
        result = _can_render_unicode()
        assert isinstance(result, bool)

    def test_true_with_utf8(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "utf-8"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is True

    def test_false_with_gbk(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "gbk"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is False

    def test_false_with_big5(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "big5"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is False

    def test_false_with_cp936(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "cp936"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is False

    def test_true_when_encoding_is_none(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": None})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is True

    def test_false_with_unknown_encoding(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "nonexistent_codec_xyz"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            assert _can_render_unicode() is False

    def test_follows_reconfigured_encoding(self) -> None:
        """Reevaluate support after the same stdout object changes its encoding."""
        with (
            io.TextIOWrapper(io.BytesIO(), encoding="utf-8") as stdout,
            patch.object(sys, "stdout", stdout),
        ):
            assert _can_render_unicode() is True
            stdout.reconfigure(encoding="gbk")
            assert _can_render_unicode() is False
            stdout.reconfigure(encoding="utf-8")
            assert _can_render_unicode() is True


# ---------------------------------------------------------------------------
# create_progress with Unicode fallback
# ---------------------------------------------------------------------------


class TestCreateProgressUnicodeFallback:
    """create_progress falls back to ASCII-safe layout when encoding is limited."""

    def test_terminal_gbk_returns_ascii_rich(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="terminal"),
            patch("sqlseed._utils.progress._can_render_unicode", return_value=False),
        ):
            result = create_progress()
            assert isinstance(result, RichProgressBackend)

    def test_terminal_utf8_returns_unicode_rich(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="terminal"),
            patch("sqlseed._utils.progress._can_render_unicode", return_value=True),
        ):
            result = create_progress()
            assert isinstance(result, RichProgressBackend)

    def test_gbk_logs_debug_message(self) -> None:
        with (
            patch("sqlseed._utils.progress._detect_environment", return_value="terminal"),
            patch("sqlseed._utils.progress._can_render_unicode", return_value=False),
            patch("sqlseed._utils.progress.logger") as mock_logger,
        ):
            create_progress()
            mock_logger.debug.assert_called_once()
            assert "ASCII" in mock_logger.debug.call_args[0][0]


class TestRichOutputEncodingChanges:
    """Exercise actual Rich rendering through strict encoding streams."""

    @pytest.fixture(autouse=True)
    def _terminal_console(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Isolate a real terminal console that follows redirected stdout."""
        rich = pytest.importorskip("rich")
        console_module = pytest.importorskip("rich.console")
        monkeypatch.setenv("TERM", "xterm")
        # Keep Rich's real cached console, whose output follows sys.stdout.
        monkeypatch.setattr(
            rich,
            "_console",
            console_module.Console(force_terminal=True, color_system=None, legacy_windows=False, width=120),
        )

    @pytest.mark.parametrize("encoding", ["gbk", "big5", "cp936", "ascii"])
    def test_new_progress_after_stdout_redirect(self, encoding: str) -> None:
        """Create a fresh progress display safely after switching from UTF-8 to a strict stream."""
        with _redirectable_output(encoding) as (utf8, limited, patcher):
            with create_progress() as backend:
                backend.add_task("Before redirect", total=2)
            assert any("\u2800" <= char <= "\u28ff" for char in utf8.buffer.getvalue().decode("utf-8"))

            patcher.setattr(sys, "stdout", limited)
            with create_progress() as backend:
                task = backend.add_task("After redirect", total=2)
                backend.update(task, advance=1)
            output = limited.buffer.getvalue().decode(encoding)
            assert "After redirect" in output
            assert "1/2" in output
            assert output.isascii()

    @pytest.mark.parametrize("encoding", ["gbk", "big5", "ascii"])
    def test_existing_progress_follows_output_encoding(self, encoding: str) -> None:
        """Retain task counts while an active display switches between strict and Unicode streams."""
        with _redirectable_output(encoding) as (utf8, limited, patcher):
            backend = create_progress()
            assert isinstance(backend, RichProgressBackend)
            backend._progress.live.auto_refresh = False
            # The object is created under UTF-8 but entered after redirection.
            patcher.setattr(sys, "stdout", limited)
            with backend:
                task = backend.add_task("Changing encoding", total=4)
                backend.update(task, advance=1)
                backend._progress.refresh()
                limited_output = limited.buffer.getvalue().decode(encoding)
                assert "1/4" in limited_output
                assert limited_output.isascii()

                patcher.setattr(sys, "stdout", utf8)
                backend.update(task, advance=1)
                backend._progress.refresh()
                utf8_output = utf8.buffer.getvalue().decode("utf-8")
                assert "2/4" in utf8_output
                assert any("\u2800" <= char <= "\u28ff" for char in utf8_output)

                patcher.setattr(sys, "stdout", limited)
                backend.update(task, advance=1)
                backend._progress.refresh()
            assert "3/4" in limited.buffer.getvalue().decode(encoding)

    def test_reconfigured_console_file_uses_actual_encoding(self) -> None:
        """Follow a file whose codec changes without replacing the stream object."""
        import rich

        with _redirectable_output("utf-8") as (_, output, _patcher):
            rich.get_console().file = output
            backend = create_progress()
            assert isinstance(backend, RichProgressBackend)
            backend._progress.live.auto_refresh = False
            with backend:
                task = backend.add_task("Reconfigured file", total=4)
                backend.update(task, advance=1)
                backend._progress.refresh()
                first_end = len(output.buffer.getvalue())
                output.reconfigure(encoding="gbk")
                backend.update(task, advance=1)
                backend._progress.refresh()
            gbk_output = output.buffer.getvalue()[first_end:].decode("gbk")
            assert "2/4" in gbk_output
            assert gbk_output.isascii()

    def test_unknown_output_codec_escapes_description_without_changing_task(self) -> None:
        """Render ASCII escapes when codec lookup fails while retaining the original task text."""
        import rich

        class StrictOutput(io.StringIO):
            @property
            def encoding(self) -> str:
                """Expose an invalid codec name while the underlying sink remains strict ASCII."""
                return "sqlseed-unknown-test-codec"

            def write(self, text: str) -> int:
                """Reject any Unicode characters that escape the progress fallback."""
                text.encode("ascii", errors="strict")
                return super().write(text)

        with StrictOutput() as output:
            rich.get_console().file = output
            with RichProgressBackend() as backend:
                task = backend.add_task("Generating 用户🚀", total=2)
                backend.update(task, advance=1)
                backend._progress.refresh()
                assert backend._progress.tasks[0].description == "Generating 用户🚀"
            assert r"Generating \u7528\u6237\U0001f680" in output.getvalue()
            assert "1/2" in output.getvalue()
            assert output.getvalue().isascii()

    @pytest.mark.parametrize("ascii_only", [False, True])
    @pytest.mark.parametrize(
        ("encoding", "expected"),
        [
            ("ascii", r"\u7528\u6237\U0001f680"),
            ("gbk", "用户" + r"\U0001f680"),
            ("big5", "用" + r"\u6237\U0001f680"),
            ("utf-8", "用户🚀"),
        ],
    )
    def test_description_escapes_only_unencodable_text(self, encoding: str, expected: str, ascii_only: bool) -> None:
        """Preserve encodable text and the original task description in both layout modes."""
        with (
            io.TextIOWrapper(io.BytesIO(), encoding=encoding, write_through=True) as output,
            patch.object(sys, "stdout", output),
            RichProgressBackend(ascii_only=ascii_only) as backend,
        ):
            task = backend.add_task("Generating 用户🚀", total=2)
            backend.update(task, advance=1)
            backend._progress.refresh()
            assert "Generating " + expected in output.buffer.getvalue().decode(encoding)
            assert backend._progress.tasks[0].description == "Generating 用户🚀"

    @pytest.mark.parametrize("encoding", ["ascii", "gbk", "big5"])
    def test_unencodable_description_preserves_original_business_exception(self, encoding: str) -> None:
        """Keep the original generation error when cleanup renders to a newly restricted stream."""
        import rich

        original = ValueError("generation failed")
        with _redirectable_output(encoding) as (_, limited, _patcher):
            backend = create_progress()
            assert isinstance(backend, RichProgressBackend)
            backend._progress.live.auto_refresh = False

            def redirect_before_failure(active: RichProgressBackend) -> None:
                """Change the active output only after the Unicode task has been created."""
                active.add_task("Generating 用户🚀", total=2)
                rich.get_console().file = limited

            with pytest.raises(ValueError) as caught:
                _fail_generation(backend, original, redirect_before_failure)
            assert caught.value is original
            assert "Generating" in limited.buffer.getvalue().decode(encoding)

    @pytest.mark.parametrize("width", [8, 20])
    def test_narrow_ascii_console_does_not_add_unicode_ellipsis(self, width: int) -> None:
        """Keep narrow layout truncation from replacing the original business error."""
        import rich

        rich.get_console().width = width
        original = ValueError("generation failed")
        with (
            io.TextIOWrapper(io.BytesIO(), encoding="ascii", write_through=True) as output,
            patch.object(sys, "stdout", output),
        ):
            backend = create_progress()
            assert isinstance(backend, RichProgressBackend)
            backend._progress.live.auto_refresh = False

            def long_description_before_failure(active: RichProgressBackend) -> None:
                """Force description cropping before the simulated generation failure."""
                task = active.add_task("initial", total=20)
                active.update(task, description="Generating 用户🚀" * 10)

            with pytest.raises(ValueError) as caught:
                _fail_generation(backend, original, long_description_before_failure)
            assert caught.value is original
            rendered = output.buffer.getvalue().decode("ascii")
            assert rendered
            assert rendered.isascii()
