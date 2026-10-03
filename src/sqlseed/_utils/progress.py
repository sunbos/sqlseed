"""Progress backend abstraction with Rich (terminal) and tqdm (notebook) implementations.

Selects the appropriate backend at runtime based on environment (Jupyter vs
terminal) and console encoding (UTF-8 vs GBK/Big5). When no rendering library
is installed, falls back to a silent ``NullProgressBackend``.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from abc import ABC, abstractmethod
from copy import copy
from functools import lru_cache
from importlib.util import find_spec
from typing import Any, Literal

from sqlseed._utils.logger import get_logger

try:
    from tqdm.auto import tqdm
except ImportError:
    tqdm = None

# rich is an optional dependency of sqlseed core (per ARCHITECTURE.md
# Section 7.1: "Core must not depend on click/rich for long-term
# stability"). When rich is absent, RichProgressBackend is unavailable
# and create_progress() falls back to NullProgressBackend in terminal
# environments. Install with: pip install sqlseed-cli (which pulls rich).
#
# Uses importlib.import_module() to avoid ruff's import-outside-toplevel
# warning (which would fire for ``from rich import ...`` inside a
# function) while keeping the import lazy at module load time. The
# ``_*_CLASS`` names hold either the rich class (when installed) or
# ``None`` (when absent), allowing runtime ``is None`` guards and
# instantiation in RichProgressBackend.__init__.
try:
    _GET_CONSOLE = importlib.import_module("rich").get_console
    _rich_progress_module = importlib.import_module("rich.progress")
    _PROGRESS_CLASS = _rich_progress_module.Progress
    _BAR_COLUMN_CLASS = _rich_progress_module.BarColumn
    _SPINNER_COLUMN_CLASS = _rich_progress_module.SpinnerColumn
    _TEXT_COLUMN_CLASS = _rich_progress_module.TextColumn
    _TIME_REMAINING_COLUMN_CLASS = _rich_progress_module.TimeRemainingColumn
    _TRANSFER_SPEED_COLUMN_CLASS = _rich_progress_module.TransferSpeedColumn
except ImportError:
    _GET_CONSOLE = None
    _PROGRESS_CLASS = None
    _BAR_COLUMN_CLASS = None
    _SPINNER_COLUMN_CLASS = None
    _TEXT_COLUMN_CLASS = None
    _TIME_REMAINING_COLUMN_CLASS = None
    _TRANSFER_SPEED_COLUMN_CLASS = None

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

RuntimeEnv = Literal["jupyter", "terminal"]


def _detect_environment() -> RuntimeEnv:
    """Detect the current runtime environment.

    Covers: IPython/Jupyter, Google Colab, Databricks, Kaggle, Papermill.
    Returns a deterministic literal for testability.
    """
    try:
        # get_ipython() is injected by IPython/Jupyter at runtime; it's not
        # available at type-check time. Use builtins lookup to avoid a
        # name-defined suppression directive.
        if (shell := getattr(builtins, "get_ipython", lambda: None)()) is None:
            return "terminal"
    except (ImportError, NameError):
        return "terminal"

    if _is_jupyter_shell(shell):
        return "jupyter"
    return "terminal"


def _is_jupyter_shell(shell: Any) -> bool:
    """Check if the IPython shell is a notebook kernel (Jupyter/Colab/Databricks).

    Detection covers:
    - ZMQInteractiveShell (standard Jupyter / JupyterLab / VS Code Jupyter)
    - google.colab module on the shell class (Google Colab)
    - DatabricksShell (Databricks notebook)
    - IPKernelApp in shell config (Kaggle, Papermill, etc.)
    """
    if (shell_class := type(shell).__name__) == "ZMQInteractiveShell":
        return True
    if "google.colab" in str(type(shell).__module__):
        return True
    if shell_class == "DatabricksShell":
        return True
    config = getattr(shell, "config", {})
    return "IPKernelApp" in config


def _can_render_unicode(*, encoding: str | None = None) -> bool:
    """Check whether the current output can encode Rich progress characters.

    Rich's default ``SpinnerColumn`` uses Braille patterns (e.g. ``⠋`` U+280B)
    and ``BarColumn`` uses block elements (``█`` U+2588, ``░`` U+2591).  On
    Windows consoles with GBK / GB2312 / Big5 encodings these characters cause
    ``UnicodeEncodeError``.  This helper probes the actual encoding so that
    rendering can fall back to an ASCII-safe layout. Do not cache the result:
    stdout may be redirected or its encoding reconfigured during a run.
    """
    try:
        encoding = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
        "\u280b\u2588\u2591".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class ProgressBackend(ABC):
    """Abstract interface for progress reporting.

    Implementations must be usable as context managers.
    """

    @abstractmethod
    def __enter__(self) -> ProgressBackend:
        """Enter the context manager and return self."""

    @abstractmethod
    def __exit__(self, *args: Any) -> None:
        """Exit the context manager, releasing any resources."""

    @abstractmethod
    def add_task(self, description: str, *, total: int | None = None) -> Any:
        """Register a new task and return its identifier."""

    @abstractmethod
    def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None:
        """Advance the task counter and/or update its description."""

    @abstractmethod
    def remove_task(self, task_id: Any) -> None:
        """Remove a previously added task from the backend."""


# ---------------------------------------------------------------------------
# Null backend (zero overhead when progress is disabled)
# ---------------------------------------------------------------------------

_NULL_TASK_ID = 0


class NullProgressBackend(ProgressBackend):
    """Silent no-op backend. Used when progress display is explicitly disabled.

    Avoids importing any rendering library — zero cost, zero side effects.
    """

    def __enter__(self) -> NullProgressBackend:
        """Enter the context manager (no-op)."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit the context manager (no-op)."""

    def add_task(self, description: str, *, total: int | None = None) -> int:
        """Add a task (no-op)."""
        return _NULL_TASK_ID

    def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None:
        """Update a task (no-op)."""

    def remove_task(self, task_id: Any) -> None:
        """Remove a task (no-op)."""


