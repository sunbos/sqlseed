"""Exact runtime type contracts exclude coercions and subclass masquerading."""

from __future__ import annotations

import importlib
from enum import IntEnum
from importlib.util import find_spec

import pytest


class _IntegerSubclass(int):
    pass


class _StringSubclass(str):
    pass


class _IntegerEnum(IntEnum):
    ONE = 1


class _Pretender:
    @property
    def __class__(self) -> type[int]:
        return int


@pytest.mark.parametrize(
    ("value", "expected_type", "accepted"),
    [
        (1, int, True),
        (True, bool, True),
        (False, bool, True),
        ("value", str, True),
        (None, type(None), True),
        (True, int, False),
        (1, bool, False),
        (1.0, int, False),
        (_IntegerSubclass(1), int, False),
        (_IntegerEnum.ONE, int, False),
        (_StringSubclass("value"), str, False),
        (_Pretender(), int, False),
    ],
)
def test_exact_type_contract(value: object, expected_type: type, accepted: bool) -> None:
    if find_spec("sqlseed._utils.type_checks") is None:
        pytest.fail("Shared exact-type policy has not been implemented")
    checker = importlib.import_module("sqlseed._utils.type_checks").has_exact_type

    assert checker(value, expected_type) is accepted


def test_type_check_does_not_invoke_instance_or_metaclass_hooks() -> None:
    if find_spec("sqlseed._utils.type_checks") is None:
        pytest.fail("Shared exact-type policy has not been implemented")
    checker = importlib.import_module("sqlseed._utils.type_checks").has_exact_type

    class HostileMeta(type):
        __hash__ = type.__hash__

        def __eq__(cls, other: object) -> bool:
            raise RuntimeError("type equality must not run")

    class Hostile(metaclass=HostileMeta):
        @property
        def __class__(self) -> type:
            raise RuntimeError("instance class lookup must not run")

    value = Hostile()
    assert checker(value, Hostile)
    assert not checker(value, int)
    assert not checker(1, Hostile)
