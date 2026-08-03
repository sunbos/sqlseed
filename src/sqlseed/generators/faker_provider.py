"""Faker-based data generator adapter."""

from __future__ import annotations

import datetime
import importlib
from typing import Any, ClassVar

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

    # generator 类型 -> 其 _gen_* 实现依赖的 faker 方法名。faker 的部分方法
    # 仅特定 locale 实现（实证：zh_CN 缺 state/zipcode，ja_JP 缺 state），
    # 缺失时在 _init_faker 阶段把该 generator 实例级遮蔽为 base 的类型路由
    # 实现 —— 按 mimesis → faker → base 的既有兜底链降级，而不是让生成在
    # AttributeError 中崩溃（生成中途崩溃 = 整批失败）。仅含本类覆写了
    # _gen_* 且调用 faker 方法的条目；基类纯 Python 实现的不涉及。
    _FAKER_ATTR_PROBES: ClassVar[dict[str, str]] = {
        "integer": "random_int",
        "float": "pyfloat",
        "boolean": "boolean",
        "bytes": "binary",
        "name": "name",
        "first_name": "first_name",
        "last_name": "last_name",
        "email": "email",
        "phone": "phone_number",
        "address": "address",
        "company": "company",
        "url": "url",
        "ipv4": "ipv4",
        "uuid": "uuid4",
        "date": "date_between_dates",
        "datetime": "date_time_between_dates",
        "timestamp": "date_time_between_dates",
        "text": "text",
        "sentence": "sentence",
        "password": "password",
        "choice": "random_element",
        "json": "json",
        "city": "city",
        "country": "country",
        "state": "state",
        "zip_code": "zipcode",
        "job_title": "job",
        "country_code": "country_code",
        "word": "word",
        "catch_phrase": "catch_phrase",
    }

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
        self._install_locale_fallbacks()

    def _install_locale_fallbacks(self) -> None:
        """按当前 locale 能力探测，缺失方法的 generator 降级为 base 实现。

        探测在 locale 切换时执行一次（生成热路径零开销）：dispatch 经
        ``getattr(self, "_gen_<type>")`` 解析方法，实例 ``__dict__`` 中的
        绑定实现优先于类方法，从而只对缺失项遮蔽为 ``BaseProvider`` 的类型
        路由实现。降级走 base 的 ``_rng``（``set_seed`` 已播种），确定性
        不受影响。set_locale 重建 faker 实例时先清除旧遮蔽，保证切回
        支持的 locale 后恢复真实数据。
        """
        for gen_type in self._FAKER_ATTR_PROBES:
            self.__dict__.pop(f"_gen_{gen_type}", None)
        missing: list[str] = []
        for gen_type, attr in self._FAKER_ATTR_PROBES.items():
            if hasattr(self._faker, attr):
                continue
            base_impl = getattr(BaseProvider, f"_gen_{gen_type}", None)
            if base_impl is None:
                continue
            self.__dict__[f"_gen_{gen_type}"] = base_impl.__get__(self)
            missing.append(gen_type)
        if missing:
            logger.warning("faker_locale_fallback", locale=self._locale, generators=missing)

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

    def _gen_phone(self, *, mask: str | None = None) -> str:
        """Generate a phone number.

        默认（``mask=None``）按当前 locale 生成真实国家格式的号码，
        保证业务数据真实性；显式传 ``mask`` 时按 mask 生成（``#`` 替换为
        随机数字），用于需要统一格式的测试场景。
        """
        if mask is None:
            return self._faker.phone_number()
        return self._faker.numerify(mask)

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

    def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime.date:
        """Generate a ``datetime.date`` object.

        Returning a ``date`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATE`` columns accept the value directly —
        SQLite's ``DATE`` type rejects ISO-format strings with
        ``StatementError: SQLite Date type only accepts Python date objects``.
        """
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1).date()
        end = datetime.datetime(resolved_end, 12, 31).date()
        return self._faker.date_between_dates(date_start=start, date_end=end)

    def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> datetime.datetime:
        """Generate a ``datetime.datetime`` object.

        Returning a ``datetime`` object (rather than a ``strftime`` string)
        ensures SQLAlchemy ``DATETIME``/``TIMESTAMP`` columns accept the value
        directly — SQLite's ``DateTime`` type rejects ISO-format strings with
        ``StatementError: SQLite DateTime type only accepts Python datetime
        and date objects as input``.
        """
        _, resolved_end = self._resolve_date_range(start_year, end_year)
        start = datetime.datetime(start_year, 1, 1)
        end = datetime.datetime(resolved_end, 12, 31, 23, 59, 59)
        return self._faker.date_time_between_dates(datetime_start=start, datetime_end=end)

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

    def _gen_word(self) -> str:
        """Generate a real English word (e.g., 'apple', 'computer', 'mountain')."""
        return self._faker.word()

    def _gen_catch_phrase(self) -> str:
        """Generate a business catch phrase (e.g., 'Future-proofed leadingedge paradigm').

        More suitable than ``word`` for business-entity name columns
        (category_name, product_name, dept_name, project_name) where a
        multi-word phrase reads like a real entity name rather than a
        single random word.
        """
        return self._faker.catch_phrase()
