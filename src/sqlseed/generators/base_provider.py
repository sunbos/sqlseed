"""Built-in data generator with no external dependencies. Provides 31 generators."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators._json_helpers import generate_json_from_schema
from sqlseed.generators._string_helpers import generate_random_string


class BaseProvider(GeneratorDispatchMixin):
    """Built-in data generator with no external dependencies.

    Uses an incrementing counter combined with seed variation to produce lightweight
    placeholder data. No hardcoded data lists — all values are synthesized.
    """

    def __init__(self) -> None:
        self._rng = random.Random()
        self._locale: str = "en_US"
        self._counter: int = 0

    def _next_id(self) -> int:
        """Return the next incrementing counter value (starting from 1)."""
        self._counter += 1
        return self._counter

    def _seeded_id(self) -> int:
        """Return a seed-based counter variant for differentiation."""
        return self._rng.randint(1, 9999)

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "base"

    def set_locale(self, locale: str) -> None:
        """Set the locale information."""
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        """Set the random seed."""
        self._rng = random.Random(seed)

    # ── Primitive generators ──────────────────────────────────────────

    def _gen_string(
        self,
        *,
        min_length: int = 1,
        max_length: int = 100,
        charset: str | None = None,
    ) -> str:
        """Generate a string."""
        if charset is not None:
            return generate_random_string(self._rng, min_length=min_length, max_length=max_length, charset=charset)
        n = self._next_id()
        return f"str_{n:03d}"

    def _gen_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        """Generate an integer."""
        return self._rng.randint(min_value, max_value)

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        """Generate a float."""
        value = self._rng.uniform(min_value, max_value)
        return round(value, precision)

    def _gen_boolean(self) -> bool:
        """Generate a boolean."""
        n = self._next_id()
        return n % 2 == 1

    def _gen_bytes(self, *, length: int = 16) -> bytes:
        """Generate a byte string."""
        return self._rng.randbytes(length)

    # ── Name generators ───────────────────────────────────────────────

    def _gen_name(self) -> str:
        """Generate a full name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"first_{n:03d}_{s:04d} last_{n:03d}_{s:04d}"

    def _gen_first_name(self) -> str:
        """Generate a first name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"first_{n:03d}_{s:04d}"

    def _gen_last_name(self) -> str:
        """Generate a last name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"last_{n:03d}_{s:04d}"

    # ── Contact generators ────────────────────────────────────────────

    def _gen_email(self) -> str:
        """Generate an email address."""
        n = self._next_id()
        s = self._seeded_id()
        return f"user_{n:03d}_{s:04d}@placeholder.com"

    def _gen_phone(self) -> str:
        """Generate a phone number."""
        n = self._next_id()
        return f"000-0000-{n:04d}"

    def _gen_address(self) -> str:
        """Generate an address."""
        n = self._next_id()
        s = self._seeded_id()
        return f"addr_{n:03d}_{s:04d}"

    # ── Location generators ───────────────────────────────────────────

    def _gen_city(self) -> str:
        """Generate a city name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"city_{n:03d}_{s:04d}"

    def _gen_state(self) -> str:
        """Generate a state/province."""
        n = self._next_id()
        s = self._seeded_id()
        return f"state_{n:03d}_{s:04d}"

    def _gen_country(self) -> str:
        """Generate a country name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"country_{n:03d}_{s:04d}"

    def _gen_zip_code(self) -> str:
        """Generate a postal code."""
        n = self._next_id()
        return f"{n:05d}"

    def _gen_country_code(self) -> str:
        """Generate a country code."""
        n = self._next_id()
        s = self._seeded_id()
        return f"CC{n:03d}_{s:04d}"

    # ── Business generators ───────────────────────────────────────────

    def _gen_company(self) -> str:
        """Generate a company name."""
        n = self._next_id()
        s = self._seeded_id()
        return f"company_{n:03d}_{s:04d}"

    def _gen_job_title(self) -> str:
        """Generate a job title."""
        n = self._next_id()
        s = self._seeded_id()
        return f"job_{n:03d}_{s:04d}"

    # ── Text generators ───────────────────────────────────────────────

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        """Generate text."""
        n = self._next_id()
        s = self._seeded_id()
        return f"text_{n:03d}_{s:04d}"

    def _gen_sentence(self) -> str:
        """Generate a sentence."""
        n = self._next_id()
        s = self._seeded_id()
        return f"text_{n:03d}_{s:04d}."

    # ── Date/time generators ──────────────────────────────────────────

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a date string."""
        n = self._next_id()
        base = datetime(start_year, 1, 1) + timedelta(days=n - 1)
        return base.strftime("%Y-%m-%d")

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a datetime string."""
        n = self._next_id()
        base = datetime(start_year, 1, 1) + timedelta(hours=n - 1)
        return base.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _resolve_date_range(start_year: int, end_year: int | None) -> tuple[int, int]:
        """Resolve the date range and return the start and end years."""
        resolved_end = end_year or datetime.now().year
        return start_year, max(resolved_end, start_year)

    def _random_date(self, start_year: int, end_year: int | None = None) -> datetime:
        """Randomly generate a date within the given year range."""
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime(start_year, 1, 1)
        end = datetime(resolved_end, 12, 31)
        delta = max((end - start).days, 0)
        return start + timedelta(days=self._rng.randint(0, max(delta, 1)))

    def _gen_timestamp(self) -> int:
        """Generate a Unix timestamp."""
        start = datetime(2000, 1, 1)
        end = datetime(2030, 12, 31, 23, 59, 59)
        delta = (end - start).total_seconds()
        random_dt = start + timedelta(seconds=self._rng.uniform(0, delta))
        return int(random_dt.timestamp())

    # ── Network generators ────────────────────────────────────────────

    def _gen_url(self) -> str:
        """Generate a URL."""
        n = self._next_id()
        s = self._seeded_id()
        return f"https://example.com/page_{n:03d}_{s:04d}"

    def _gen_ipv4(self) -> str:
        """Generate an IPv4 address."""
        n = self._next_id()
        return f"0.0.0.{n}"

    def _gen_uuid(self) -> str:
        """Generate a UUID."""
        self._next_id()
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    # ── Credential generators ─────────────────────────────────────────

    def _gen_password(self, *, length: int = 16) -> str:
        """Generate a password."""
        n = self._next_id()
        s = self._seeded_id()
        core = f"pass_{n:03d}_{s:04d}!"
        if len(core) >= length:
            return core[:length]
        # Pad with seed-based digits to reach requested length
        pad_len = length - len(core)
        padding = "".join(str(self._rng.randint(0, 9)) for _ in range(pad_len))
        return core + padding

    def _gen_username(self) -> str:
        """Generate a username."""
        n = self._next_id()
        s = self._seeded_id()
        return f"user_{n:03d}_{s:04d}"

    # ── Other generators ──────────────────────────────────────────────

    def _gen_choice(self, choices: list[Any]) -> Any:
        """Select a value from the given choices."""
        self._next_id()
        return self._rng.choice(choices)

    def _gen_json(self, *, schema: dict[str, Any] | None = None) -> str:
        """Generate a JSON string based on the schema."""
        self._next_id()
        return generate_json_from_schema(self, schema, self._get_array_count)

    def _get_array_count(self) -> int:
        """Return the number of array elements."""
        return self._rng.randint(1, 5)

    def _gen_pattern(self, *, pattern: str | None = None, regex: str | None = None) -> str:
        """Generate a string matching the regex pattern."""
        effective = pattern or regex or ""
        try:
            # Optional dependency — import inside the function to defer ImportError
            import rstr as _rstr  # noqa: PLC0415
        except ImportError as err:
            raise ImportError(
                "The 'rstr' package is required for pattern generation. Install it with: pip install rstr"
            ) from err
        r = _rstr.Rstr(self._rng)
        return r.xeger(effective)
