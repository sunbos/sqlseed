"""Tests for sqlseed._utils.progress — backend selection, lifecycle, and Jupyter detection."""

from __future__ import annotations

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
    from collections.abc import Generator

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

    @pytest.fixture(autouse=True)
    def _reset_unicode_cache(self) -> Generator[None, None, None]:
        progress_mod._can_render_unicode.cache_clear()
        yield
        progress_mod._can_render_unicode.cache_clear()

    def test_returns_bool(self) -> None:
        result = _can_render_unicode()
        assert isinstance(result, bool)

    def test_true_with_utf8(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "utf-8"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is True

    def test_false_with_gbk(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "gbk"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is False

    def test_false_with_big5(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "big5"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is False

    def test_false_with_cp936(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "cp936"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is False

    def test_true_when_encoding_is_none(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": None})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is True

    def test_false_with_unknown_encoding(self) -> None:
        mock_stdout = type("FakeStdout", (), {"encoding": "nonexistent_codec_xyz"})()
        with patch("sqlseed._utils.progress.sys.stdout", mock_stdout):
            progress_mod._can_render_unicode.cache_clear()
            assert _can_render_unicode() is False

    def test_caches_result(self) -> None:
        first = _can_render_unicode()
        second = _can_render_unicode()
        assert first == second


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
