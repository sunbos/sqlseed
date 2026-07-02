from __future__ import annotations

from sqlseed.generators.base_provider import BaseProvider

from ._mixin import (
    IdentityProviderTestMixin,
    JsonSchemaTestMixin,
    TemporalProviderTestMixin,
)


class TestBaseProvider(
    JsonSchemaTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
):
    def setup_method(self) -> None:
        self.provider = BaseProvider()

    def test_name(self) -> None:
        assert self.provider.name == "base"

    def test_generate_name_format(self) -> None:
        result = self.provider.generate("name")
        assert " " in result

    def test_generate_phone_format(self) -> None:
        result = self.provider.generate("phone")
        assert "-" in result

    def test_generate_url_format(self) -> None:
        result = self.provider.generate("url")
        assert result.startswith("http")

    def test_generate_uuid_format(self) -> None:
        result = self.provider.generate("uuid")
        assert len(result) == 36
        assert result.count("-") == 4

    def test_generate_date_range(self) -> None:
        import datetime as _dt

        result = self.provider.generate("date", start_year=2020, end_year=2024)
        assert isinstance(result, _dt.date)
        assert _dt.date(2020, 1, 1) <= result <= _dt.date(2024, 12, 31)

    def test_generate_datetime_is_datetime_object(self) -> None:
        import datetime as _dt

        result = self.provider.generate("datetime", start_year=2020, end_year=2024)
        assert isinstance(result, _dt.datetime)
        assert _dt.datetime(2020, 1, 1) <= result <= _dt.datetime(2024, 12, 31, 23, 59, 59)

    def test_generate_text_long(self) -> None:
        result = self.provider.generate("text", min_length=50, max_length=200)
        assert len(result) <= 200

    def test_generate_sentence_ends_with_period(self) -> None:
        result = self.provider.generate("sentence")
        assert result.endswith(".")

    def test_generate_word_is_pronounceable(self) -> None:
        """word generator produces a non-empty alphabetic token of reasonable length."""
        result = self.provider.generate("word")
        assert isinstance(result, str)
        assert 4 <= len(result) <= 8
        assert result.isalpha()

    def test_generate_word_seed_reproducibility(self) -> None:
        """word generator respects set_seed for reproducible output."""
        self.provider.set_seed(42)
        r1 = self.provider.generate("word")
        self.provider.set_seed(42)
        r2 = self.provider.generate("word")
        assert r1 == r2

    def test_generate_string_default_charset(self) -> None:
        result = self.provider.generate("string", min_length=5, max_length=10, charset=None)
        assert len(result) >= 5

    def test_seed_reproducibility(self) -> None:
        self.provider.set_seed(42)
        r1 = self.provider.generate("integer", min_value=0, max_value=999999)
        self.provider.set_seed(42)
        r2 = self.provider.generate("integer", min_value=0, max_value=999999)
        assert r1 == r2
