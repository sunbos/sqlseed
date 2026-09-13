from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.registry import ProviderRegistry


class TestProviderRegistry:
    def test_builtin_base_provider(self) -> None:
        registry = ProviderRegistry()
        provider = registry.get("base")
        assert isinstance(provider, BaseProvider)

    def test_default_provider(self) -> None:
        registry = ProviderRegistry()
        assert registry.default_name == "base"
        provider = registry.get()
        assert provider.name == "base"

    def test_register_custom_provider(self) -> None:
        registry = ProviderRegistry()
        custom = BaseProvider()
        registry.register(custom)
        assert "base" in registry.available_providers

    def test_set_default(self) -> None:
        registry = ProviderRegistry()
        registry.set_default("base")
        assert registry.default_name == "base"

    def test_get_nonexistent_provider(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(ValueError):
            registry.get("nonexistent")

    def test_available_providers(self) -> None:
        registry = ProviderRegistry()
        assert "base" in registry.available_providers

    def test_ensure_provider_base(self) -> None:
        registry = ProviderRegistry()
        provider = registry.ensure_provider("base")
        assert provider.name == "base"

    def test_ensure_provider_faker(self) -> None:
        pytest.importorskip("faker")
        registry = ProviderRegistry()
        provider = registry.ensure_provider("faker")
        assert provider.name == "faker"

    def test_ensure_provider_mimesis(self) -> None:
        pytest.importorskip("mimesis")
        registry = ProviderRegistry()
        provider = registry.ensure_provider("mimesis")
        assert provider.name == "mimesis"

    def test_ensure_provider_unknown(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(ValueError):
            registry.ensure_provider("unknown_provider")

    def test_register_from_entry_points(self) -> None:
        registry = ProviderRegistry()
        registry.register_from_entry_points()

    def test_register_from_entry_points_with_mock(self) -> None:
        registry = ProviderRegistry()
        mock_ep = MagicMock()
        mock_ep.name = "test_provider"

        class TestProvider(BaseProvider):
            @property
            def name(self) -> str:
                return "test_provider"

        mock_ep.load.return_value = TestProvider

        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_result = MagicMock()
            mock_result.select.return_value = [mock_ep]
            mock_eps.return_value = mock_result
            registry.register_from_entry_points()

        assert "test_provider" in registry.available_providers

    def test_register_from_entry_points_skips_non_provider_entrypoint(self) -> None:
        registry = ProviderRegistry()
        mock_ep = MagicMock()
        mock_ep.name = "ai_plugin"
        mock_ep.load.return_value = object()

        with (
            patch("importlib.metadata.entry_points") as mock_eps,
            patch("sqlseed.generators.registry.logger.warning") as mock_warning,
        ):
            mock_result = MagicMock()
            mock_result.select.return_value = [mock_ep]
            mock_eps.return_value = mock_result

            registry.register_from_entry_points()

        mock_warning.assert_not_called()

    def test_register_from_entry_points_failure(self) -> None:
        registry = ProviderRegistry()
        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_eps.side_effect = RuntimeError("no entry points")
            registry.register_from_entry_points()

    def test_set_default_nonexistent(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(ValueError):
            registry.set_default("nonexistent")

    def test_ensure_provider_faker_import_error(self) -> None:
        """When HAS_FAKER is False, ensure_provider('faker') raises ImportError with install hint.

        Previously mocked ``FakerProvider.__init__`` to raise ImportError, which
        was self-proving: the mock forced the exception and the assertion merely
        echoed it (mutmut baseline 2026-06-25). Now patches the module-level
        ``HAS_FAKER`` flag to exercise the real ``if name == "faker": raise
        ImportError(...)`` branch (registry.py:148-149), and asserts the
        install-hint message content so mutants like ``raise ValueError`` or
        message corruption get killed.
        """
        registry = ProviderRegistry()
        with (
            patch("sqlseed.generators.registry.HAS_FAKER", False),
            pytest.raises(ImportError, match="Faker is not installed"),
        ):
            registry.ensure_provider("faker")

    def test_ensure_provider_mimesis_import_error(self) -> None:
        """When HAS_MIMESIS is False, ensure_provider('mimesis') raises ImportError with install hint."""
        registry = ProviderRegistry()
        with (
            patch("sqlseed.generators.registry.HAS_MIMESIS", False),
            pytest.raises(ImportError, match="Mimesis is not installed"),
        ):
            registry.ensure_provider("mimesis")
