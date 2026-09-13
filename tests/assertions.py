"""Assertions shared by tests that verify public result shapes."""

from __future__ import annotations


def assert_empty(actual: object, expected_type: type) -> None:
    """Require both the expected collection type and an empty value."""
    assert isinstance(actual, expected_type), (
        f"Expected {expected_type.__name__}, got {type(actual).__name__}: {actual!r}"
    )
    assert not actual, f"Expected an empty {expected_type.__name__}, got {actual!r}"