# ---------------------------------------------------------------------------
# Rich backend (terminal)
# ---------------------------------------------------------------------------


class _EncodingAwareColumn:
    """Select a real Rich column using the output encoding at render time."""

    def __init__(self, unicode_column: Any, ascii_column: Any, *, console: Any) -> None:
        self._unicode_column = unicode_column
        self._ascii_column = ascii_column
        self._console = console

    def _current_column(self) -> Any:
        if _can_render_unicode(encoding=self._console.encoding):
            return self._unicode_column
        return self._ascii_column

    def get_table_column(self) -> Any:
        """Use the selected column's layout, including an empty fallback bar."""
        column = self._current_column().get_table_column().copy()
        if not _can_render_unicode(encoding=self._console.encoding):
            # Rich's default truncation inserts a Unicode ellipsis, even
            # when the actual text and spinner are entirely ASCII.
            column.overflow = "crop"
        return column

    def __call__(self, task: Any) -> Any:
        """Render safely even when an existing progress changes output streams."""
        return self._current_column()(task)


class _EncodingAwareDescriptionColumn:
    """Escape unencodable display text without changing the original task."""

    def __init__(self, column: Any, *, console: Any) -> None:
        self._column = column
        self._console = console

    def get_table_column(self) -> Any:
        """Keep the description column's normal Rich layout."""
        return self._column.get_table_column()

    def __call__(self, task: Any) -> Any:
        """Use the current output encoding, including during exception cleanup."""
        description: str = task.description
        encoding = self._console.encoding
        try:
            safe_description = description.encode(encoding, errors="backslashreplace").decode(encoding)
        except (LookupError, TypeError):
            safe_description = description.encode("ascii", errors="backslashreplace").decode("ascii")
        if safe_description == description:
            return self._column(task)
        display_task = copy(task)
        display_task.description = safe_description
        return self._column(display_task)


