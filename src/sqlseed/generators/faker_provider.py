"""Faker-based data generator adapter."""

from __future__ import annotations

import datetime
import importlib
import time
from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators.base_provider import BaseProvider

# Use importlib.import_module() instead of a top-level ``from faker import
# Faker`` so that ruff's import-outside-toplevel check is not triggered
# (the original code imported Faker inside _init_faker). The ``_*_CLASS``
# name holds either the Faker class (when installed) or ``None``.
try:
    _faker_module = importlib.import_module("faker")
    _FAKER_CLASS = _faker_module.Faker
except ImportError:
    _FAKER_CLASS = None

HAS_FAKER = _FAKER_CLASS is not None

logger = get_logger(__name__)


class FakerProvider(BaseProvider):
    """Faker-based data generator adapter."""

    def __init__(self) -> None:
        super().__init__()
        self._faker: Any = None
        self._seed: int | None = None
        self._init_faker()

    def _init_faker(self) -> None:
        """Initialize the Faker instance."""
        if _FAKER_CLASS is None:
            raise ImportError("Faker is not installed. Install it with: pip install sqlseed[faker]")
        self._faker = _FAKER_CLASS(self._locale)

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "faker"

    def set_locale(self, locale: str) -> None:
        """Set the locale information and reinitialize Faker."""
        self._locale = locale
        self._init_faker()

    def set_seed(self, seed: int) -> None:
        """Set the random seed."""
        self._seed = seed
        self._faker.seed_instance(seed)
        super().set_seed(seed)

    def _gen_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        """Generate an integer."""
        return self._faker.random_int(min=min_value, max=max_value)

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        """Generate a float."""
        return round(self._faker.pyfloat(min_value=min_value, max_value=max_value, right_digits=precision), precision)

    def _gen_boolean(self) -> bool:
        """Generate a boolean."""
        return self._faker.boolean()

    def _gen_bytes(self, *, length: int = 16) -> bytes:
        """Generate a byte string."""
        return self._faker.binary(length=length)

    def _gen_name(self) -> str:
        """Generate a full name."""
        return self._faker.name()

    def _gen_first_name(self) -> str:
        """Generate a first name."""
        return self._faker.first_name()

    def _gen_last_name(self) -> str:
        """Generate a last name."""
        return self._faker.last_name()

    def _gen_email(self) -> str:
        """Generate an email address."""
        return self._faker.email()

    def _gen_phone(self) -> str:
        """Generate a phone number."""
        return self._faker.phone_number()

    def _gen_address(self) -> str:
        """Generate an address."""
        return self._faker.address().replace("\n", ", ")

    def _gen_company(self) -> str:
        """Generate a company name."""
        return self._faker.company()

    def _gen_url(self) -> str:
        """Generate a URL."""
        return self._faker.url()

    def _gen_ipv4(self) -> str:
        """Generate an IPv4 address."""
        return self._faker.ipv4()

    def _gen_uuid(self) -> str:
        """Generate a UUID."""
        return self._faker.uuid4()

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a date string."""
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1).date()
        end = datetime.datetime(resolved_end, 12, 31).date()
        return self._faker.date_between_dates(date_start=start, date_end=end).strftime("%Y-%m-%d")

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        """Generate a datetime string."""
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1)
        end = datetime.datetime(resolved_end, 12, 31, 23, 59, 59)
        dt = self._faker.date_time_between_dates(datetime_start=start, datetime_end=end)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _gen_timestamp(self) -> int:
        """Generate a Unix timestamp."""
        dt = self._faker.date_time_this_decade()
        return int(time.mktime(dt.timetuple()))

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        """Generate text."""
        text = self._faker.text(max_nb_chars=max_length)
        while len(text) < min_length:
            text += " " + self._faker.text(max_nb_chars=max_length - len(text))
        return text[:max_length]

    def _gen_sentence(self) -> str:
        """Generate a sentence."""
        return self._faker.sentence()

    def _gen_password(self, *, length: int = 16) -> str:
        """Generate a password."""
        return self._faker.password(length=length)

    def _gen_choice(self, choices: list[Any]) -> Any:
        """Randomly select a value from the given choices."""
        return self._faker.random_element(choices)

    def _gen_json(self, *, schema: dict[str, Any] | None = None) -> str:
        """Generate a JSON string based on the schema."""
        return self._faker.json(data_columns=schema)

    def _gen_city(self) -> str:
        """Generate a city name."""
        return self._faker.city()

    def _gen_country(self) -> str:
        """Generate a country name."""
        return self._faker.country()

    def _gen_state(self) -> str:
        """Generate a state/province."""
        return self._faker.state()

    def _gen_zip_code(self) -> str:
        """Generate a postal code."""
        return self._faker.zipcode()

    def _gen_job_title(self) -> str:
        """Generate a job title."""
        return self._faker.job()

    def _gen_country_code(self) -> str:
        """Generate a country code."""
        return self._faker.country_code()
