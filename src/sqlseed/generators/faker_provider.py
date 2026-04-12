from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class FakerProvider:
    """Faker-based data generator adapter."""

    def __init__(self) -> None:
        self._faker: Any = None
        self._locale: str = "en_US"
        self._seed: int | None = None
        self._init_faker()

    def _init_faker(self) -> None:
        try:
            from faker import Faker

            self._faker = Faker(self._locale)
        except ImportError:
            raise ImportError("Faker is not installed. Install it with: pip install sqlseed[faker]") from None

    @property
    def name(self) -> str:
        return "faker"

    def set_locale(self, locale: str) -> None:
        self._locale = locale
        self._init_faker()

    def set_seed(self, seed: int) -> None:
        self._faker.seed_instance(seed)

    def generate_string(
        self,
        *,
        min_length: int = 1,
        max_length: int = 100,
        charset: str | None = None,
    ) -> str:
        import string

        if charset == "alphanumeric":
            chars = string.ascii_letters + string.digits
        elif charset == "alpha":
            chars = string.ascii_letters
        elif charset == "digits":
            chars = string.digits
        elif charset is not None:
            chars = charset
        else:
            chars = string.ascii_letters + string.digits + " _-"
        length = self._faker.random_int(min=min_length, max=max_length)
        return "".join(self._faker.random_element(chars) for _ in range(length))

    def generate_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        return self._faker.random_int(min=min_value, max=max_value)

    def generate_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        return round(self._faker.pyfloat(min_value=min_value, max_value=max_value, right_digits=precision), precision)

    def generate_boolean(self) -> bool:
        return self._faker.boolean()

    def generate_bytes(self, *, length: int = 16) -> bytes:
        return self._faker.binary(length=length)

    def generate_name(self) -> str:
        return self._faker.name()

    def generate_first_name(self) -> str:
        return self._faker.first_name()

    def generate_last_name(self) -> str:
        return self._faker.last_name()

    def generate_email(self) -> str:
        return self._faker.email()

    def generate_phone(self) -> str:
        return self._faker.phone_number()

    def generate_address(self) -> str:
        return self._faker.address().replace("\n", ", ")

    def generate_company(self) -> str:
        return self._faker.company()

    def generate_url(self) -> str:
        return self._faker.url()

    def generate_ipv4(self) -> str:
        return self._faker.ipv4()

    def generate_uuid(self) -> str:
        return self._faker.uuid4()

    def generate_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        from datetime import datetime

        if end_year is None:
            end_year = datetime.now().year
        start = datetime(start_year, 1, 1).date()
        end = datetime(end_year, 12, 31).date()
        return self._faker.date_between_dates(date_start=start, date_end=end).strftime("%Y-%m-%d")

    def generate_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        from datetime import datetime

        if end_year is None:
            end_year = datetime.now().year
        start = datetime(start_year, 1, 1)
        end = datetime(end_year, 12, 31, 23, 59, 59)
        dt = self._faker.date_time_between_dates(datetime_start=start, datetime_end=end)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def generate_timestamp(self) -> int:
        import time

        dt = self._faker.date_time_this_decade()
        return int(time.mktime(dt.timetuple()))

    def generate_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        text = self._faker.text(max_nb_chars=max_length)
        while len(text) < min_length:
            text += " " + self._faker.text(max_nb_chars=max_length - len(text))
        return text[:max_length]

    def generate_sentence(self) -> str:
        return self._faker.sentence()

    def generate_password(self, *, length: int = 16) -> str:
        return self._faker.password(length=length)

    def generate_choice(self, choices: list[Any]) -> Any:
        return self._faker.random_element(choices)

    def generate_json(self, *, schema: dict[str, Any] | None = None) -> str:
        return self._faker.json(data_columns=schema)

    def generate_pattern(self, *, regex: str) -> str:
        import random
        import rstr
        
        rng = random.Random(self._seed)
        return rstr.Rstr(rng).xeger(regex)
