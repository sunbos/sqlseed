from __future__ import annotations

from sqlseed._utils.logger import get_logger
from sqlseed.generators._protocol import DataProvider
from sqlseed.generators.base_provider import BaseProvider

logger = get_logger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, DataProvider] = {}
        self._default_name: str = "base"
        self._register_builtin()

    def _register_builtin(self) -> None:
        base = BaseProvider()
        self._providers["base"] = base

    def register(self, provider: DataProvider) -> None:
        name = provider.name
        self._providers[name] = provider
        logger.debug("Registered provider", name=name)

    def register_from_entry_points(self) -> None:
        try:
            from importlib.metadata import entry_points

            eps = entry_points()
            sqlseed_eps = eps.select(group="sqlseed") if hasattr(eps, "select") else eps.get("sqlseed", [])  # type: ignore[arg-type]
            for ep in sqlseed_eps:
                try:
                    provider_cls = ep.load()
                    provider = provider_cls()
                    if isinstance(provider, DataProvider):
                        self.register(provider)
                        logger.info("Auto-discovered provider", name=ep.name)
                except Exception as e:
                    logger.warning("Failed to load provider", name=ep.name, error=e)
        except Exception as e:
            logger.debug("Entry point discovery failed", error=e)

    def get(self, name: str | None = None) -> DataProvider:
        provider_name = name or self._default_name
        if provider_name not in self._providers:
            available = ", ".join(self._providers.keys())
            raise ValueError(f"Provider '{provider_name}' not found. Available: {available}")
        return self._providers[provider_name]

    def set_default(self, name: str) -> None:
        if name not in self._providers:
            raise ValueError(f"Provider '{name}' not found")
        self._default_name = name

    @property
    def default_name(self) -> str:
        return self._default_name

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    def ensure_provider(self, name: str) -> DataProvider:
        if name in self._providers:
            return self._providers[name]

        if name == "faker":
            try:
                from sqlseed.generators.faker_provider import FakerProvider

                provider: DataProvider = FakerProvider()
                self.register(provider)
                return provider
            except ImportError:
                raise ImportError("Faker is not installed. Install it with: pip install sqlseed[faker]") from None
        elif name == "mimesis":
            try:
                from sqlseed.generators.mimesis_provider import MimesisProvider

                provider = MimesisProvider()
                self.register(provider)
                return provider
            except ImportError:
                raise ImportError("Mimesis is not installed. Install it with: pip install sqlseed[mimesis]") from None

        raise ValueError(f"Unknown provider: {name}")
