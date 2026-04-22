from __future__ import annotations

import datetime
import time
from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed.generators.base_provider import BaseProvider

try:
    from faker import Faker as _FakerClass

    HAS_FAKER = True
except ImportError:
    _FakerClass = None  # type: ignore[assignment,misc]
    HAS_FAKER = False

logger = get_logger(__name__)


class FakerProvider(BaseProvider):
    """Faker-based data generator adapter."""

    def __init__(self) -> None:
        super().__init__()
        self._faker: Any = None
        self._seed: int | None = None
        self._init_faker()

    def _init_faker(self) -> None:
        if not HAS_FAKER:
            raise ImportError("Faker is not installed. Install it with: pip install sqlseed[faker]")
        self._faker = _FakerClass(self._locale)

    @property
    def name(self) -> str:
        return "faker"

    def set_locale(self, locale: str) -> None:
        self._locale = locale
        self._init_faker()

    def set_seed(self, seed: int) -> None:
        self._seed = seed
        self._faker.seed_instance(seed)
        super().set_seed(seed)

    def _gen_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        return self._faker.random_int(min=min_value, max=max_value)

    def _gen_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        return round(self._faker.pyfloat(min_value=min_value, max_value=max_value, right_digits=precision), precision)

    def _gen_boolean(self) -> bool:
        return self._faker.boolean()

    def _gen_bytes(self, *, length: int = 16) -> bytes:
        return self._faker.binary(length=length)

    def _gen_name(self) -> str:
        return self._faker.name()

    def _gen_first_name(self) -> str:
        return self._faker.first_name()

    def _gen_last_name(self) -> str:
        return self._faker.last_name()

    def _gen_email(self) -> str:
        return self._faker.email()

    def _gen_phone(self) -> str:
        return self._faker.phone_number()

    def _gen_address(self) -> str:
        return self._faker.address().replace("\n", ", ")

    def _gen_company(self) -> str:
        return self._faker.company()

    def _gen_url(self) -> str:
        return self._faker.url()

    def _gen_ipv4(self) -> str:
        return self._faker.ipv4()

    def _gen_uuid(self) -> str:
        return self._faker.uuid4()

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1).date()
        end = datetime.datetime(resolved_end, 12, 31).date()
        return self._faker.date_between_dates(date_start=start, date_end=end).strftime("%Y-%m-%d")

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1)
        end = datetime.datetime(resolved_end, 12, 31, 23, 59, 59)
        dt = self._faker.date_time_between_dates(datetime_start=start, datetime_end=end)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _gen_timestamp(self) -> int:
        dt = self._faker.date_time_this_decade()
        return int(time.mktime(dt.timetuple()))

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        text = self._faker.text(max_nb_chars=max_length)
        while len(text) < min_length:
            text += " " + self._faker.text(max_nb_chars=max_length - len(text))
        return text[:max_length]

    def _gen_sentence(self) -> str:
        return self._faker.sentence()

    def _gen_password(self, *, length: int = 16) -> str:
        return self._faker.password(length=length)

    def _gen_choice(self, choices: list[Any]) -> Any:
        return self._faker.random_element(choices)

    def _gen_json(self, *, schema: dict[str, Any] | None = None) -> str:
        return self._faker.json(data_columns=schema)
