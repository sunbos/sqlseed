"""Validated generator names and families shared by AI validation and repair."""

from __future__ import annotations

NUMERIC_GENERATORS = frozenset({"integer", "float", "random_int", "random_float"})
CANONICAL_NUMERIC_GENERATORS = frozenset({"integer", "float"})
DATE_GENERATORS = frozenset({"date", "datetime"})
RELATION_GENERATORS = frozenset({"autoincrement", "foreign_key_or_integer"})


def generator_name(value: object) -> str | None:
    """Return a plain name; malformed model values have no generator identity."""
    return str(value) if isinstance(value, str) else None


def needs_typed_source(value: object) -> bool:
    """Identify missing or generic-string sources that cannot perform date arithmetic."""
    return generator_name(value) in {None, "string"}
