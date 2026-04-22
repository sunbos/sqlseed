from __future__ import annotations

from sqlseed.generators.faker_provider import FakerProvider
from tests.test_generators._mixin import (
    CoreProviderTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
)


class TestFakerProvider(
    CoreProviderTestMixin,
    IdentityProviderTestMixin,
    TemporalProviderTestMixin,
):
    def setup_method(self) -> None:
        self.provider = FakerProvider()

    def test_name(self) -> None:
        assert self.provider.name == "faker"
