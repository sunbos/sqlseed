from __future__ import annotations

import pytest

from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.faker_provider import FakerProvider


@pytest.fixture(name="provider", params=["base", "faker", "mimesis"])
def fixture_provider(request: pytest.FixtureRequest) -> BaseProvider:
    if request.param == "faker":
        return FakerProvider()
    if request.param == "mimesis":
        pytest.importorskip("mimesis")
        from sqlseed.generators.mimesis_provider import MimesisProvider

        return MimesisProvider()
    return BaseProvider()


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [(0.005, 0.006), (-0.006, -0.005), (0.291, 0.299), (0.001, 0.001), (0.30000000000000004, 0.301)],
)
def test_float_rejects_ranges_without_a_value_at_requested_precision(
    provider: BaseProvider, minimum: float, maximum: float
) -> None:
    with pytest.raises(ValueError, match="precision"):
        provider.generate("float", min_value=minimum, max_value=maximum, precision=2)


@pytest.mark.parametrize(("minimum", "maximum"), [(2.0, 1.0), (-1.0, -2.0)])
def test_float_rejects_reversed_bounds(provider: BaseProvider, minimum: float, maximum: float) -> None:
    with pytest.raises(ValueError):
        provider.generate("float", min_value=minimum, max_value=maximum)


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        (0.291, 0.309, 0.3),
        (-0.309, -0.291, -0.3),
        (0.29, 0.29, 0.29),
        (0.0, 0.0, 0.0),
        (0.29999999999999993, 0.30000000000000004, 0.3),
    ],
)
def test_float_honors_narrow_ranges_and_exact_decimal_endpoints(
    provider: BaseProvider, minimum: float, maximum: float, expected: float
) -> None:
    provider.set_seed(1)
    values = [provider.generate("float", min_value=minimum, max_value=maximum, precision=2) for _ in range(12)]
    assert values == [expected] * 12
    assert all(minimum <= value <= maximum for value in values)


@pytest.mark.parametrize(("minimum", "maximum"), [(0.005, 0.035), (-0.035, -0.005)])
def test_float_rounding_stays_in_the_requested_closed_interval(
    provider: BaseProvider, minimum: float, maximum: float
) -> None:
    provider.set_seed(9)
    values = [provider.generate("float", min_value=minimum, max_value=maximum, precision=2) for _ in range(50)]
    assert all(minimum <= value <= maximum for value in values)
    assert all(round(value, 2) == value for value in values)
    assert len(set(values)) > 1


@pytest.mark.parametrize(("minimum", "maximum"), [(float("nan"), 1.0), (0.0, float("inf")), (-float("inf"), 0.0)])
def test_float_rejects_non_finite_bounds(provider: BaseProvider, minimum: float, maximum: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        provider.generate("float", min_value=minimum, max_value=maximum)


def test_float_preserves_the_established_default_seed_sequence(provider: BaseProvider) -> None:
    # Captured before correcting the range boundaries: normal generation must
    # continue using each provider's native RNG and consume the same draws.
    expected = {
        "base": [279815.19, 502139.94, 564147.25, 460961.4],
        "faker": [293407.15, 526532.61, 591551.23, 483353.38],
        "mimesis": [279815.19, 502139.94, 564147.25, 460961.4],
    }
    provider.set_seed(73)
    assert [provider.generate("float") for _ in range(4)] == expected[provider.name]


def test_text_rejects_reversed_length_bounds(provider: BaseProvider) -> None:
    with pytest.raises(ValueError):
        provider.generate("text", min_length=20, max_length=4)
