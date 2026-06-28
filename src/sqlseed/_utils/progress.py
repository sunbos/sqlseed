from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from functools import lru_cache
from importlib.util import find_spec
from typing import Any, Literal

try:
    from tqdm.auto import tqdm
except ImportError:
    tqdm = None

try:
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
except ImportError:
    # rich is an optional dependency of sqlseed core (per ARCHITECTURE.md
    # Section 7.1: "Core must not depend on click/rich for long-term
    # stability"). When rich is absent, RichProgressBackend is unavailable
    # and create_progress() falls back to NullProgressBackend in terminal
    # environments. Install with: pip install sqlseed-cli (which pulls rich).
    Progress = None  # type: ignore[assignment,misc]
    BarColumn = Progress  # type: ignore[assignment,misc]
    SpinnerColumn = Progress  # type: ignore[assignment,misc]
    TextColumn = Progress  # type: ignore[assignment,misc]
    TimeRemainingColumn = Progress  # type: ignore[assignment,misc]
    TransferSpeedColumn = Progress  # type: ignore[assignment,misc]

from sqlseed._utils.logger import get_logger

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
        shell = get_ipython()  # type: ignore[name-defined]
    except NameError:
        return "terminal"

    # IPython exists — check if it's a kernel (notebook) vs interactive shell
    shell_class = type(shell).__name__

    # ZMQInteractiveShell → standard Jupyter / JupyterLab / VS Code Jupyter
    if shell_class == "ZMQInteractiveShell":
        return "jupyter"

    # Google Colab uses its own shell class
    if "google.colab" in str(type(shell).__module__):
        return "jupyter"

    # Databricks notebook
    if shell_class == "DatabricksShell":
        return "jupyter"

    # Fallback: check config for IPKernelApp (catches Kaggle, Papermill, etc.)
    config = getattr(shell, "config", {})
    if "IPKernelApp" in config:
        return "jupyter"

    return "terminal"


@lru_cache(maxsize=1)
def _can_render_unicode() -> bool:
    """Check whether stdout can encode characters used by Rich progress bars.

    Rich's default ``SpinnerColumn`` uses Braille patterns (e.g. ``⠋`` U+280B)
    and ``BarColumn`` uses block elements (``█`` U+2588, ``░`` U+2591).  On
    Windows consoles with GBK / GB2312 / Big5 encodings these characters cause
    ``UnicodeEncodeError``.  This helper probes the actual encoding so that
    ``create_progress()`` can fall back to an ASCII-safe layout.
    """
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
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
    def __enter__(self) -> ProgressBackend: ...

    @abstractmethod
    def __exit__(self, *args: Any) -> None: ...

    @abstractmethod
    def add_task(self, description: str, *, total: int | None = None) -> Any: ...

    @abstractmethod
    def update(self, task_id: Any, *, advance: int = 0, description: str | None = None) -> None: ...

    @abstractmethod
    def remove_task(self, task_id: Any) -> None: ...


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


class RichProgressBackend(ProgressBackend):
    """Rich Progress backend for terminal environments.

    Renders spinner, progress bar, percentage, speed, and ETA.

    When *ascii_only* is ``True`` the layout avoids Unicode characters
    (Braille spinners, block-element bars) that cannot be encoded by
    limited console encodings such as GBK or Big5.  The spinner falls back
    to the ``"line"`` style (``|/-\\``) and the graphical bar is omitted.

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
        if Progress is None:
            raise RuntimeError(
                "rich is not installed. Install with: pip install sqlseed-cli "
                "(or pip install rich). The sqlseed core package does not "
                "require rich; RichProgressBackend is only available when "
                "rich is installed."
            )

        if ascii_only:
            columns: list[Any] = [
                SpinnerColumn("line"),
                TextColumn("[progress.description]{task.description}"),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("{task.completed}/{task.total}"),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ]
        else:
            columns = [
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("{task.completed}/{task.total}"),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ]
        self._progress = Progress(
            *columns,
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
        pbar = self._ensure_bar(task_id)
        if pbar is None:
            return
        if description is not None:
            pbar.set_description(description)
        if advance > 0:
            pbar.update(advance)

    def remove_task(self, task_id: Any) -> None:
        """Close and remove the tqdm bar associated with *task_id*."""
        self._pending.pop(task_id, None)
        pbar = self._bars.pop(task_id, None)
        if pbar is not None:
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
        Terminal+GBK  → RichProgressBackend(ascii_only=True)  (ASCII spinner, no bar)

    The Jupyter-without-tqdm path logs a one-time warning instead of raising
    ImportError, because progress display is a UX nicety, not a correctness
    requirement.

    When the console encoding cannot represent the Unicode characters used by
    Rich's default spinner (Braille patterns) and bar (block elements), the
    factory automatically switches to an ASCII-safe layout so that Windows
    consoles with GBK / Big5 encodings do not crash with ``UnicodeEncodeError``.
    """
    if disable:
        return NullProgressBackend()

    env = _detect_environment()

    if env == "jupyter":
        if _check_tqdm():
            return TqdmNotebookBackend()
        logger.warning(
            "tqdm is not installed — progress bars disabled in Jupyter. Install with: pip install sqlseed[notebook]"
        )
        return NullProgressBackend()

    ascii_only = not _can_render_unicode()
    if ascii_only:
        logger.debug("Console encoding does not support Unicode progress characters — using ASCII-safe layout")

    if Progress is None:
        # rich is not installed — fall back to silent null backend rather
        # than crashing. This keeps the sqlseed core importable without
        # rich (per ARCHITECTURE.md Section 7.1). Users who want progress
        # bars should install sqlseed-cli (which pulls rich).
        logger.debug("rich not installed — progress bars disabled. Install with: pip install sqlseed-cli")
        return NullProgressBackend()

    return RichProgressBackend(ascii_only=ascii_only)
