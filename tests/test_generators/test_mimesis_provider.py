from __future__ import annotations

from sqlseed.generators.mimesis_provider import MimesisProvider

from ._mixin import (
    IdentityProviderTestMixin,
    JsonSchemaTestMixin,
    TemporalProviderTestMixin,
)


class TestMimesisProvider(
    JsonSchemaTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
):
    def setup_method(self) -> None:
        self.provider = MimesisProvider()

    def test_name(self) -> None:
        assert self.provider.name == "mimesis"

    def test_generate_word_returns_real_word(self) -> None:
        """Mimesis's text.word() returns a real English word (non-empty string)."""
        result = self.provider.generate("word")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_phone_default_follows_locale(self) -> None:
        """默认 phone 按 locale 生成真实号码（非空字符串，含数字）。

        默认 mask=None 走 mimesis 原生 phone_number()，按 locale 输出真实
        国家格式，不强制统一，保证业务真实性。
        """
        for _ in range(20):
            phone = self.provider.generate("phone")
            assert isinstance(phone, str)
            assert len(phone) > 0
            assert any(c.isdigit() for c in phone)

    def test_phone_custom_mask(self) -> None:
        """显式传 mask 参数时按 mask 生成（统一格式的可控覆盖）。"""
        phone = self.provider.generate("phone", mask="1##########")
        assert isinstance(phone, str)
        assert len(phone) == 11
        assert phone.isdigit()
        assert phone.startswith("1")

    def test_generate_uuid(self) -> None:
        result = self.provider.generate("uuid")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_date_default_end_year(self) -> None:
        import datetime as _dt

        result = self.provider.generate("date", start_year=2020)
        assert isinstance(result, _dt.date)
        assert result.year >= 2020
