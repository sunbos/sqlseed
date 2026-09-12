"""Shared generation rules for providers backed by native locale libraries."""

from __future__ import annotations

from sqlseed.generators._datetime_methods import date_method, datetime_method, time_method
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

    _gen_date = date_method(count_placeholder=False)
    _gen_datetime = datetime_method()
    _gen_time = time_method(count_placeholder=False)
