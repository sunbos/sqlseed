"""Mimesis-based data generator adapter."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators.base_provider import BaseProvider

if TYPE_CHECKING:
    import datetime

# Use importlib.import_module() instead of top-level ``from mimesis import
# Generic`` so that ruff's import-outside-toplevel check is not triggered
# (the original code imported inside _init_mimesis). The ``_*_CLASS`` names
# hold either the mimesis class (when installed) or ``None``.
try:
    _mimesis_module = importlib.import_module("mimesis")
    _mimesis_locales_module = importlib.import_module("mimesis.locales")
    _GENERIC_CLASS = _mimesis_module.Generic
    _LOCALE_ENUM = _mimesis_locales_module.Locale
except ImportError:
    _GENERIC_CLASS = None
    _LOCALE_ENUM = None

HAS_MIMESIS = _GENERIC_CLASS is not None

logger = get_logger(__name__)


class MimesisProvider(BaseProvider):
    """Mimesis-based data generator adapter."""

    def __init__(self) -> None:
        super().__init__()
        self._generic: Any = None
        self._locale: str = "en"
        self._seed: int | None = None
        self._init_mimesis()

    def _init_mimesis(self) -> None:
        """Initialize the Mimesis Generic instance."""
        if _GENERIC_CLASS is None or _LOCALE_ENUM is None:
            raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]")
        locale_enum = _LOCALE_ENUM(self._locale)
        self._generic = _GENERIC_CLASS(locale_enum)

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "mimesis"

    def set_locale(self, locale: str) -> None:
        """Set the locale information and reinitialize Mimesis."""
        locale_map = {
            "en_US": "en",
            "en_GB": "en",
            "zh_CN": "zh",
            "zh_TW": "zh",
            "ja_JP": "ja",
            "ko_KR": "ko",
            "de_DE": "de",
            "fr_FR": "fr",
            "es_ES": "es",
            "pt_BR": "pt-br",
            "ru_RU": "ru",
        }
        self._locale = locale_map.get(locale, locale.split("_", maxsplit=1)[0])
        self._init_mimesis()

    def set_seed(self, seed: int) -> None:
        """Set the random seed."""
        self._seed = seed
        if _LOCALE_ENUM is None or _GENERIC_CLASS is None:
            raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]")
        locale_enum = _LOCALE_ENUM(self._locale)
        self._generic = _GENERIC_CLASS(locale_enum, seed=seed)
        super().set_seed(seed)

    def _gen_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        """Generate an integer."""
        return self._generic.numeric.integer_number(start=min_value, end=max_value)

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        """Generate a float."""
        return round(
            self._generic.numeric.float_number(start=min_value, end=max_value, precision=precision),
            precision,
        )

    def _gen_boolean(self) -> bool:
        """Generate a boolean."""
        return self._generic.development.boolean()

    def _gen_bytes(self, *, length: int = 16) -> bytes:
        """Generate a byte string."""
        return self._generic.cryptographic.token_bytes(length)

    def _gen_name(self) -> str:
        """Generate a full name."""
        return self._generic.person.full_name()

    def _gen_first_name(self) -> str:
        """Generate a first name."""
        return self._generic.person.first_name()

    def _gen_last_name(self) -> str:
        """Generate a last name."""
        return self._generic.person.last_name()

    def _gen_email(self) -> str:
        """Generate an email address."""
        return self._generic.person.email()

    def _gen_phone(self, *, mask: str | None = None) -> str:
        """Generate a phone number.

        默认（``mask=None``）按当前 locale 生成真实国家格式的号码，
        保证业务数据真实性；显式传 ``mask`` 时按 mask 生成（``#`` 替换为
        随机数字），用于需要统一格式的测试场景。
        """
        if mask is None:
            return self._generic.person.phone_number()
        return self._generic.person.phone_number(mask=mask)

    def _gen_address(self) -> str:
        """Generate an address."""
        return self._generic.address.address()

    def _gen_company(self) -> str:
        """Generate a company name."""
        return self._generic.finance.company()

    def _gen_url(self) -> str:
        """Generate a URL."""
        return self._generic.internet.url()

    def _gen_ipv4(self) -> str:
        """Generate an IPv4 address."""
        return self._generic.internet.ip_v4()

    def _gen_uuid(self) -> str:
        """Generate a UUID."""
        return str(self._generic.cryptographic.uuid_object())

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime.date:
        """Generate a ``datetime.date`` object.

        Returning a ``date`` object (rather than a ``str(date)`` string)
        ensures SQLAlchemy ``DATE`` columns accept the value directly —
        SQLite's ``DATE`` type rejects ISO-format strings with
        ``StatementError: SQLite Date type only accepts Python date objects``.
        """
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        return self._generic.datetime.date(start=start_year, end=resolved_end)

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime.datetime:
        """Generate a ``datetime.datetime`` object.

        Returning a ``datetime`` object (rather than a ``str(datetime)`` string)
        ensures SQLAlchemy ``DATETIME``/``TIMESTAMP`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects ISO-format strings with
        ``StatementError: SQLite DateTime type only accepts Python datetime
        and date objects as input``.
        """
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        return self._generic.datetime.datetime(start=start_year, end=resolved_end)

    def _gen_timestamp(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime.datetime:
        """Generate a ``datetime.datetime`` object.

        Returning a ``datetime`` object (rather than a Unix epoch integer)
        ensures SQLAlchemy ``TIMESTAMP``/``DATETIME`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects integers with
        ``StatementError: SQLite DateTime type only accepts Python datetime
        and date objects as input``.
        """
        return self._gen_datetime(start_year=start_year, end_year=end_year)

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        """Generate text."""
        text = self._generic.text.text(quantity=1)
        while len(text) < min_length:
            text += " " + self._generic.text.text(quantity=1)
        return text[:max_length]

    def _gen_sentence(self) -> str:
        """Generate a sentence."""
        return self._generic.text.sentence()

    def _gen_password(self, *, length: int = 16) -> str:
        """Generate a password."""
        return self._generic.person.password(length=length)

    def _gen_choice(self, choices: list[Any]) -> Any:
        """Randomly select a value from the given choices."""
        return self._generic.random.choice(choices)

    def _get_array_count(self) -> int:
        """Return the number of array elements."""
        return self._generic.numeric.integer_number(start=1, end=5)

    def _gen_city(self) -> str:
        """Generate a city name."""
        return self._generic.address.city()

    def _gen_country(self) -> str:
        """Generate a country name."""
        return self._generic.address.country()

    def _gen_state(self) -> str:
        """Generate a state/province."""
        return self._generic.address.state()

    def _gen_zip_code(self) -> str:
        """Generate a postal code."""
        return self._generic.address.postal_code()

    def _gen_job_title(self) -> str:
        """Generate a job title."""
        return self._generic.person.occupation()

    def _gen_country_code(self) -> str:
        """Generate a country code."""
        return self._generic.address.country_code()

    def _gen_word(self) -> str:
        """Generate a real English word (e.g., 'apple', 'computer', 'mountain')."""
        return self._generic.text.word()
