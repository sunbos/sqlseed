"""Shared date/time helpers for the generator providers.

参考工具 parity (``示例UI/生成数据类型/日期.png``, ``时间.png``, ``日期时间.png``)
demands finer control than a year range:

- exact date bounds (``start_date`` / ``end_date``) rather than year-only,
- a time-of-day window (``start_time`` / ``end_time``) with an "all day"
  escape hatch that unlocks the full 00:00:00–23:59:59 range,
- weekday filtering with three modes: all / workdays / an explicit day set.

Before this module each provider rolled its own date logic, which is exactly
why their precision diverged (faker and mimesis leaked microseconds, base did
not). Centralising the arithmetic keeps all three identical and makes the
weekday math unit-testable without instantiating a provider.

Values are returned as ``date`` / ``time`` / ``datetime`` objects — never
strings — because SQLAlchemy's ``DATE``/``DATETIME`` column types reject
ISO strings and Unix epoch integers.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only needed for annotations (``from __future__ import annotations``
    # defers their evaluation), so keep it out of the runtime import set.
    import random
    from collections.abc import Iterable

#: Monday=0 … Sunday=6 (``date.weekday()`` convention).
WORKDAYS = frozenset({0, 1, 2, 3, 4})
WEEKEND = frozenset({5, 6})
ALL_WEEKDAYS = frozenset(range(7))

DEFAULT_START_TIME = time(0, 0, 0)
DEFAULT_END_TIME = time(23, 59, 59)


class DateRangeError(ValueError):
    """Raised for an unsatisfiable date/time configuration.

    Subclasses ``ValueError`` (not the retriable ``GenerationError``): a bad
    range can never succeed on retry, so the stream layer must surface the
    real cause instead of burning 1000 retries.
    """


def normalize_weekdays(
    value: str | list[int] | tuple[int, ...] | frozenset[int] | set[int] | None,
) -> frozenset[int] | None:
    """Normalise the ``weekdays`` param into a day set, or ``None`` for "all".

    Accepts (mirroring 参考工具's 全部 / 工作日 / 自定义 radio):

    - ``None``, ``"all"``, ``[]`` -> ``None`` (no filtering)
    - ``"workdays"`` -> Mon-Fri, ``"weekend"`` -> Sat-Sun
    - ``[0, 2, 4]`` or ``"0,2,4"`` → that explicit set

    Raises:
        DateRangeError: On an unknown mode name or a day outside 0–6.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return _parse_weekday_string(value)
    return _normalize_weekday_numbers(value)


def _parse_weekday_string(value: str) -> frozenset[int] | None:
    """Resolve named modes or parse the existing comma-separated day syntax."""
    token = value.strip().lower()
    if token in {"", "all", "*"}:
        return None
    if token == "workdays":
        return WORKDAYS
    if token == "weekend":
        return WEEKEND
    parts = [part for part in token.replace(" ", "").split(",") if part]
    try:
        days = [int(part) for part in parts]
    except ValueError as err:
        raise DateRangeError(
            f"weekdays: expected 'all' / 'workdays' / 'weekend' / a comma list of 0-6, got {value!r}"
        ) from err
    return _normalize_weekday_numbers(days)


def _normalize_weekday_numbers(value: Iterable[int]) -> frozenset[int] | None:
    """Validate integer day values and collapse empty or complete sets to all days."""
    days = frozenset(int(d) for d in value)
    if not days:
        return None
    bad = sorted(d for d in days if d < 0 or d > 6)
    if bad:
        raise DateRangeError(f"weekdays: day numbers must be 0 (Mon) - 6 (Sun), got {bad}")
    if days == ALL_WEEKDAYS:
        return None
    return days


def parse_iso_date(value: str | date | None) -> date | None:
    """Parse ``YYYY-MM-DD`` (or pass through a ``date``); ``None`` stays ``None``."""
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as err:
        raise DateRangeError(f"invalid date {value!r} — expected YYYY-MM-DD") from err


def parse_iso_time(value: str | time | None) -> time | None:
    """Parse ``HH:MM`` / ``HH:MM:SS`` (or pass through a ``time``)."""
    if value is None or isinstance(value, time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise DateRangeError(f"invalid time {value!r} — expected HH:MM or HH:MM:SS")


def resolve_date_bounds(
    start_year: int,
    end_year: int | None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> tuple[date, date]:
    """Resolve the inclusive ``[start, end]`` date bounds.

    Precedence, deliberately one-directional so the two schemes never fight:

    1. ``start_date`` / ``end_date`` (``YYYY-MM-DD``) win whenever given.
    2. Otherwise the legacy ``start_year`` / ``end_year`` pair is expanded to
       Jan 1 / Dec 31, so existing YAML configs keep working unchanged.

    ``start_year`` / ``end_year`` are therefore **deprecated fallbacks, not a
    second set of knobs**: the web panel no longer exposes them (two competing
    boundaries on screen left users unsure which one applied), but the core
    still honours them for backward compatibility. ``end_year`` defaults to
    the current year.
    """
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if start is None:
        start = date(int(start_year), 1, 1)
    if end is None:
        end = date(int(end_year) if end_year is not None else date.today().year, 12, 31)
    if end < start:
        start, end = end, start
    return start, end


def random_date(rng: random.Random, start: date, end: date, weekdays: frozenset[int] | None = None) -> date:
    """Uniformly pick a date in ``[start, end]``, optionally weekday-filtered.

    The filtered branch is O(1) rather than reject-and-resample: it computes
    how many admissible days the span contains, draws an index, then maps
    that index straight to an offset. Resampling would degrade badly for
    narrow filters (``weekdays=[2]`` over a short range) and could loop
    forever on an unsatisfiable one.
    """
    span = (end - start).days
    if span < 0:
        raise DateRangeError(f"empty date range: {start} > {end}")
    if weekdays is None:
        return start + timedelta(days=rng.randint(0, span))

    allowed = sorted(weekdays)
    per_week = len(allowed)
    start_wd = start.weekday()
    full_weeks, remainder = divmod(span + 1, 7)
    tail_hits = [i for i in range(remainder) if (start_wd + i) % 7 in weekdays]
    total = full_weeks * per_week + len(tail_hits)
    if total == 0:
        raise DateRangeError(
            f"no date in {start}..{end} matches weekdays {sorted(weekdays)} "
            "(Mon=0 … Sun=6) — widen the range or relax the filter"
        )

    k = rng.randrange(total)
    if k < full_weeks * per_week:
        week, idx = divmod(k, per_week)
        offset = week * 7 + ((allowed[idx] - start_wd) % 7)
    else:
        offset = full_weeks * 7 + tail_hits[k - full_weeks * per_week]
    return start + timedelta(days=offset)


def random_time(rng: random.Random, start_time: time, end_time: time) -> time:
    """Uniformly pick a whole-second time in ``[start_time, end_time]``.

    Whole seconds only — 参考工具's 日期时间 panel has no sub-second control,
    and microsecond noise (``T10:21:03.895011``) carries no meaning.
    """
    lo = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
    hi = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
    if hi < lo:
        raise DateRangeError(f"empty time range: {start_time} > {end_time}")
    seconds = rng.randint(lo, hi)
    return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def resolve_time_bounds(
    all_day: bool,
    start_time: str | time | None,
    end_time: str | time | None,
) -> tuple[time, time]:
    """Resolve the time-of-day window.

    ``all_day=True`` is 参考工具's 一整天 checkbox — it disables the time
    controls and unlocks the full day, so any explicit bounds are ignored.
    """
    if all_day:
        return DEFAULT_START_TIME, DEFAULT_END_TIME
    lo = parse_iso_time(start_time) or DEFAULT_START_TIME
    hi = parse_iso_time(end_time) or DEFAULT_END_TIME
    if hi < lo:
        raise DateRangeError(f"empty time range: {lo} > {hi}")
    return lo, hi
