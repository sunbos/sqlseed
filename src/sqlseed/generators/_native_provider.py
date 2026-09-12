"""Shared generation rules for providers backed by native locale libraries."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlseed.generators._datetime_utils import (
    normalize_weekdays,
    random_date,
    random_time,
    resolve_date_bounds,
    resolve_time_bounds,
)
from sqlseed.generators.base_provider import BaseProvider


class NativeProvider(BaseProvider):
    """Share native-provider arithmetic without advancing BaseProvider's counter.

    Date/time generation uses the provider's seeded shared RNG. Native float
    draws remain provider-specific. BaseProvider's directly bound fallbacks
    keep their own RNG and counter behavior.
    """

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        """Apply shared float bounds while drawing through the native library."""
        return self._generate_float_in_bounds(
            min_value, max_value, precision, lambda: self._draw_native_float(min_value, max_value, precision)
        )

    def _draw_native_float(self, min_value: float, max_value: float, precision: int) -> float:
        """Draw one value through the concrete provider's seeded native RNG."""
        raise NotImplementedError

    def _gen_date(
        self,
        *,
        start_year: int = 2000,
        end_year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        weekdays: str | list[int] | None = "all",
    ) -> date:
        """Return a date under shared bounds and weekday rules, without counting a placeholder."""
        start, end = resolve_date_bounds(start_year, end_year, start_date, end_date)
        return random_date(self._rng, start, end, normalize_weekdays(weekdays))

    def _gen_datetime(
        self,
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
        """Return whole seconds, drawing the day before validating and drawing the time."""
        start, end = resolve_date_bounds(start_year, end_year, start_date, end_date)
        day = random_date(self._rng, start, end, normalize_weekdays(weekdays))
        lo, hi = resolve_time_bounds(all_day, start_time, end_time)
        return datetime.combine(day, random_time(self._rng, lo, hi))

    def _gen_time(
        self,
        *,
        all_day: bool = True,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> time:
        """Return whole seconds from the shared all-day or explicit time window."""
        lo, hi = resolve_time_bounds(all_day, start_time, end_time)
        return random_time(self._rng, lo, hi)
