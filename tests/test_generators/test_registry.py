from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        try:
            registry.get("nonexistent")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_available_providers(self) -> None:
        registry = ProviderRegistry()
        assert "base" in registry.available_providers

    def test_ensure_provider_base(self) -> None:
        registry = ProviderRegistry()
        provider = registry.ensure_provider("base")
        assert provider.name == "base"

    def test_ensure_provider_faker(self) -> None:
        registry = ProviderRegistry()
        provider = registry.ensure_provider("faker")
        assert provider.name == "faker"

    def test_ensure_provider_mimesis(self) -> None:
        registry = ProviderRegistry()
        provider = registry.ensure_provider("mimesis")
        assert provider.name == "mimesis"

    def test_ensure_provider_unknown(self) -> None:
        registry = ProviderRegistry()
        try:
            registry.ensure_provider("unknown_provider")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_register_from_entry_points(self) -> None:
        registry = ProviderRegistry()
        registry.register_from_entry_points()

    def test_register_from_entry_points_with_mock(self) -> None:
        registry = ProviderRegistry()
        mock_ep = MagicMock()
        mock_ep.name = "test_provider"
        mock_ep.load.return_value = BaseProvider

        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_result = MagicMock()
            mock_result.select.return_value = [mock_ep]
            mock_eps.return_value = mock_result
            registry.register_from_entry_points()

    def test_register_from_entry_points_failure(self) -> None:
        registry = ProviderRegistry()
        with patch("importlib.metadata.entry_points") as mock_eps:
            mock_eps.side_effect = Exception("no entry points")
            registry.register_from_entry_points()

    def test_set_default_nonexistent(self) -> None:
        registry = ProviderRegistry()
        try:
            registry.set_default("nonexistent")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_ensure_provider_faker_import_error(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "sqlseed.generators.faker_provider.FakerProvider.__init__",
            side_effect=ImportError("no faker"),
        ):
            try:
                registry.ensure_provider("faker")
                raise AssertionError("Should have raised ImportError")
            except ImportError:
                pass

    def test_ensure_provider_mimesis_import_error(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "sqlseed.generators.mimesis_provider.MimesisProvider.__init__",
            side_effect=ImportError("no mimesis"),
        ):
            try:
                registry.ensure_provider("mimesis")
                raise AssertionError("Should have raised ImportError")
            except ImportError:
                pass
