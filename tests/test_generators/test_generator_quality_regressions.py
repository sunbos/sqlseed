"""Real-provider regressions from the September 2026 generator audit."""

from __future__ import annotations

import json
import random
from typing import Any

import pytest

from sqlseed._utils.type_checks import has_exact_type
from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.faker_provider import FakerProvider
from sqlseed.generators.mimesis_provider import MimesisProvider


def _provider(provider_type: type[BaseProvider], locale: str) -> BaseProvider:
    if provider_type is MimesisProvider:
        pytest.importorskip("mimesis")
    provider = provider_type()
    provider.set_locale(locale)
    provider.set_seed(1707)
    return provider


@pytest.mark.parametrize("locale", ["zh_CN", "zh"])
def test_mimesis_chinese_name_is_surname_then_given_name(locale: str) -> None:
    mimesis = pytest.importorskip("mimesis")
    provider = _provider(MimesisProvider, locale)
    person = mimesis.Generic("zh", seed=1707).person
    actual = []
    for _ in range(25):
        given_name = person.name()
        surname = person.surname()
        value = provider.generate("name")
        assert value == surname + given_name
        assert not any(char.isspace() for char in value)
        actual.append(value)
    repeated = _provider(MimesisProvider, locale)
    assert actual == [repeated.generate("name") for _ in range(25)]


def test_mimesis_english_name_keeps_native_format() -> None:
    mimesis = pytest.importorskip("mimesis")
    provider = _provider(MimesisProvider, "en_US")
    person = mimesis.Generic("en", seed=1707).person
    assert [provider.generate("name") for _ in range(25)] == [person.full_name() for _ in range(25)]


@pytest.mark.parametrize("locale", ["en_US", "zh_CN"])
@pytest.mark.parametrize("bounds", [(1, 4), (10, 10), (50, 50), (50, 200)])
def test_faker_text_respects_short_and_exact_lengths(locale: str, bounds: tuple[int, int]) -> None:
    provider = _provider(FakerProvider, locale)
    params = {"min_length": bounds[0], "max_length": bounds[1]}
    actual = [provider.generate("text", **params) for _ in range(25)]
    assert all(bounds[0] <= len(value) <= bounds[1] for value in actual)
    repeated = _provider(FakerProvider, locale)
    assert actual == [repeated.generate("text", **params) for _ in range(25)]


@pytest.mark.parametrize("locale", ["en_US", "zh_CN"])
def test_faker_text_rejects_inverted_bounds(locale: str) -> None:
    provider = _provider(FakerProvider, locale)
    with pytest.raises(ValueError, match="min_length"):
        provider.generate("text", min_length=11, max_length=10)


@pytest.mark.parametrize("locale", ["en_US", "zh_CN"])
def test_faker_json_schema_uses_shared_recursive_types(locale: str) -> None:
    provider = _provider(FakerProvider, locale)
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "nested": {"type": "array", "items": {"type": "boolean"}},
            "details": {"type": "object", "properties": {"label": {"type": "string"}}},
        },
    }
    samples = [provider.generate("json", schema=schema) for _ in range(25)]
    for sample in samples:
        value = json.loads(sample)
        assert set(value) == {"count", "nested", "details"}
        assert has_exact_type(value["count"], int)
        assert value["nested"] and all(has_exact_type(item, bool) for item in value["nested"])
        assert has_exact_type(value["details"]["label"], str)
    repeated = _provider(FakerProvider, locale)
    assert samples == [repeated.generate("json", schema=schema) for _ in range(25)]


@pytest.mark.parametrize("provider_type", [BaseProvider, FakerProvider, MimesisProvider])
@pytest.mark.parametrize("locale", ["en_US", "zh_CN"])
def test_weighted_choices_list_preserves_weights_and_seed(provider_type: type[BaseProvider], locale: str) -> None:
    provider = _provider(provider_type, locale)
    entries: list[dict[str, Any]] = [
        {"value": "never", "weight": 0},
        {"value": "rare", "weight": 0.25},
        {"value": "common", "weight": 2.5},
    ]
    expected_rng = random.Random(1707)
    expected = [expected_rng.choices(["never", "rare", "common"], weights=[0, 0.25, 2.5], k=1)[0] for _ in range(50)]
    actual = [provider.generate("weighted_choice", weighted_choices=entries) for _ in range(50)]
    assert actual == expected
    assert "never" not in actual
    legacy = _provider(provider_type, locale)
    assert actual == [legacy.generate("weighted_choice", choices=entries) for _ in range(50)]


def test_faker_locale_aliases_follow_current_locale_after_switch() -> None:
    from faker import Faker

    provider = FakerProvider()
    for locale, state_method, zip_method in (
        ("zh_CN", "province", "postcode"),
        ("en_US", "state", "zipcode"),
        ("zh_CN", "province", "postcode"),
    ):
        provider.set_locale(locale)
        provider.set_seed(1707)
        native = Faker(locale)
        native.seed_instance(1707)
        for _ in range(10):
            assert provider.generate("state") == getattr(native, state_method)()
            assert provider.generate("zip_code") == getattr(native, zip_method)()
