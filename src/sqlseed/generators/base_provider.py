"""Built-in data generator with no external dependencies. Provides 34 generators."""

from __future__ import annotations

import random
import re
import uuid
from datetime import date as _date
from datetime import datetime, timedelta
from typing import Any

import rstr as _rstr

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
        """Generate a random string respecting ``min_length`` and ``max_length``.

        When ``charset`` is ``None``, a default charset (letters, digits, space,
        underscore, hyphen) is used via :func:`resolve_charset`. This ensures
        that ``min_length`` is always honored — previously, a missing
        ``charset`` caused the method to return a fixed-length ``str_NNN``
        placeholder, ignoring ``min_length``/``max_length`` entirely.
        """
        return generate_random_string(
            self._rng, min_length=min_length, max_length=max_length, charset=charset
        )

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
        """Generate text padded to the requested length range."""
        n = self._next_id()
        s = self._seeded_id()
        core = f"text_{n:03d}_{s:04d}"
        while len(core) < min_length:
            core += str(self._rng.randint(0, 9))
        return core[:max_length]

    def _gen_sentence(self) -> str:
        """Generate a sentence."""
        n = self._next_id()
        s = self._seeded_id()
        return f"text_{n:03d}_{s:04d}."

    def _gen_word(self) -> str:
        """Generate a pronounceable pseudo-word (e.g., 'banir', 'topelu').

        Uses a consonant-vowel alternation pattern to synthesize word-like
        tokens without any hardcoded word list, consistent with the base
        provider's "all values are synthesized" philosophy.
        """
        self._next_id()
        consonants = "bcdfghjklmnpqrstvwxz"
        vowels = "aeiou"
        length = self._rng.randint(4, 8)
        chars: list[str] = []
        for i in range(length):
            if i % 2 == 0:
                chars.append(self._rng.choice(consonants))
            else:
                chars.append(self._rng.choice(vowels))
        return "".join(chars)

    # ── Date/time generators ──────────────────────────────────────────

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> _date:
        """Generate a ``datetime.date`` within the given year range.

        Returning a ``date`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATE`` columns accept the value directly —
        SQLite's ``DATE`` type rejects ISO-format strings with
        ``StatementError: SQLite Date type only accepts Python date objects``.
        """
        self._next_id()
        return self._random_date(start_year, end_year).date()

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime:
        """Generate a ``datetime.datetime`` within the given year range.

        Returning a ``datetime`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATETIME``/``TIMESTAMP`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects strings and Unix epoch
        integers with ``StatementError: SQLite DateTime type only accepts
        Python datetime and date objects as input``.
        """
        self._next_id()
        base = self._random_date(start_year, end_year)
        return base.replace(
            hour=self._rng.randint(0, 23),
            minute=self._rng.randint(0, 59),
            second=self._rng.randint(0, 59),
        )

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

    def _gen_timestamp(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime:
        """Generate a ``datetime.datetime`` within the given year range.

        Returning a ``datetime`` object (rather than a Unix epoch integer)
        ensures SQLAlchemy ``TIMESTAMP``/``DATETIME`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects integers with
        ``StatementError: SQLite DateTime type only accepts Python datetime
        and date objects as input``.
        """
        self._next_id()
        return self._gen_datetime(start_year=start_year, end_year=end_year)

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
        r = _rstr.Rstr(self._rng)
        return r.xeger(effective)

    def _gen_template(
        self,
        *,
        template: str = "",
        sequence_start: int = 1,
        sequence_step: int = 1,
    ) -> str:
        """Generate a value from a template with placeholders.

        Supported placeholders (use Python str.format-style):
        - ``{sequence}`` — incrementing integer counter (per-provider).
        - ``{sequence:04d}`` — counter with format spec.
        - ``{random_string:N}`` — N-character random alphanumeric string.
        - ``{random_int:MIN-MAX}`` — random integer in [MIN, MAX].
        - ``{random_digits:N}`` — N random digits (0-9).

        Examples:
        - ``"MER-{sequence:04d}"`` -> ``MER-0001``, ``MER-0002``...
        - ``"ORD-{random_string:6}"`` -> ``ORD-aB3x9K``
        - ``"SKU-{random_int:100-999}"`` -> ``SKU-542``

        Args:
            template: Template string with placeholders.
            sequence_start: Starting value for {sequence} (default 1).
            sequence_step: Increment step for {sequence} (default 1).

        Returns:
            Formatted string with placeholders replaced.
        """
        if not hasattr(self, "_template_seq"):
            self._template_seq: dict[int, int] = {}
        seq_key = id(template)
        if seq_key not in self._template_seq:
            self._template_seq[seq_key] = sequence_start - sequence_step

        self._template_seq[seq_key] += sequence_step
        seq_val = self._template_seq[seq_key]

        # Replace custom placeholders first (not in default str.format spec)
        result = template
        # {random_string:N}
        while "{random_string:" in result:
            start = result.index("{random_string:")
            end = result.index("}", start)
            n = int(result[start + len("{random_string:") : end])
            charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            replacement = "".join(self._rng.choice(charset) for _ in range(n))
            result = result[:start] + replacement + result[end + 1 :]

        # {random_digits:N}
        while "{random_digits:" in result:
            start = result.index("{random_digits:")
            end = result.index("}", start)
            n = int(result[start + len("{random_digits:") : end])
            replacement = "".join(str(self._rng.randint(0, 9)) for _ in range(n))
            result = result[:start] + replacement + result[end + 1 :]

        # {random_int:MIN-MAX}
        while "{random_int:" in result:
            start = result.index("{random_int:")
            end = result.index("}", start)
            range_spec = result[start + len("{random_int:") : end]
            min_v, max_v = range_spec.split("-")
            replacement = str(self._rng.randint(int(min_v), int(max_v)))
            result = result[:start] + replacement + result[end + 1 :]

        # {sequence} or {sequence:format}
        # Use a sentinel-safe approach: temporarily replace {sequence:XXd} with formatted value

        def _replace_sequence(match: re.Match[str]) -> str:
            fmt = match.group(1)
            if fmt:
                # Strip leading colon: ":04d" -> "04d"
                return format(seq_val, fmt.lstrip(":"))
            return str(seq_val)

        return re.sub(r"\{sequence(:[^}]*)?\}", _replace_sequence, result)

    def _gen_weighted_choice(
        self,
        *,
        choices: list[Any] | None = None,
        weighted_choices: dict[str, int] | list[dict[str, Any]] | None = None,
    ) -> Any:
        """Select a value with weighted probability.

        Supports two param formats:
        1. ``choices`` as list of ``{"value": ..., "weight": ...}`` dicts:
           .. code-block:: yaml
               choices:
                 - value: active
                   weight: 80
                 - value: suspended
                   weight: 15
        2. ``weighted_choices`` as dict mapping value -> weight:
           .. code-block:: yaml
               weighted_choices:
                 active: 80
                 suspended: 15
                 closed: 5

        Args:
            choices: List of ``{"value": v, "weight": w}`` dicts.
            weighted_choices: Dict mapping value -> weight (alternative to choices).

        Returns:
            One value selected with probability proportional to its weight.
        """
        self._next_id()
        if weighted_choices is not None and isinstance(weighted_choices, dict):
            population = list(weighted_choices.keys())
            weights = [weighted_choices[v] for v in population]
        elif choices is not None:
            population = [c["value"] for c in choices]
            weights = [c.get("weight", 1) for c in choices]
        else:
            raise ValueError("weighted_choice requires 'choices' or 'weighted_choices' param")

        selected = self._rng.choices(population, weights=weights, k=1)
        return selected[0]