class RichProgressBackend(ProgressBackend):
    """Rich Progress backend for terminal environments.

    Renders spinner, progress bar, percentage, speed, and ETA.

    When *ascii_only* is ``True`` the layout avoids Unicode characters
    (Braille spinners, block-element bars) that cannot be encoded by
    limited console encodings such as GBK or Big5.  The spinner falls back
    to the ``"line"`` style (``|/-\\``) and the graphical bar is omitted.
    Otherwise, columns follow the actual Rich console encoding on every render,
    including background refreshes and changes to an already-created backend.

    Raises:
        RuntimeError: If ``rich`` is not installed. Callers should use
            :func:`create_progress` (which never raises on missing deps)
            rather than instantiating this class directly.
    """

    def __init__(self, *, ascii_only: bool = False) -> None:
        """Initialize the Rich progress bar with appropriate columns.

        Args:
            ascii_only: If ``True``, use ASCII-safe spinner and omit the
                        graphical bar (for GBK/Big5 console encodings).

        Raises:
            RuntimeError: If ``rich`` is not installed.
        """
        # Grouped None guards (3 expressions each, under pylint's
        # too-many-boolean-expressions threshold of 5). Two groups cover all
        # six rich classes. Each ``if x is None: raise`` also narrows the type
        # for mypy, so the class variables are known to be non-None below.
        _not_installed = (
            "rich is not installed. Install with: pip install sqlseed-cli "
            "(or pip install rich). The sqlseed core package does not "
            "require rich; RichProgressBackend is only available when "
            "rich is installed."
        )
        if _PROGRESS_CLASS is None or _BAR_COLUMN_CLASS is None or _SPINNER_COLUMN_CLASS is None:
            raise RuntimeError(_not_installed)
        if _TEXT_COLUMN_CLASS is None or _TIME_REMAINING_COLUMN_CLASS is None or _TRANSFER_SPEED_COLUMN_CLASS is None:
            raise RuntimeError(_not_installed)
        if _GET_CONSOLE is None:
            raise RuntimeError(_not_installed)

        console = _GET_CONSOLE()
        description_column = _EncodingAwareDescriptionColumn(
            _TEXT_COLUMN_CLASS("[progress.description]{task.description}"), console=console
        )
        if ascii_only:
            columns: list[Any] = [
                _SPINNER_COLUMN_CLASS("line"),
                description_column,
                _TEXT_COLUMN_CLASS("[progress.percentage]{task.percentage:>3.0f}%"),
                _TEXT_COLUMN_CLASS("{task.completed}/{task.total}"),
                _TRANSFER_SPEED_COLUMN_CLASS(),
                _TIME_REMAINING_COLUMN_CLASS(),
            ]
        else:
            columns = [
                _EncodingAwareColumn(_SPINNER_COLUMN_CLASS(), _SPINNER_COLUMN_CLASS("line"), console=console),
                description_column,
                _EncodingAwareColumn(_BAR_COLUMN_CLASS(), _TEXT_COLUMN_CLASS(""), console=console),
                _TEXT_COLUMN_CLASS("[progress.percentage]{task.percentage:>3.0f}%"),
                _TEXT_COLUMN_CLASS("{task.completed}/{task.total}"),
                _TRANSFER_SPEED_COLUMN_CLASS(),
                _TIME_REMAINING_COLUMN_CLASS(),
            ]
        safe_columns = [
            column
            if isinstance(column, _EncodingAwareColumn)
            else _EncodingAwareColumn(column, column, console=console)
            for column in columns
        ]
        self._progress = _PROGRESS_CLASS(
            *safe_columns,
            console=console,
            transient=False,
            refresh_per_second=1,
        )

    def __enter__(self) -> RichProgressBackend:
        """Start the Rich progress display."""
        self._progress.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        """Stop the Rich progress display."""
        self._progress.__exit__(*args)

    def add_task(self, description: str, *, total: int | None = None) -> Any:
        """Add a new task to the Rich progress bar."""
        return self._progress.add_task(description, total=total)

    def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None:
        """Advance and/or update the description of a Rich task."""
        kwargs: dict[str, Any] = {"advance": advance}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(task_id, **kwargs)

    def remove_task(self, task_id: Any) -> None:
        """Remove a task from the Rich progress bar."""
        self._progress.remove_task(task_id)


# ---------------------------------------------------------------------------
# tqdm backend (Jupyter / notebook environments)
# ---------------------------------------------------------------------------


