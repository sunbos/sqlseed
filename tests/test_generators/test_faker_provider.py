from __future__ import annotations

from sqlseed.generators.faker_provider import FakerProvider

from ._mixin import (
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

    def test_generate_word_returns_real_word(self) -> None:
        """Faker's word() returns a real English word (non-empty alphabetic string)."""
        result = self.provider.generate("word")
        assert isinstance(result, str)
        assert len(result) > 0
        assert result.isalpha()
