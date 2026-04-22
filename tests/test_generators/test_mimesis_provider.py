from __future__ import annotations

from sqlseed.generators.mimesis_provider import MimesisProvider
from tests.test_generators._mixin import (
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

    def test_generate_uuid(self) -> None:
        result = self.provider.generate("uuid")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_date_default_end_year(self) -> None:
        result = self.provider.generate("date", start_year=2020)
        assert len(result) > 0
