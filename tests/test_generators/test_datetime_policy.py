"""Date generation keeps introspection, counter policy and late-bound aliases."""

from __future__ import annotations

import importlib
import inspect
from datetime import date, datetime, time
from importlib.util import find_spec
from types import MethodType
from typing import get_type_hints

import pytest

from sqlseed.generators._native_provider import NativeProvider
from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.faker_provider import FakerProvider


def test_date_method_policy_belongs_to_the_bound_implementation() -> None:
    if find_spec("sqlseed.generators._datetime_methods") is None:
        pytest.fail("Shared date method policies have not been implemented")
    methods = importlib.import_module("sqlseed.generators._datetime_methods")
    provider = NativeProvider()
    provider.set_seed(42)
    native = MethodType(methods.date_method(count_placeholder=False), provider)
    fallback = MethodType(methods.date_method(count_placeholder=True), provider)

    assert isinstance(native(start_date="2024-01-01", end_date="2024-01-01"), date)
    assert provider._counter == 0
    assert fallback(start_date="2024-01-01", end_date="2024-01-01") == date(2024, 1, 1)
    assert provider._counter == 1


@pytest.mark.parametrize("provider_type", [BaseProvider, NativeProvider])
@pytest.mark.parametrize("kind", ["date", "datetime", "time", "timestamp"])
def test_datetime_methods_preserve_strict_introspectable_parameters(
    provider_type: type[BaseProvider], kind: str
) -> None:
    provider = provider_type()
    method = getattr(provider, f"_gen_{kind}")
    expected = {}
    if kind != "time":
        expected.update(start_year=2000, end_year=None, start_date=None, end_date=None)
    if kind != "date":
        expected.update(all_day=True, start_time=None, end_time=None)
    if kind != "time":
        expected["weekdays"] = "all"
    parameters = inspect.signature(method).parameters
    assert list(parameters) == list(expected)
    assert {name: parameter.default for name, parameter in parameters.items()} == expected
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters.values())
    hints = get_type_hints(method)
    assert hints["return"] is {"date": date, "datetime": datetime, "time": time, "timestamp": datetime}[kind]
    if kind != "time":
        assert hints["start_year"] is int
        assert hints["weekdays"] == str | list[int] | None
    if kind != "date":
        assert hints["all_day"] is bool
    before_rng = provider._rng.getstate()
    with pytest.raises(TypeError):
        method(unknown_parameter=1)
    assert provider._counter == 0
    assert provider._rng.getstate() == before_rng


@pytest.mark.parametrize("provider_type", [BaseProvider, NativeProvider])
def test_timestamp_uses_the_current_datetime_override(
    monkeypatch: pytest.MonkeyPatch, provider_type: type[BaseProvider]
) -> None:
    provider = provider_type()
    returned = datetime(2024, 2, 3, 4, 5, 6)
    parameters: list[dict] = []

    def replacement(**kwargs: object) -> datetime:
        parameters.append(kwargs)
        return returned

    monkeypatch.setattr(provider, "_gen_datetime", replacement)
    assert provider._gen_timestamp(start_year=2024, weekdays=[1, 3]) is returned
    assert parameters == [
        {
            "start_year": 2024,
            "end_year": None,
            "start_date": None,
            "end_date": None,
            "all_day": True,
            "start_time": None,
            "end_time": None,
            "weekdays": [1, 3],
        }
    ]
    assert provider._counter == 0


@pytest.mark.parametrize(
    "missing",
    [{"date_between_dates"}, {"date_time_between_dates"}, {"date_between_dates", "date_time_between_dates"}],
)
def test_faker_locale_fallback_keeps_counter_policy_when_installed_and_removed(missing: set[str]) -> None:
    provider = FakerProvider()
    original = provider._faker

    class LimitedLocale:
        def __getattr__(self, name: str):
            if name in missing:
                raise AttributeError(name)
            return getattr(original, name)

    provider._faker = LimitedLocale()
    provider._install_locale_fallbacks()
    bounds = {"start_date": "2024-01-01", "end_date": "2024-01-01"}
    assert provider._gen_date(**bounds) == date(2024, 1, 1)
    assert provider._counter == int("date_between_dates" in missing)
    provider._gen_datetime(**bounds)
    provider._gen_timestamp(**bounds)
    expected_counter = int("date_between_dates" in missing) + 2 * int("date_time_between_dates" in missing)
    assert provider._counter == expected_counter

    provider._faker = original
    provider._install_locale_fallbacks()
    assert provider._gen_date(**bounds) == date(2024, 1, 1)
    provider._gen_datetime(**bounds)
    provider._gen_timestamp(**bounds)
    assert provider._counter == expected_counter
    assert all(name not in provider.__dict__ for name in ("_gen_date", "_gen_datetime", "_gen_timestamp"))


@pytest.mark.parametrize("kind", ["date", "datetime", "time", "timestamp"])
def test_ai_candidate_validation_reads_generator_annotations_without_drawing(kind: str) -> None:
    pytest.importorskip("sqlseed_ai")
    from sqlseed_ai.healer.candidate_validation import _validate_builtin_params

    from sqlseed.config.models import ColumnConfig

    provider = BaseProvider()
    method = getattr(provider, f"_gen_{kind}")
    parameter, value = ("all_day", False) if kind == "time" else ("start_year", 2024)
    before_rng = provider._rng.getstate()
    _validate_builtin_params(ColumnConfig(name="value", generator=kind, params={parameter: value}), "items", method)
    column_config = ColumnConfig(name="value", generator=kind, params={parameter: "invalid"})
    with pytest.raises(ValueError, match=r"invalid .* params"):
        _validate_builtin_params(column_config, "items", method)
    assert provider._counter == 0
    assert provider._rng.getstate() == before_rng
