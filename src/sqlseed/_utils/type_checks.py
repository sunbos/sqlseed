"""Exact runtime type policies shared by configuration and boundary validation."""

from __future__ import annotations

from typing import TypeGuard, TypeVar

_T = TypeVar("_T")


def has_exact_type(value: object, expected: type[_T]) -> TypeGuard[_T]:
    """Accept only the actual runtime class, without subclass or coercion hooks.

    This deliberately rejects bool where int is required and ignores a value's
    custom ``__class__`` attribute and metaclass equality implementation.
    """
    actual = type(value)
    return actual is expected
