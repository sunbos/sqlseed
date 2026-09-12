"""Faker-based data generator adapter."""

from __future__ import annotations

import importlib
from types import MethodType
from typing import Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed.generators._native_provider import NativeProvider
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


class FakerProvider(NativeProvider):
    """Faker-based data generator adapter."""

    # Locale-specific providers may expose equivalent methods under different
    # names (zh_CN uses province/postcode). Try those before installing a Base
    # fallback, and remember the resolved method until the next locale switch.
    _FAKER_ATTR_PROBES: ClassVar[dict[str, str | tuple[str, ...]]] = {
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
        "city": "city",
        "country": "country",
        "state": ("state", "province"),
        "zip_code": ("zipcode", "postcode"),
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
            raise ImportError("Faker is not installed. It is required by sqlseed. Install it with: pip install Faker")
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
        self._faker_attrs: dict[str, str] = {}
        missing: list[str] = []
        for gen_type, attr in self._FAKER_ATTR_PROBES.items():
            candidates = (attr,) if isinstance(attr, str) else attr
            resolved = next((candidate for candidate in candidates if hasattr(self._faker, candidate)), None)
            if resolved is not None:
                self._faker_attrs[gen_type] = resolved
                continue
            base_impl = getattr(BaseProvider, f"_gen_{gen_type}", None)
            if base_impl is None:
                continue
            self.__dict__[f"_gen_{gen_type}"] = MethodType(base_impl, self)
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

    def _draw_native_float(self, min_value: float, max_value: float, precision: int) -> float:
        """Draw using the native library; shared validation runs before this call."""
        return self._faker.pyfloat(min_value=min_value, max_value=max_value, right_digits=precision)

    def _gen_boolean(self) -> bool:
        """Generate a boolean."""
        return self._faker.boolean()

    def _gen_bytes(self, *, length: int = 16, **kwargs: Any) -> bytes:
        """Generate a byte string; media modes (image/folder) live in the base provider."""
        if kwargs:
            return super()._gen_bytes(length=length, **kwargs)
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

    def _gen_text(self, *, min_length: int = 50, max_length: int = 200) -> str:
        """Generate text."""
        if min_length > max_length:
            raise ValueError(f"min_length ({min_length}) must be <= max_length ({max_length})")
        # Faker requires at least five characters per call, even when only a
        # shorter final fragment is needed. Trim after reaching the minimum.
        text = self._faker.text(max_nb_chars=max(5, max_length))
        while len(text) < min_length:
            text += " " + self._faker.text(max_nb_chars=max(5, max_length - len(text)))
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

    def _gen_city(self) -> str:
        """Generate a city name."""
        return self._faker.city()

    def _gen_country(self) -> str:
        """Generate a country name."""
        return self._faker.country()

    def _gen_state(self) -> str:
        """Generate a state/province."""
        return getattr(self._faker, self._faker_attrs["state"])()

    def _gen_zip_code(self) -> str:
        """Generate a postal code."""
        return getattr(self._faker, self._faker_attrs["zip_code"])()

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