class TqdmNotebookBackend(ProgressBackend):
    """tqdm.auto backend for Jupyter environments.

    Design decisions:
    - Uses ``tqdm.auto`` (not ``tqdm.notebook``) for VS Code Jupyter compatibility.
    - Indeterminate tasks (``total=None``) are silently disabled to avoid
      rendering meaningless ``0it [00:00, ?it/s]`` lines.
    - Bars are created lazily on first ``update()`` to prevent the initial
      ``0%`` frame from appearing as a separate line in Jupyter text mode.
    - ``__exit__`` calls ``refresh() + close()`` to ensure the final 100% state
      is captured before the widget is torn down.
    """

    def __init__(self) -> None:
        """Initialize internal tracking state (no bars created yet)."""
        self._bars: dict[int, Any] = {}
        self._pending: dict[int, tuple[str, int | None]] = {}
        self._counter = 0

    def __enter__(self) -> TqdmNotebookBackend:
        """Enter the context manager (bars are created lazily on update)."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Refresh and close all tqdm bars, then clear internal state."""
        for pbar in self._bars.values():
            pbar.refresh()
            pbar.close()
        self._bars.clear()
        self._pending.clear()

    def _ensure_bar(self, task_id: int) -> Any:
        """Lazily create the tqdm bar for *task_id* on first access.

        Returns ``None`` if the task is indeterminate (``total=None``) or
        if tqdm is not installed.
        """
        if task_id in self._bars:
            return self._bars[task_id]
        if task_id not in self._pending:
            return None

        description, total = self._pending.pop(task_id)
        if tqdm is None:
            return None
        pbar = tqdm(
            total=total,
            desc=description,
            leave=total is not None,
            disable=total is None,
        )
        self._bars[task_id] = pbar
        return pbar

    def add_task(self, description: str, *, total: int | None = None) -> int:
        """Register a task; the tqdm bar is created lazily on first update."""
        task_id = self._counter
        self._counter += 1
        if total is None:
            return task_id
        self._pending[task_id] = (description, total)
        return task_id

    def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None:
        """Advance and/or update the description of a tqdm task."""
        if (pbar := self._ensure_bar(task_id)) is None:
            return
        if description is not None:
            pbar.set_description(description)
        if advance > 0:
            pbar.update(advance)

    def remove_task(self, task_id: Any) -> None:
        """Close and remove the tqdm bar associated with *task_id*."""
        self._pending.pop(task_id, None)
        if (pbar := self._bars.pop(task_id, None)) is not None:
            pbar.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _check_tqdm() -> bool:
    """Lazy-check tqdm availability (cached)."""
    return find_spec("tqdm") is not None


def create_progress(*, disable: bool = False) -> ProgressBackend:
    """Create the appropriate progress backend for the current environment.

    Selection logic::

        disable=True  → NullProgressBackend     (zero-cost no-op)
        Jupyter+tqdm  → TqdmNotebookBackend     (native notebook widget)
        Jupyter-tqdm  → NullProgressBackend      (graceful degradation)
        Terminal+UTF8 → RichProgressBackend      (rich spinner + bar)
        Terminal+GBK  → RichProgressBackend      (ASCII spinner, no bar)

    The Jupyter-without-tqdm path logs a one-time warning instead of raising
    ImportError, because progress display is a UX nicety, not a correctness
    requirement.

    When the console encoding cannot represent the Unicode characters used by
    Rich's default spinner (Braille patterns) and bar (block elements), the
    factory automatically switches to an ASCII-safe layout so that Windows
    consoles with GBK / Big5 encodings do not crash with ``UnicodeEncodeError``.
    The layout is checked again at render time so that redirected output does
    not inherit the encoding decision of an earlier console.
    """
    if disable:
        return NullProgressBackend()

    if (_detect_environment()) == "jupyter":
        if _check_tqdm():
            return TqdmNotebookBackend()
        logger.warning(
            "tqdm is not installed — progress bars disabled in Jupyter. Install with: pip install sqlseed[notebook]"
        )
        return NullProgressBackend()

    if not _can_render_unicode():
        logger.debug("Console encoding does not support Unicode progress characters — using ASCII-safe layout")

    if _PROGRESS_CLASS is None:
        # rich is not installed — fall back to silent null backend rather
        # than crashing. This keeps the sqlseed core importable without
        # rich (per ARCHITECTURE.md Section 7.1). Users who want progress
        # bars should install sqlseed-cli (which pulls rich).
        logger.debug("rich not installed — progress bars disabled. Install with: pip install sqlseed-cli")
        return NullProgressBackend()

    return RichProgressBackend()
