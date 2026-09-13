"""Data provider protocol and exception definitions."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class UnknownGeneratorError(Exception):
    """Raised when the requested generator type is not registered in ``GENERATOR_MAP``."""

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
    def name(self) -> str:
        """Return the provider's unique name (e.g. ``"faker"``, ``"mimesis"``)."""

    def set_locale(self, locale: str) -> None:
        """Set the locale for locale-aware generation (e.g. ``"en_US"``, ``"zh_CN"``)."""

    def set_seed(self, seed: int) -> None:
        """Set the random seed for reproducible generation."""

    def generate(
        self,
        type_name: str,
        *,
        exclude_values: set[Any] | None = None,
        **params: Any,
    ) -> Any:
        """Generate a single value of the given type with optional parameters.

        Args:
            type_name: Generator type name (e.g. ``"email"``, ``"integer"``).
            exclude_values: Optional set of values the generator should avoid
                producing. When non-empty, the dispatch layer retries
                internally (up to a fixed maximum) to return a value not in
                the set. Used by ``DataStream`` to enforce UNIQUE constraints
                on semantic generators (email/phone/name etc.) that would
                otherwise produce duplicates on large row counts. ``None``
                or an empty set means no exclusion (backward compatible).
            **params: Generator-specific parameters.

        Returns:
            The generated value. When ``exclude_values`` is non-empty and the
            value space is exhausted, returns the last generated value (the
            caller's ``ConstraintSolver.try_register`` will detect the
            duplicate and trigger backtracking).
        """
