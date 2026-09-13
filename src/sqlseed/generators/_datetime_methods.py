"""Date generators with implementation-owned bookkeeping policies.

The returned ordinary methods keep explicit keyword parameters and annotations.
Binding the counter policy when the method is created preserves BaseProvider
fallbacks even when they are installed on a native provider instance.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Protocol

from sqlseed.generators._datetime_utils import (
    normalize_weekdays,
    random_date,
    random_time,
    resolve_date_bounds,
    resolve_time_bounds,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from random import Random


class _DateTimeHost(Protocol):
    """Only the state and dynamic alias target needed by these generators."""

    _rng: Random
    _gen_datetime: Callable[..., datetime]

    def _next_id(self) -> int:
        """Advance the placeholder counter."""
        ...


def date_method(*, count_placeholder: bool) -> Callable[..., date]:
    """Bind a date generator to its implementation's placeholder policy."""

    def _gen_date(
        self: _DateTimeHost,
        *,
        start_year: int = 2000,
        end_year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        weekdays: str | list[int] | None = "all",
    ) -> date:
        """Generate a ``datetime.date`` within the given bounds.

        Explicit ISO date bounds take precedence over the legacy year bounds.
        Weekdays accepts all days, workdays, or a list of weekday numbers.
        SQLAlchemy DATE columns receive date objects, never formatted strings.
        """
        if count_placeholder:
            self._next_id()
        start, end = resolve_date_bounds(start_year, end_year, start_date, end_date)
        return random_date(self._rng, start, end, normalize_weekdays(weekdays))

    return _gen_date


def datetime_method(*, count_placeholder: bool = False, delegate: bool = False) -> Callable[..., datetime]:
    """Bind a datetime implementation or its late-bound timestamp alias."""

    def _gen_datetime(
        self: _DateTimeHost,
        *,
        start_year: int = 2000,
        end_year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        all_day: bool = True,
        start_time: str | None = None,
        end_time: str | None = None,
        weekdays: str | list[int] | None = "all",
    ) -> datetime:
        """Generate a ``datetime.datetime`` within the given bounds.

        Draw the day before validating and drawing the time, retaining RNG
        consumption on invalid time bounds. All-day mode ignores explicit time
        bounds. Results have whole seconds and work with SQLAlchemy DATETIME
        and TIMESTAMP columns. Timestamp delegates to the current datetime
        method, including a native override or an installed Base fallback.
        """
        if delegate:
            return self._gen_datetime(
                start_year=start_year,
                end_year=end_year,
                start_date=start_date,
                end_date=end_date,
                all_day=all_day,
                start_time=start_time,
                end_time=end_time,
                weekdays=weekdays,
            )
        if count_placeholder:
            self._next_id()
        start, end = resolve_date_bounds(start_year, end_year, start_date, end_date)
        day = random_date(self._rng, start, end, normalize_weekdays(weekdays))
        lo, hi = resolve_time_bounds(all_day, start_time, end_time)
        return datetime.combine(day, random_time(self._rng, lo, hi))

    return _gen_datetime


def time_method(*, count_placeholder: bool) -> Callable[..., time]:
    """Bind a time generator to its implementation's placeholder policy."""

    def _gen_time(
        self: _DateTimeHost,
        *,
        all_day: bool = True,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> time:
        """Generate a ``datetime.time`` (参考工具 时间 panel).

        All-day mode spans 00:00:00 through 23:59:59; explicit windows accept
        HH:MM or HH:MM:SS. Results always have whole seconds.
        """
        if count_placeholder:
            self._next_id()
        lo, hi = resolve_time_bounds(all_day, start_time, end_time)
        return random_time(self._rng, lo, hi)

    return _gen_time
