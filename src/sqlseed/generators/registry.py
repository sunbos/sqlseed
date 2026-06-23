"""Data provider registry with entry-point discovery and lazy loading."""

from __future__ import annotations

import importlib.metadata

from sqlseed._utils.logger import get_logger
from sqlseed.generators._protocol import DataProvider
from sqlseed.generators.base_provider import BaseProvider

try:
    from sqlseed.generators.faker_provider import FakerProvider

    HAS_FAKER = True
except ImportError:
    HAS_FAKER = False

try:
    from sqlseed.generators.mimesis_provider import MimesisProvider

    HAS_MIMESIS = True
except ImportError:
    HAS_MIMESIS = False

logger = get_logger(__name__)


class ProviderRegistry:
    """Data provider registry.

    Supports registering, retrieving and setting the default provider, as well as
    auto-discovering providers via Python entry points. The built-in ``base`` provider
    is always available; ``faker`` and ``mimesis`` are lazily loaded on demand.
    """

    def __init__(self) -> None:
        """Initialize the registry and register the built-in ``base`` provider."""
        self._providers: dict[str, DataProvider] = {}
        self._default_name: str = "base"
        self._register_builtin()

    def _register_builtin(self) -> None:
        """Register the built-in ``base`` provider to ensure the registry always has at least one available provider."""
        base = BaseProvider()
        self._providers["base"] = base

    def register(self, provider: DataProvider) -> None:
        """Register a data provider in the registry.

        Args:
            provider: A provider instance implementing the ``DataProvider`` protocol.
        """
        name = provider.name
        self._providers[name] = provider
        logger.debug("Registered provider", name=name)

    def register_from_entry_points(self) -> None:
        """Auto-discover and register providers from Python entry points (group="sqlseed").

        Entry points may return a provider class or instance. Load failures are logged
        as warnings and skipped without affecting other entry points.
        """
        try:
            eps = importlib.metadata.entry_points()
            sqlseed_eps = eps.select(group="sqlseed") if hasattr(eps, "select") else eps.get("sqlseed", [])  # type: ignore[arg-type]
            for ep in sqlseed_eps:
                try:
                    loaded = ep.load()
                    if isinstance(loaded, type):
                        provider = loaded()
                    elif isinstance(loaded, DataProvider):
                        provider = loaded
                    else:
                        logger.debug("Skipping non-provider entry point", name=ep.name, entry_point=ep.value)
                        continue

                    if isinstance(provider, DataProvider):
                        self.register(provider)
                        logger.info("Auto-discovered provider", name=ep.name)
                    else:
                        logger.debug("Skipping non-provider entry point", name=ep.name, entry_point=ep.value)
                except (ImportError, AttributeError, ValueError, TypeError, OSError, RuntimeError) as e:
                    logger.warning("Failed to load provider", name=ep.name, error=e)
        except (ImportError, AttributeError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.debug("Entry point discovery failed", error=e)

    def get(self, name: str | None = None) -> DataProvider:
        """Get the provider with the given name.

        Args:
            name: Provider name. When ``None``, the default provider is returned.

        Returns:
            The ``DataProvider`` instance for the given name.

        Raises:
            ValueError: Raised when the given name is not registered.
        """
        provider_name = name or self._default_name
        if provider_name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ValueError(f"Provider '{provider_name}' not found. Available: {available}")
        return self._providers[provider_name]

    def set_default(self, name: str) -> None:
        """Set the default provider.

        Args:
            name: Name of an already-registered provider.

        Raises:
            ValueError: Raised when the name is not registered.
        """
        if name not in self._providers:
            raise ValueError(f"Provider '{name}' not found")
        self._default_name = name

    @property
    def default_name(self) -> str:
        """Return the name of the current default provider."""
        return self._default_name

    @property
    def available_providers(self) -> list[str]:
        """Return a list of all registered provider names."""
        return list(self._providers.keys())

    def ensure_provider(self, name: str) -> DataProvider:
        """Ensure the given provider is available, lazily loading faker/mimesis when necessary.

        Args:
            name: Provider name (base/faker/mimesis).

        Returns:
            The corresponding ``DataProvider`` instance.

        Raises:
            ImportError: Raised when faker/mimesis is not installed.
            ValueError: Raised when the provider name is unknown.
        """
        if name in self._providers:
            return self._providers[name]

        if name == "faker" and HAS_FAKER:
            provider: DataProvider = FakerProvider()
            self.register(provider)
            return provider
        if name == "faker":
            raise ImportError("Faker is not installed. Install it with: pip install sqlseed[faker]")

        if name == "mimesis" and HAS_MIMESIS:
            provider = MimesisProvider()
            self.register(provider)
            return provider
        if name == "mimesis":
            raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]")

        raise ValueError(f"Unknown provider: {name}")
