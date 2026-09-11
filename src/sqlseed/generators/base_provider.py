"""Built-in data generator with no external dependencies. Provides 34 generators."""

from __future__ import annotations

import random
import re
import struct
import uuid
import zlib
from datetime import date as _date
from datetime import datetime
from datetime import time as _time
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from math import isfinite
from pathlib import Path
from typing import Any

import rstr as _rstr

from sqlseed.generators._datetime_utils import (
    normalize_weekdays,
    random_date,
    random_time,
    resolve_date_bounds,
    resolve_time_bounds,
)
from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators._json_helpers import generate_json_from_schema
from sqlseed.generators._protocol import ConfigurationError
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
        return generate_random_string(self._rng, min_length=min_length, max_length=max_length, charset=charset)

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
        """Generate a float within the closed interval at the requested precision."""
        lower, upper = self._float_bounds(min_value, max_value, precision)
        if lower == upper:
            return lower
        value = self._rng.uniform(min_value, max_value)
        return max(lower, min(upper, round(value, precision)))

    @staticmethod
    def _float_bounds(min_value: float, max_value: float, precision: int) -> tuple[float, float]:
        """Find rounded endpoints without letting rounding escape the requested range."""
        if not isfinite(min_value) or not isfinite(max_value):
            raise ValueError("float bounds must be finite")
        if min_value > max_value:
            raise ValueError("min_value must not exceed max_value")

        lower, upper = round(min_value, precision), round(max_value, precision)
        if lower < min_value or upper > max_value:
            # Decimal strings avoid treating a bound such as 0.29 as slightly
            # below its decimal value when locating the first/last valid step.
            minimum, maximum = Decimal(str(min_value)), Decimal(str(max_value))
            quantum = Decimal((0, (1,), -precision))
            with localcontext() as context:
                context.prec = max(28, minimum.adjusted() + precision + 1, maximum.adjusted() + precision + 1)
                if lower < min_value:
                    lower = float(minimum.quantize(quantum, rounding=ROUND_CEILING))
                if upper > max_value:
                    upper = float(maximum.quantize(quantum, rounding=ROUND_FLOOR))
        if lower > upper or lower < min_value or upper > max_value:
            raise ValueError(f"No float in [{min_value}, {max_value}] has the requested precision {precision}")
        return float(lower), float(upper)

    def _gen_boolean(self) -> bool:
        """Generate a boolean."""
        n = self._next_id()
        return n % 2 == 1

    def _gen_bytes(
        self,
        *,
        length: int = 16,
        width: int | None = None,
        height: int | None = None,
        image_format: str | None = None,
        folder: str | None = None,
        extensions: list[str] | None = None,
    ) -> bytes:
        """Generate bytes: random data, a synthetic image, or a file from disk.

        Modes (first match wins, mirroring 参考工具's 图像或二进制 type):

        - ``folder`` — pick a random file from the directory (optionally
          filtered by ``extensions``, case-insensitive, leading dot optional).
          Raises ``ValueError`` when the folder is missing or nothing matches.
        - ``width``/``height`` — a synthetic image. PNG is built with the
          stdlib (8-bit RGB, deterministic); ``image_format="jpeg"`` uses
          Pillow when installed and falls back to PNG bytes otherwise.
        - otherwise — ``length`` random bytes (legacy behavior).
        """
        if folder is not None:
            return self._file_bytes_from_folder(folder, extensions)
        if width is not None or height is not None:
            w = width if width is not None else (height or 1)
            h = height if height is not None else (width or 1)
            return self._image_bytes(w, h, image_format or "png")
        return self._rng.randbytes(length)

    def _image_bytes(self, width: int, height: int, image_format: str) -> bytes:
        """Synthesize image bytes for the given dimensions."""
        if image_format.lower() in ("jpeg", "jpg"):
            try:
                import io

                from PIL import Image  # optional dependency — not a hard requirement
            except ImportError:
                return self._png_bytes(width, height)
            buf = io.BytesIO()
            Image.new("RGB", (width, height)).save(buf, format="JPEG")
            return buf.getvalue()
        return self._png_bytes(width, height)

    def _png_bytes(self, width: int, height: int) -> bytes:
        """Build a minimal valid PNG (8-bit RGB, uniform gray) with the stdlib."""
        raw = b"".join(b"\x00" + b"\x80" * (width * 3) for _ in range(height))

        def chunk(tag: bytes, payload: bytes) -> bytes:
            return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

    def _file_bytes_from_folder(self, folder: str, extensions: list[str] | None) -> bytes:
        """Return the bytes of a random file in ``folder`` matching ``extensions``.

        Raises ``ConfigurationError`` (not the retriable ``GenerationError``):
        a missing folder or empty match set can never succeed on retry, and
        the stream layer would otherwise burn 1000 retries and replace the
        real cause with a generic constraint-failure message.
        """
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise ConfigurationError(f"bytes generator: folder does not exist or is not a directory: {folder}")
        exts = {e.lower().lstrip(".") for e in (extensions or [])}
        files = [p for p in root.iterdir() if p.is_file() and (not exts or p.suffix.lower().lstrip(".") in exts)]
        if not files:
            raise ConfigurationError(
                f"bytes generator: no files matching {sorted(exts) or 'any extension'} in {folder}"
            )
        return self._rng.choice(files).read_bytes()

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

    def _gen_phone(self, *, mask: str | None = None) -> str:
        """Generate a phone number.

        base provider 仅作类型路由兜底（无真实数据），接受并忽略 ``mask``
        以保持与 faker/mimesis provider 的接口一致（dispatch 以
        ``method(**params)`` 透传，缺省形参会致 TypeError）。
        """
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
        """Generate text padded to the requested length range.

        Raises:
            ValueError: When ``min_length > max_length`` — silently swapping or
                truncating would violate the caller's contract.
        """
        if min_length > max_length:
            raise ValueError(f"min_length ({min_length}) must be <= max_length ({max_length}) for _gen_text")
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

    def _gen_catch_phrase(self) -> str:
        """Generate a synthesized catch-phrase-style string.

        The base provider has no word list, so we compose a multi-word
        phrase from synthesized pseudo-words to mimic the structure of a
        business catch phrase (e.g., 'banir topelu moripar'). This is
        more suitable than a single ``word`` for business-entity name
        columns.
        """
        self._next_id()
        num_words = self._rng.randint(2, 4)
        words = [self._gen_word() for _ in range(num_words)]
        return " ".join(words)

    # ── Date/time generators ──────────────────────────────────────────

    def _gen_date(
        self,
        *,
        start_year: int = 2000,
        end_year: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        weekdays: str | list[int] | None = "all",
    ) -> _date:
        """Generate a ``datetime.date`` within the given bounds.

        ``start_date`` / ``end_date`` (``YYYY-MM-DD``) take precedence over the
        legacy ``start_year`` / ``end_year`` pair, kept for backward
        compatibility. ``weekdays`` mirrors 参考工具's 全部 / 工作日 / 自定义
        radio: ``"all"`` (default), ``"workdays"``, or an explicit day list
        such as ``[0, 2, 4]`` (Mon=0 … Sun=6).

        Returning a ``date`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATE`` columns accept the value directly —
        SQLite's ``DATE`` type rejects ISO-format strings with
        ``StatementError: SQLite Date type only accepts Python date objects``.
        """
        self._next_id()
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
        """Generate a ``datetime.datetime`` within the given bounds.

        ``all_day`` is 参考工具's 一整天 checkbox (checked by default): it
        unlocks the full 00:00:00–23:59:59 day and ignores ``start_time`` /
        ``end_time``. Unchecking it restricts generation to that window.

        Truncated to whole seconds — 参考工具's 日期时间 panel has no
        sub-second control, so microsecond noise carries no meaning.

        Returning a ``datetime`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATETIME``/``TIMESTAMP`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects strings and Unix epoch
        integers with ``StatementError: SQLite DateTime type only accepts
        Python datetime and date objects as input``.
        """
        self._next_id()
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
    ) -> _time:
        """Generate a ``datetime.time`` (参考工具 时间 panel).

        ``all_day=True`` (default, 参考工具's 一整天 checkbox) spans the whole
        day; unchecking it enables the ``start_time`` / ``end_time`` window
        (``HH:MM`` or ``HH:MM:SS``). Whole seconds only — 参考工具's 时间 panel
        has no sub-second control.
        """
        self._next_id()
        lo, hi = resolve_time_bounds(all_day, start_time, end_time)
        return random_time(self._rng, lo, hi)

    def _gen_timestamp(
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
        """Generate a ``datetime.datetime`` within the given bounds.

        Accepts the same params as :meth:`_gen_datetime` and delegates to it —
        sqlseed's ``timestamp`` and ``datetime`` are the same SQLAlchemy-facing
        ``datetime`` object; only the column dialect differs.

        Returning a ``datetime`` object (rather than a Unix epoch integer)
        ensures SQLAlchemy ``TIMESTAMP``/``DATETIME`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects integers with
        ``StatementError: SQLite DateTime type only accepts Python datetime
        and date objects as input``.
        """
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

    # ── Network generators ────────────────────────────────────────────

    def _gen_url(self) -> str:
        """Generate a URL."""
        n = self._next_id()
        s = self._seeded_id()
        return f"https://example.com/page_{n:03d}_{s:04d}"

    def _gen_ipv4(self) -> str:
        """Generate an IPv4 address.

        Each octet is constrained to the legal 0-255 range — using the
        incrementing counter would eventually exceed 255 and produce an
        illegal address.
        """
        self._next_id()
        octet = self._rng.randint(0, 255)
        return f"0.0.0.{octet}"

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
        """Select a value from the given choices.

        Raises:
            ValueError: When ``choices`` is empty — ``random.choice`` would
                raise ``IndexError`` which is not actionable for the caller.
        """
        if not choices:
            raise ValueError("_gen_choice requires a non-empty 'choices' list")
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
            self._template_seq: dict[str, int] = {}
        # Use the template string itself as the seq_key — id() can be reused
        # by the allocator after a string is garbage-collected, causing two
        # unrelated templates to share a counter. The string value is a stable,
        # deterministic key.
        seq_key = template
        if seq_key not in self._template_seq:
            self._template_seq[seq_key] = sequence_start - sequence_step

        self._template_seq[seq_key] += sequence_step
        seq_val = self._template_seq[seq_key]

        # Replace custom placeholders first (not in default str.format spec)
        result = template
        # {random_string:N}
        while "{random_string:" in result:
            start = result.index("{random_string:")
            end = result.find("}", start)
            if end == -1:
                raise ValueError(f"Malformed template — unmatched '{{' in: {template!r}")
            n = int(result[start + len("{random_string:") : end])
            charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            replacement = "".join(self._rng.choice(charset) for _ in range(n))
            result = result[:start] + replacement + result[end + 1 :]

        # {random_digits:N}
        while "{random_digits:" in result:
            start = result.index("{random_digits:")
            end = result.find("}", start)
            if end == -1:
                raise ValueError(f"Malformed template — unmatched '{{' in: {template!r}")
            n = int(result[start + len("{random_digits:") : end])
            replacement = "".join(str(self._rng.randint(0, 9)) for _ in range(n))
            result = result[:start] + replacement + result[end + 1 :]

        # {random_int:MIN-MAX}
        while "{random_int:" in result:
            start = result.index("{random_int:")
            end = result.find("}", start)
            if end == -1:
                raise ValueError(f"Malformed template — unmatched '{{' in: {template!r}")
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
            weighted_choices: Value-to-weight mapping or the same weighted list
                accepted by choices.

        Returns:
            One value selected with probability proportional to its weight.
        """
        self._next_id()
        if isinstance(weighted_choices, list):
            choices = weighted_choices
        if weighted_choices is not None and isinstance(weighted_choices, dict):
            population = list(weighted_choices.keys())
            weights = [weighted_choices[v] for v in population]
        elif choices is not None:
            if all(isinstance(c, str) for c in choices):
                # 等权字符串列表：与 weighted_choices={v: 1} 等价。web 属性面板的
                # 「每行一个值」textarea 提交的正是这个形状，此前会在这里以
                # TypeError: string indices must be integers 崩掉。
                population = list(choices)
                weights = [1] * len(population)
            else:
                population = [c["value"] for c in choices]
                weights = [c.get("weight", 1) for c in choices]
        else:
            raise ValueError("weighted_choice requires 'choices' or 'weighted_choices' param")

        selected = self._rng.choices(population, weights=weights, k=1)
        return selected[0]
