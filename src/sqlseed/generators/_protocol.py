"""Data provider protocol and exception definitions."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class UnknownGeneratorError(Exception):
    """Raised when the requested generator type is not registered in ``_GENERATOR_MAP``."""

    def __init__(self, generator_name: str, column_name: str | None = None) -> None:
        self.generator_name = generator_name
        self.column_name = column_name
        super().__init__(f"Unknown generator '{generator_name}'{f' for column {column_name}' if column_name else ''}")


class GenerationError(Exception):
    """Raised when an error occurs during data generation."""


class ConfigurationError(Exception):
    """Raised when the generator configuration is invalid or inconsistent."""


@runtime_checkable
class DataProvider(Protocol):
    """Data provider protocol.

    Defines the interface generators must implement: ``name``, ``set_locale``,
    ``set_seed`` and ``generate``.
    """

    @property
    def name(self) -> str: ...

    def set_locale(self, locale: str) -> None: ...

    def set_seed(self, seed: int) -> None: ...

    def generate(self, type_name: str, **params: Any) -> Any: ...
