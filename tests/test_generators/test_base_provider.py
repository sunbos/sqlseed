from __future__ import annotations

from sqlseed.generators.base_provider import BaseProvider
from tests.test_generators._mixin import (
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
        result = self.provider.generate("date", start_year=2020, end_year=2024)
        assert result.startswith("20")

    def test_generate_datetime_has_space(self) -> None:
        result = self.provider.generate("datetime", start_year=2020, end_year=2024)
        assert " " in result

    def test_generate_text_long(self) -> None:
        result = self.provider.generate("text", min_length=50, max_length=200)
        assert len(result) <= 200

    def test_generate_sentence_ends_with_period(self) -> None:
        result = self.provider.generate("sentence")
        assert result.endswith(".")

    def test_generate_string_default_charset(self) -> None:
        result = self.provider.generate("string", min_length=5, max_length=10, charset=None)
        assert len(result) >= 5

    def test_seed_reproducibility(self) -> None:
        self.provider.set_seed(42)
        r1 = self.provider.generate("integer", min_value=0, max_value=999999)
        self.provider.set_seed(42)
        r2 = self.provider.generate("integer", min_value=0, max_value=999999)
        assert r1 == r2
