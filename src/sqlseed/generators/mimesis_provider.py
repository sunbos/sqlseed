"""Mimesis-based data generator adapter."""

from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators.base_provider import BaseProvider

try:
    from mimesis import Generic as _GenericClass
    from mimesis.locales import Locale as _LocaleEnum

    HAS_MIMESIS = True
except ImportError:
    _GenericClass = None  # type: ignore[assignment,misc]
    _LocaleEnum = None  # type: ignore[assignment,misc]
    HAS_MIMESIS = False

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
        if not HAS_MIMESIS:
            raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]")
        locale_enum = _LocaleEnum(self._locale)
        self._generic = _GenericClass(locale_enum)

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
        locale_enum = _LocaleEnum(self._locale)
        self._generic = _GenericClass(locale_enum, seed=seed)
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

    def _gen_phone(self) -> str:
        """Generate a phone number."""
        return self._generic.person.phone_number()

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

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a date string."""
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        date = self._generic.datetime.date(start=start_year, end=resolved_end)
        return str(date)

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a datetime string."""
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        dt = self._generic.datetime.datetime(start=start_year, end=resolved_end)
        return str(dt)

    def _gen_timestamp(self) -> int:
        """Generate a Unix timestamp."""
        return self._generic.datetime.timestamp()

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
