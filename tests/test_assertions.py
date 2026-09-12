"""Preserve collection shape when asserting empty results."""

from __future__ import annotations

import pytest

from tests.assertions import assert_empty


@pytest.mark.parametrize(("value", "expected_type"), [([], list), ({}, dict), ((), tuple)])
def test_accepts_empty_collection_of_expected_type(value: object, expected_type: type) -> None:
    assert_empty(value, expected_type)


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [(None, list), (False, list), ({}, list), ([], dict), ([], tuple), ("", list)],
)
def test_rejects_falsy_values_of_wrong_type(value: object, expected_type: type) -> None:
    with pytest.raises(AssertionError, match="Expected"):
        assert_empty(value, expected_type)


@pytest.mark.parametrize(("value", "expected_type"), [([1], list), ({"key": 1}, dict), ((1,), tuple)])
def test_rejects_nonempty_collection(value: object, expected_type: type) -> None:
    with pytest.raises(AssertionError, match="empty"):
        assert_empty(value, expected_type)


def test_accepts_list_subclasses() -> None:
    class Results(list):
        pass

    assert_empty(Results(), list)
