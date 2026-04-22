from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class UnknownGeneratorError(Exception):
    def __init__(self, generator_name: str, column_name: str | None = None) -> None:
        self.generator_name = generator_name
        self.column_name = column_name
        super().__init__(f"Unknown generator '{generator_name}'{f' for column {column_name}' if column_name else ''}")


@runtime_checkable
class DataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def set_locale(self, locale: str) -> None: ...

    def set_seed(self, seed: int) -> None: ...

    def generate(self, type_name: str, **params: Any) -> Any: ...
