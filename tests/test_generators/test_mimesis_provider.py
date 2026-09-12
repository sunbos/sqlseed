from __future__ import annotations

from sqlseed.generators.mimesis_provider import MimesisProvider

from ._mixin import (
    IdentityProviderTestMixin,
    JsonSchemaTestMixin,
    NativePhoneProviderTestMixin,
    TemporalProviderTestMixin,
)


class TestMimesisProvider(
    NativePhoneProviderTestMixin,
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
