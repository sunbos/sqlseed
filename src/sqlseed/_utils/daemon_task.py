"""Future-backed daemon work that does not hold the interpreter open."""

from __future__ import annotations

from concurrent.futures import Future
from threading import Thread
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

_T = TypeVar("_T")


class DaemonTask(Future[_T]):
    """Own one daemon thread and publish its result through the Future protocol.

    A timeout only stops waiting; Python cannot terminate a running thread.
    Unlike ThreadPoolExecutor, this task never waits during interpreter exit.
    Exceptions, including process-control exceptions, are delivered to the
    caller of ``result()`` instead of leaving an apparently successful task.
    """

    def __init__(
        self,
        target: Callable[[], _T],
        *,
        name: str | None = None,
        on_done: Callable[[Future[_T]], None] | None = None,
    ) -> None:
        super().__init__()
        if on_done is not None:
            self.add_done_callback(on_done)
        self._thread = Thread(target=self._run, args=(target,), name=name, daemon=True)
        self._thread.start()

    def _run(self, target: Callable[[], _T]) -> None:
        if self.set_running_or_notify_cancel():
            with self:
                self.set_result(target())

    def __enter__(self) -> DaemonTask[_T]:
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if error is None:
            return False
        self.set_exception(error)
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the worker to exit, returning whether it has finished."""
        self._thread.join(timeout)
        return not self._thread.is_alive()
