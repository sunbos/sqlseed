from __future__ import annotations

from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class MimesisProvider:
    """Mimesis-based data generator adapter."""

    def __init__(self) -> None:
        self._generic: Any = None
        self._locale: str = "en"
        self._seed: int | None = None
        self._init_mimesis()

    def _init_mimesis(self) -> None:
        try:
            from mimesis import Generic
            from mimesis.locales import Locale

            locale_enum = Locale(self._locale)
            self._generic = Generic(locale_enum)
        except ImportError:
            raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]") from None

    @property
    def name(self) -> str:
        return "mimesis"

    def set_locale(self, locale: str) -> None:
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
        from mimesis import Generic
        from mimesis.locales import Locale

        self._seed = seed
        locale_enum = Locale(self._locale)
        self._generic = Generic(locale_enum, seed=seed)

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
        length = self._generic.numeric.integer_number(start=min_length, end=max_length)
        return "".join(self._generic.random.choice(chars) for _ in range(length))

    def generate_integer(self, *, min_value: int = 0, max_value: int = 999999) -> int:
        return self._generic.numeric.integer_number(start=min_value, end=max_value)

    def generate_float(
        self,
        *,
        min_value: float = 0.0,
        max_value: float = 999999.0,
        precision: int = 2,
    ) -> float:
        return round(
            self._generic.numeric.float_number(start=min_value, end=max_value, precision=precision),
            precision,
        )

    def generate_boolean(self) -> bool:
        return self._generic.development.boolean()

    def generate_bytes(self, *, length: int = 16) -> bytes:
        return self._generic.cryptographic.token_bytes(length)

    def generate_name(self) -> str:
        return self._generic.person.full_name()

    def generate_first_name(self) -> str:
        return self._generic.person.first_name()

    def generate_last_name(self) -> str:
        return self._generic.person.last_name()

    def generate_email(self) -> str:
        return self._generic.person.email()

    def generate_phone(self) -> str:
        return self._generic.person.phone_number()

    def generate_address(self) -> str:
        return self._generic.address.address()

    def generate_company(self) -> str:
        return self._generic.finance.company()

    def generate_url(self) -> str:
        return self._generic.internet.url()

    def generate_ipv4(self) -> str:
        return self._generic.internet.ip_v4()

    def generate_uuid(self) -> str:
        return str(self._generic.cryptographic.uuid_object())

    def generate_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        from datetime import datetime

        if end_year is None:
            end_year = datetime.now().year
        date = self._generic.datetime.date(start=start_year, end=end_year)
        return str(date)

    def generate_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
        from datetime import datetime

        if end_year is None:
            end_year = datetime.now().year
        dt = self._generic.datetime.datetime(start=start_year, end=end_year)
        return str(dt)

    def generate_timestamp(self) -> int:
        return self._generic.datetime.timestamp()

    def generate_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        text = self._generic.text.text(quantity=1)
        while len(text) < min_length:
            text += " " + self._generic.text.text(quantity=1)
        return text[:max_length]

    def generate_sentence(self) -> str:
        return self._generic.text.sentence()

    def generate_password(self, *, length: int = 16) -> str:
        return self._generic.person.password(length=length)

    def generate_choice(self, choices: list[Any]) -> Any:
        return self._generic.random.choice(choices)

    def generate_json(self, *, schema: dict[str, Any] | None = None) -> str:
        import json

        if schema is None:
            data = {
                "id": self.generate_integer(min_value=1, max_value=999999),
                "name": self.generate_name(),
                "active": self.generate_boolean(),
            }
        else:
            data = self._generate_from_schema(schema)
        return json.dumps(data)

    def _generate_from_schema(self, schema: dict[str, Any]) -> Any:
        schema_type = schema.get("type", "string")
        if schema_type == "string":
            return self.generate_string(min_length=5, max_length=20)
        if schema_type == "integer":
            return self.generate_integer()
        if schema_type == "number":
            return self.generate_float()
        if schema_type == "boolean":
            return self.generate_boolean()
        if schema_type == "array":
            items = schema.get("items", {"type": "string"})
            count = self._generic.numeric.integer_number(start=1, end=5)
            return [self._generate_from_schema(items) for _ in range(count)]
        if schema_type == "object":
            properties = schema.get("properties", {})
            return {k: self._generate_from_schema(v) for k, v in properties.items()}
        return self.generate_string()

    def generate_pattern(self, *, regex: str) -> str:
        import random
        import rstr

        rng = random.Random(self._seed)
        return rstr.Rstr(rng).xeger(regex)
