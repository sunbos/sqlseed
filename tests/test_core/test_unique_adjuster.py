from __future__ import annotations

import string
from dataclasses import replace
from inspect import signature
from unittest.mock import MagicMock

import pytest
from structlog.testing import capture_logs

from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.unique_adjuster import UniqueAdjuster
from sqlseed.database._protocol import CheckConstraintInfo
from sqlseed.generators._protocol import ConfigurationError
from sqlseed.generators.base_provider import BaseProvider

# Import the shared ColumnInfo factory from tests.conftest to avoid
# CodeDuplication with test_plugin_mediator.py (both files previously
# defined an identical _make_col_info helper).
from tests.conftest import make_col_info_varchar as _make_col_info


def _checks(*expressions: str) -> list[CheckConstraintInfo]:
    return [CheckConstraintInfo(name="", table="items", columns=(), expression=expr) for expr in expressions]


def _adjust_nullable_rank(expression: str) -> GeneratorSpec:
    """Infer a five-value unique integer domain from a nullable skip mapping."""
    column = _make_col_info("rank", "INTEGER", nullable=True)
    return UniqueAdjuster(ColumnMapper()).adjust(
        {"rank": GeneratorSpec(generator_name="skip")}, {"rank"}, 5, [column], _checks(expression)
    )["rank"]


class TestUniqueAdjuster:
    @pytest.mark.parametrize("generator,params", [("string", {"min_length": 0, "max_length": 0}), ("integer", {})])
    def test_zero_rows_need_no_domain_adjustment(self, generator: str, params: dict[str, int]) -> None:
        original = GeneratorSpec(generator_name=generator, params=params)
        adjusted = UniqueAdjuster(ColumnMapper()).adjust({"code": original}, {"code"}, 0)

        assert adjusted == {"code": original}

    @pytest.mark.parametrize(
        "charset,min_length,max_length,capacity",
        [("", 0, 0, 1), ("", 1, 5, 0), ("aaa", 1, 5, 5), ("x", 3, 3, 1)],
    )
    def test_degenerate_string_capacity_is_checked_before_generation(
        self, charset: str, min_length: int, max_length: int, capacity: int
    ) -> None:
        """Empty and one-character alphabets have exact, finite value domains."""
        params = {"charset": charset, "min_length": min_length, "max_length": max_length}
        spec = GeneratorSpec(generator_name="string", params=params)
        adjuster = UniqueAdjuster(ColumnMapper())
        if capacity:
            adjusted = adjuster.adjust({"code": spec}, {"code"}, capacity)
            assert adjusted["code"].params == params
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, capacity + 1)

    def test_adjust_string_increases_min_length(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"code": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, {"code"}, 10000)
        # The default alphabet includes letters, digits, space, underscore and hyphen.
        # The weak `> 1` assertion previously let mutants in the log/charset_size
        # math survive (mutmut baseline 2026-06-25). Pin to the exact computed value.
        assert result["code"].params["min_length"] == 6

    def test_adjust_integer_expands_range(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 100})}
        result = adjuster.adjust(specs, {"id"}, 10000)
        # Exact value: max_value = min_val + count * 10 = 0 + 100000 = 100000.
        # The weak `> 100` assertion previously let mutants in
        # `params["max_value"] = min_val + count * 10` survive.
        assert result["id"].params["max_value"] == 100000

    def test_adjust_skip_column_unchanged(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"name": GeneratorSpec(generator_name="string", params={"min_length": 5, "max_length": 50})}
        result = adjuster.adjust(specs, {"name"}, 100)
        assert result["name"].params["min_length"] == 5

    def test_adjust_skips_skip_generator(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="skip")}
        result = adjuster.adjust(specs, {"id"}, 1000)
        assert result["id"].generator_name == "skip"

    def test_adjust_string_with_digits_charset(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 20, "charset": "digits"},
            )
        }
        result = adjuster.adjust(specs, {"code"}, 1000)
        # Exact value: charset_size=10, min_needed = ceil(log(1000^2 * 50) / log(10))
        # = ceil(7.7) = 8. Pins the charset_size=10 constant and the math formula.
        assert result["code"].params["min_length"] == 8

    def test_adjust_string_with_alpha_charset(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 50, "charset": "alpha"},
            )
        }
        result = adjuster.adjust(specs, {"code"}, 1000)
        # Exact value: charset_size=52, min_needed = ceil(log(1000^2 * 50) / log(52))
        # = ceil(4.55) = 5. Pins the charset_size=52 constant.
        assert result["code"].params["min_length"] == 5

    def test_adjust_integer_range_already_sufficient(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 999999})}
        result = adjuster.adjust(specs, {"id"}, 100)
        assert result["id"].params["max_value"] == 999999

    def test_adjust_non_unique_column_unchanged(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"name": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, set(), 10000)
        assert result["name"].params["min_length"] == 1

    def test_adjust_column_not_in_specs(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"name": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, {"nonexistent"}, 10000)
        assert "nonexistent" not in result

    def test_adjust_string_applies_setdefault_defaults_when_params_omitted(self) -> None:
        """Verify setdefault("max_length", 50) and setdefault("min_length", 1) fire.

        When the spec has NO min_length / max_length keys, _adjust_string must
        apply the defaults (50 and 1 respectively). Without this test, mutmut
        survivors like `setdefault("max_length", 50)` -> `setdefault("XXmax_lengthXX", 50)`
        pass undetected because every other test pre-sets both keys.
        """
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        # params is empty — both setdefault calls must fire.
        specs = {"code": GeneratorSpec(generator_name="string", params={})}
        # One requested value fits the default minimum length.
        result = adjuster.adjust(specs, {"code"}, 1)
        assert result["code"].params["max_length"] == 50  # setdefault default
        assert result["code"].params["min_length"] == 1  # setdefault default

    def test_adjust_string_without_charset_uses_the_default_alphabet(self) -> None:
        """The inferred length accounts for the provider's default character set."""
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        # No charset key: the real provider supports 65 distinct characters.
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 50},
            )
        }
        result = adjuster.adjust(specs, {"code"}, 1000)
        assert result["code"].params["min_length"] == 5


class TestAdjustChoiceFallback:
    """Tests for _adjust_choice fallback path (lines 59, 160-175).

    These tests use a *real* ``ColumnMapper`` (no MagicMock) so that
    ``_type_faithful_fallback`` actually runs and ``_adjust_string`` /
    ``_adjust_integer`` get exercised end-to-end through the recursive
    ``adjust`` call. Earlier versions mocked ``mapper.map_column`` and only
    asserted ``assert_called_once_with(...)``, which made the tests
    self-proving: the assertion merely echoed the mock setup and never
    verified the actual computed ``GeneratorSpec.params``. mutmut confirmed
    this by reporting ~60 surviving mutants in ``_adjust_string`` and
    ``_adjust_integer`` (lines 74-143) on 2026-06-25.

    To trigger the real ``force_type_infer=True`` branch in ``map_column``,
    the column name must NOT match any built-in exact-match rule (so we use
    ``"category"`` / ``"rank"`` instead of ``"status"`` / ``"priority"``,
    which are built-in choice rules), and ``column_info.default`` must be
    non-None (so ``_map_from_default`` enters the ``force_type_infer`` arm
    rather than returning ``None``).
    """

    @pytest.mark.parametrize("count", [3, 5], ids=["spare-capacity", "exact-capacity"])
    def test_adjust_choice_with_sufficient_choices_no_fallback(self, count: int) -> None:
        # When choices >= count, no fallback needed
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a", "b", "c", "d", "e"]},
            )
        }
        col_infos = [_make_col_info("status", "VARCHAR(10)", default="pending")]
        result = adjuster.adjust(specs, {"status"}, count, col_infos)
        # Should remain choice with same choices
        assert result["status"].generator_name == "choice"
        assert result["status"].params["choices"] == ["a", "b", "c", "d", "e"]

    def test_adjust_choice_with_insufficient_choices_triggers_fallback(self) -> None:
        # When choices < count AND column_info available, fallback to type inference.
        # Use a column name with NO built-in exact-match rule ("category") and a
        # non-None default so the real map_column(force_type_infer=True) reaches
        # _type_faithful_fallback. VARCHAR IS in TYPE_FALLBACK_RULES so length is
        # preserved: _type_faithful_fallback("VARCHAR(20)") returns
        # {"min_length": 1, "max_length": 20}. _adjust_string then expands
        # min_length to satisfy uniqueness for count=10000 over the default alphabet.
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "category": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a", "b"]},
            )
        }
        col_infos = [_make_col_info("category", "VARCHAR(20)", default="pending")]
        result = adjuster.adjust(specs, {"category"}, 10000, col_infos)
        # Real fallback path: choice → string with expanded min_length
        assert result["category"].generator_name == "string"
        # _adjust_string must have run: min_length grows above the 1 default
        # to 6.
        # This guards against mutants in the min_needed formula and the
        # `max(current_min, min_needed)` assignment.
        assert result["category"].params["min_length"] == 6
        # max_length preserved from VARCHAR(20) — guards against the
        # `params.setdefault("max_length", 50)` -> `setdefault("XXmax_lengthXX", 50)` mutant
        # and the `length_match` regex mutant.
        assert result["category"].params["max_length"] == 20

    def test_adjust_choice_without_column_info_no_fallback(self) -> None:
        # When no column_infos provided, cannot fallback — choices stay as is
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a", "b"]},
            )
        }
        # column_infos=None
        result = adjuster.adjust(specs, {"status"}, 100, None)
        assert result["status"].generator_name == "choice"
        assert result["status"].params["choices"] == ["a", "b"]

    def test_adjust_choice_column_info_not_found_no_fallback(self) -> None:
        # column_infos provided but doesn't contain the target column
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a", "b"]},
            )
        }
        col_infos = [_make_col_info("other_col", "VARCHAR(20)")]
        result = adjuster.adjust(specs, {"status"}, 100, col_infos)
        assert result["status"].generator_name == "choice"

    def test_adjust_choice_fallback_to_skip_no_recursive_adjust(self) -> None:
        # When fallback returns "skip", the `not in {"skip", "choice"}` check is False,
        # so the original choice spec is preserved unchanged (no replacement happens).
        # Use a real PK autoincrement column so map_column returns skip via the
        # `is_primary_key and is_autoincrement` short-circuit at mapper.py:324-327,
        # which fires BEFORE _map_from_default and thus before force_type_infer.
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "category": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a"]},
            )
        }
        col_infos = [_make_col_info("category", "INTEGER", is_primary_key=True, is_autoincrement=True)]
        result = adjuster.adjust(specs, {"category"}, 100, col_infos)
        # Original choice spec preserved (fallback to skip is rejected)
        assert result["category"].generator_name == "choice"
        assert result["category"].params["choices"] == ["a"]

    def test_adjust_choice_fallback_to_choice_no_recursive_adjust(self) -> None:
        # When fallback returns "choice", the `not in {"skip", "choice"}` check is False,
        # so the original choice spec is preserved unchanged (would loop otherwise).
        # This path cannot be triggered via the real map_column because the only
        # way map_column returns "choice" is via _match_exact (e.g., column named
        # "status"); but if the column is named "status", _adjust_choice would never
        # be reached because the original spec was already "choice" from the same
        # exact-match rule. The mock here is therefore intentional and tests an
        # defensive guard against infinite recursion. We assert on the *state*
        # (original spec preserved) rather than the mock call signature.
        mapper = ColumnMapper()
        # Monkey-patch the bound method for testing — this is intentional
        # test behavior to verify the defensive guard against infinite
        # recursion. We assert on the *state* (original spec preserved)
        # rather than the mock call signature.
        mapper.map_column = MagicMock(
            return_value=GeneratorSpec(
                generator_name="choice",
                params={"choices": ["x", "y", "z"]},
            )
        )
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a"]},
            )
        }
        col_infos = [_make_col_info("status", "VARCHAR(10)")]
        result = adjuster.adjust(specs, {"status"}, 100, col_infos)
        # Original choice spec preserved (fallback to choice is rejected to avoid loop)
        assert result["status"].generator_name == "choice"
        assert result["status"].params["choices"] == ["a"]
        # Defensive: also confirm the recursive adjust did not happen — params
        # are byte-for-byte the original, not the mock's ["x","y","z"].
        assert result["status"].params == {"choices": ["a"]}

    def test_adjust_choice_fallback_to_integer_triggers_recursive_adjust(self) -> None:
        # When fallback returns "integer", recursive adjust should expand range.
        # Use a column name "rank" (no exact-match rule) with type="INTEGER" and
        # a non-None default so the real map_column(force_type_infer=True) reaches
        # _type_faithful_fallback("INTEGER") which returns
        # {"min_value": 0, "max_value": 999999} per TYPE_FALLBACK_RULES.
        # _adjust_integer fires when (max_val - min_val) < count * 10:
        #   999999 - 0 = 999999 < 100000 * 10 = 1_000_000  → True → expansion fires
        # → params["max_value"] = min_val + count * 10 = 0 + 1_000_000 = 1_000_000.
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "rank": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a"]},
            )
        }
        col_infos = [_make_col_info("rank", "INTEGER", default=0)]
        result = adjuster.adjust(specs, {"rank"}, 100_000, col_infos)
        # After recursive adjust, integer range should be expanded.
        # This guards against the `min_val = params.get("min_value", 0)` -> "XXmin_valueXX"
        # mutant (#79) and the `params["max_value"] = min_val + count * 10` mutants.
        assert result["rank"].generator_name == "integer"
        assert result["rank"].params["min_value"] == 0
        assert result["rank"].params["max_value"] == 1_000_000


class TestAdjustIntegerTypeSampling:
    """Type names alone do not establish a database-enforced integer capacity."""

    @pytest.mark.parametrize(
        ("col_type", "count", "expected_min_max"),
        [
            ("INT8", 300, 3000),
            ("INT16", 70000, 700000),
            ("INT8", 200, 2000),
        ],
        ids=["int8_large_sample", "int16_large_sample", "int8_small_sample"],
    )
    def test_int_column_range_expanded(
        self,
        col_type: str,
        count: int,
        expected_min_max: int,
    ) -> None:
        """Integer domains remain expandable without a declared CHECK range."""
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "code": GeneratorSpec(
                generator_name="integer",
                params={"min_value": 0, "max_value": 100},
            )
        }
        col_infos = [_make_col_info("code", col_type)]
        with capture_logs() as events:
            result = adjuster.adjust(specs, {"code"}, count, col_infos)
        assert result["code"].params["max_value"] >= expected_min_max
        assert not [event for event in events if event["log_level"] == "warning"]

    def test_integer_column_with_no_col_info_still_adjusts(self) -> None:
        # When col_infos is None, adjustment still happens (no warning path)
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "code": GeneratorSpec(
                generator_name="integer",
                params={"min_value": 0, "max_value": 100},
            )
        }
        result = adjuster.adjust(specs, {"code"}, 10000, None)
        assert result["code"].params["max_value"] >= 100000


class TestAdjustStringEdgeCases:
    """Tests for string adjustment edge cases (line 103)."""

    def test_string_max_length_less_than_min_length_after_adjustment(self) -> None:
        # When min_length adjusted above max_length and charset is already set,
        # the `elif params["max_length"] < params["min_length"]` path triggers
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        # Use digits charset with very small max_length
        # count^2 * 50 = 10000^2 * 50 = 5e9, log(5e9)/log(10) ≈ 9.7 → min_needed = 10
        # max_length=5, so min_length(10) > max_length(5)
        # charset="digits" is set, so the `if params.get("charset") is None` branch is skipped
        # → falls to `elif params["max_length"] < params["min_length"]` → max_length = min_length
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 5, "charset": "digits"},
            )
        }
        result = adjuster.adjust(specs, {"code"}, 10000)
        # max_length should be increased to at least min_length
        assert result["code"].params["max_length"] >= result["code"].params["min_length"]

    def test_string_with_no_charset_gets_alphanumeric_when_overflow(self) -> None:
        # When min_length > max_length and charset is None,
        # charset is set to "alphanumeric" and min_needed is recalculated
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        # Very large count forces min_length > max_length
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 3},  # No charset → defaults to None
            )
        }
        result = adjuster.adjust(specs, {"code"}, 100000)
        # Should have charset set to alphanumeric
        assert result["code"].params.get("charset") == "alphanumeric"


class TestAdjustSkipUnique:
    """Nullable UNIQUE columns must not silently fall through to an all-NULL fill.

    Regression tests for the L8 nullable-skip loophole: a nullable UNIQUE
    column (not PK, no DEFAULT) whose name matches no semantic rule lands on
    the "skip" spec, and SQLite happily accepts 50 NULLs under UNIQUE. The
    adjuster must re-map such columns to a type-faithful generator instead.
    Uses a real ColumnMapper (pitfall #13: no self-proving mocks).
    """

    def test_nullable_unique_skip_remapped_to_type_faithful(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"ssn": GeneratorSpec(generator_name="skip")}
        col = _make_col_info("ssn", "TEXT", nullable=True)
        result = adjuster.adjust(specs, {"ssn"}, 10_000, [col])
        assert result["ssn"].generator_name == "string"
        assert result["ssn"].params == {"min_length": 6, "max_length": 50}

    @pytest.mark.parametrize("generator", ["skip", "autoincrement"])
    def test_nullable_unique_integer_skip_gets_expanded_range(self, generator: str) -> None:
        # Recursion: the integer fallback must also get its value space
        # expanded beyond the inferred domain for the requested 100000 rows.
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"rank": GeneratorSpec(generator_name=generator)}
        col = _make_col_info("rank", "INTEGER", nullable=True)
        result = adjuster.adjust(specs, {"rank"}, 100_000, [col])
        spec = result["rank"]
        assert spec.generator_name == "integer"
        assert spec.params == {"min_value": 0, "max_value": 1_000_000}

    def test_primary_key_skip_untouched(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="skip")}
        col = _make_col_info("id", "INTEGER", nullable=True, is_primary_key=True)
        result = adjuster.adjust(specs, {"id"}, 100, [col])
        assert result["id"].generator_name == "skip"

    def test_default_valued_skip_untouched(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"status": GeneratorSpec(generator_name="skip")}
        col = _make_col_info("status", "TEXT", nullable=True, default="active")
        result = adjuster.adjust(specs, {"status"}, 100, [col])
        assert result["status"].generator_name == "skip"

    def test_not_null_skip_untouched(self) -> None:
        # Non-nullable skip means the DEFAULT-skip level (L4), not the
        # nullable-skip loophole — leave it alone.
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"code": GeneratorSpec(generator_name="skip")}
        col = _make_col_info("code", "TEXT", nullable=False)
        result = adjuster.adjust(specs, {"code"}, 100, [col])
        assert result["code"].generator_name == "skip"

    def test_no_column_info_skip_untouched(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="skip")}
        result = adjuster.adjust(specs, {"id"}, 1000, None)
        assert result["id"].generator_name == "skip"


class TestAdjustIntegerChecks:
    """CHECK bounds remain authoritative when UNIQUE requires more values."""

    @pytest.mark.parametrize(
        "params,expression,capacity",
        [
            ({"min_value": 10, "max_value": 12}, "rank BETWEEN 0 AND 100", 3),
            ({"min_value": 0, "max_value": 100}, "rank BETWEEN 10 AND 12", 3),
            ({"min_value": 10, "max_value": 12}, "rank <= 100", 3),
            ({"min_value": 10, "max_value": 12}, "rank >= 0", 3),
        ],
    )
    def test_nonnullable_bounded_integer_rejects_only_count_above_actual_capacity(
        self, params: dict[str, int], expression: str, capacity: int
    ) -> None:
        spec = GeneratorSpec(generator_name="integer", params=params)
        adjuster = UniqueAdjuster(ColumnMapper())
        adjusted = adjuster.adjust({"rank": spec}, {"rank"}, capacity, check_constraints=_checks(expression))
        assert adjusted["rank"].params == {"min_value": 10, "max_value": 12}
        check_constraints = _checks(expression)
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"rank": spec}, {"rank"}, capacity + 1, check_constraints=check_constraints)

    @pytest.mark.parametrize("count", [1, 10, 100])
    def test_check_bounds_apply_even_when_unclamped_range_has_sampling_room(self, count: int) -> None:
        original = GeneratorSpec(generator_name="integer", params={"min_value": -1000, "max_value": 1000})
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": original}, {"rank"}, count, check_constraints=_checks("rank BETWEEN 10 AND 200")
        )["rank"]

        assert result.params == {"min_value": 10, "max_value": 200}
        provider = BaseProvider()
        provider.set_seed(42)
        assert all(10 <= provider.generate("integer", **result.params) <= 200 for _ in range(100))
        assert original.params == {"min_value": -1000, "max_value": 1000}

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("rank >= 18 AND rank <= 65", (18, 65)),
            ("rank > 18 AND rank < 65", (19, 64)),
            ("rank >= 18.2 AND rank <= 65.8", (19, 65)),
            ("rank > -3.2 AND rank < -0.2", (-3, -1)),
            ("rank > -3 AND rank < 0", (-2, -1)),
            ("rank >= 18", (18, 100)),
            ("rank <= 65", (-100, 65)),
        ],
    )
    def test_integer_range_obeys_inclusive_exclusive_and_one_sided_checks(
        self, expression: str, expected: tuple[int, int]
    ) -> None:
        original = GeneratorSpec(
            generator_name="integer",
            params={"min_value": -100, "max_value": 100},
            null_ratio=0.2,
            provider="base",
        )
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": original}, {"rank"}, 30, check_constraints=_checks(expression)
        )["rank"]

        assert result.params == {"min_value": expected[0], "max_value": expected[1]}
        assert (result.null_ratio, result.provider) == (0.2, "base")
        assert original.params == {"min_value": -100, "max_value": 100}

    @pytest.mark.parametrize("reverse", [False, True])
    def test_intersects_all_ranges_after_unrelated_and_non_range_checks(self, reverse: bool) -> None:
        ranges = ["rank >= 10", "rank > 18.2", "rank <= 70", "rank < 66"]
        if reverse:
            ranges.reverse()
        checks = _checks("other >= 1000", "rank IN (20, 21)", "rank < ceiling", *ranges)
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 100})},
            {"rank"},
            30,
            check_constraints=checks,
        )["rank"]

        assert result.params == {"min_value": 19, "max_value": 65}

    def test_nullable_check_domain_does_not_expand_narrower_user_range(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {
                "rank": GeneratorSpec(
                    generator_name="integer", params={"min_value": 20, "max_value": 30}, null_ratio=0.2
                )
            },
            {"rank"},
            100,
            check_constraints=_checks("rank >= 18 AND rank <= 65"),
        )["rank"]

        assert result.params == {"min_value": 20, "max_value": 30}

    @pytest.mark.parametrize("expression", ["other >= 18", "rank IN (18, 19)", "rank < ceiling"])
    def test_unrelated_or_non_range_check_does_not_disable_integer_expansion(self, expression: str) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"min_value": 37, "max_value": 40})},
            {"rank"},
            10,
            check_constraints=_checks(expression),
        )["rank"]

        assert result.params == {"min_value": 37, "max_value": 137}


class TestAdjustFallbackChecks:
    """Real type inference must retain CHECK domains through recursive adjustment."""

    @pytest.mark.parametrize(("col_type", "expression"), [("INTEGER", "rank <= 100"), ("INT64", "rank >= 5")])
    def test_one_sided_check_preserves_unconstrained_type_domain_endpoint(self, col_type: str, expression: str) -> None:
        mapper = ColumnMapper()
        column = _make_col_info("rank", col_type, nullable=True)
        inferred = mapper.map_column(column, force_type_infer=True)
        result = UniqueAdjuster(mapper).adjust(
            {"rank": GeneratorSpec(generator_name="skip")}, {"rank"}, 5, [column], _checks(expression)
        )["rank"]

        free_endpoint = "min_value" if "<=" in expression else "max_value"
        assert result.params[free_endpoint] == inferred.params[free_endpoint]

    @pytest.mark.parametrize("expression", ["rank <= -1000000", "rank >= 1000000"])
    def test_one_sided_fallback_uses_same_sampling_width_as_unbounded_integer(self, expression: str) -> None:
        adjuster = UniqueAdjuster(ColumnMapper())
        unbounded = adjuster.adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 0})},
            {"rank"},
            5,
        )["rank"]
        fallback = adjuster.adjust(
            {"rank": GeneratorSpec(generator_name="skip")},
            {"rank"},
            5,
            [_make_col_info("rank", "INTEGER", nullable=True)],
            _checks(expression),
        )["rank"]

        assert fallback.params["max_value"] - fallback.params["min_value"] == (
            unbounded.params["max_value"] - unbounded.params["min_value"]
        )

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("rank >= 18 AND rank <= 65", (18, 65)),
            ("rank >= -100 AND rank <= -1", (-100, -1)),
            ("rank >= 1000000 AND rank <= 1000010", (1000000, 1000010)),
        ],
    )
    def test_nullable_skip_infers_integer_inside_check_domain(self, expression: str, expected: tuple[int, int]) -> None:
        result = _adjust_nullable_rank(expression)

        assert result.generator_name == "integer"
        assert result.params == {"min_value": expected[0], "max_value": expected[1]}

    @pytest.mark.parametrize(
        ("expression", "bound_name", "bound"),
        [("rank >= 1000000", "min_value", 1000000), ("rank <= -1", "max_value", -1)],
    )
    def test_nullable_one_sided_check_outside_default_domain_retains_usable_range(
        self, expression: str, bound_name: str, bound: int
    ) -> None:
        result = _adjust_nullable_rank(expression)

        assert result.generator_name == "integer"
        assert result.params[bound_name] == bound
        assert result.params["max_value"] - result.params["min_value"] >= 4

    def test_choice_fallback_adopts_check_before_testing_unique_capacity(self) -> None:
        column = _make_col_info("rank", "INTEGER", nullable=False, default=0)
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="choice", params={"choices": [18]}, null_ratio=0.2)},
            {"rank"},
            5,
            [column],
            _checks("rank >= 18 AND rank <= 65"),
        )["rank"]

        assert result.generator_name == "integer"
        assert result.params == {"min_value": 18, "max_value": 65}
        assert result.null_ratio == 0.2


class TestAdjustTraversalAndRecursion:
    @pytest.mark.parametrize("skipped_generator", [None, "skip", "autoincrement"])
    @pytest.mark.parametrize("skipped_name", ["left_column", "right_column"])
    def test_omitted_or_generated_column_does_not_stop_other_unique_adjustments(
        self, skipped_generator: str | None, skipped_name: str
    ) -> None:
        # Swap the roles so both iteration orders of the real set are covered.
        names = {"left_column", "right_column"}
        generated_name = next(name for name in names if name != skipped_name)
        specs = {generated_name: GeneratorSpec(generator_name="integer", params={"min_value": 37, "max_value": 40})}
        if skipped_generator is not None:
            specs[skipped_name] = GeneratorSpec(generator_name=skipped_generator)
        columns = [
            _make_col_info(skipped_name, "INTEGER", is_primary_key=True, is_autoincrement=True),
            _make_col_info(generated_name, "INTEGER", nullable=False),
        ]
        result = UniqueAdjuster(ColumnMapper()).adjust(specs, names, 8, columns)

        params = result[generated_name].params
        assert params["min_value"] == 37
        assert params["max_value"] - params["min_value"] + 1 >= 8
        if skipped_generator is None:
            assert skipped_name not in result
        else:
            assert result[skipped_name].generator_name == skipped_generator

    def test_computed_nullable_unique_column_remains_database_generated(self) -> None:
        column = replace(_make_col_info("rank", "INTEGER", nullable=True), is_computed=True)
        original = GeneratorSpec(generator_name="skip")
        result = UniqueAdjuster(ColumnMapper()).adjust({"rank": original}, {"rank"}, 100, [column])

        assert result["rank"] is original

    def test_auto_allocated_fallback_stops_without_recursive_remapping(self) -> None:
        # The real mapper's id pattern returns autoincrement even without PK metadata.
        column = _make_col_info("id", "INTEGER", nullable=True)
        original = GeneratorSpec(generator_name="skip")
        result = UniqueAdjuster(ColumnMapper()).adjust({"id": original}, {"id"}, 100, [column])

        assert result["id"] is original


class TestAdjustedStringBehavior:
    @pytest.mark.parametrize("count", [69, 70, 1000])
    @pytest.mark.parametrize("bound_source", ["VARCHAR(3)", "CHECK"])
    def test_string_batch_preserves_declared_length_budget(self, count: int, bound_source: str) -> None:
        spec = GeneratorSpec(
            generator_name="string", params={"min_length": 1, "max_length": 3, "charset": "alphanumeric"}
        )
        columns = [_make_col_info("code", "VARCHAR(3)")] if bound_source != "CHECK" else None
        checks = _checks("length(code) <= 3") if bound_source == "CHECK" else None
        adjusted = UniqueAdjuster(ColumnMapper()).adjust({"code": spec}, {"code"}, count, columns, checks)["code"]

        assert adjusted.params["max_length"] <= 3
        provider = BaseProvider()
        provider.set_seed(42)
        values = [provider.generate("string", **adjusted.params) for _ in range(count)]
        assert all(len(value) <= 3 for value in values)

    @pytest.mark.parametrize("column_type", ["VARCHAR(2)", "CHAR(2)"])
    def test_bounded_string_capacity_includes_all_allowed_lengths(self, column_type: str) -> None:
        spec = GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 2, "charset": "01"})
        columns = [_make_col_info("code", column_type)]
        adjuster = UniqueAdjuster(ColumnMapper())
        adjusted = adjuster.adjust({"code": spec}, {"code"}, 6, columns)["code"]

        assert adjusted.params == spec.params
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, 7, columns)

    def test_digits_with_sampling_headroom_keep_six_character_domain(self) -> None:
        # A million six-digit values provide the existing sampling headroom
        # for 141 rows without expanding the user's configured upper length.
        spec = GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 6, "charset": "digits"})
        adjusted = UniqueAdjuster(ColumnMapper()).adjust({"code": spec}, {"code"}, 141)["code"]

        assert adjusted.params == {"min_length": 6, "max_length": 6, "charset": "digits"}

    @pytest.mark.parametrize("count,min_length", [(4, 2), (5, 1)])
    def test_bounded_string_retains_shorter_lengths_only_when_needed(self, count: int, min_length: int) -> None:
        # Four binary pairs fit at length two. A fifth distinct value needs
        # the shorter allowed strings to remain in the generation domain.
        spec = GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 2, "charset": "01"})
        columns = [_make_col_info("code", "VARCHAR(2)")]
        adjusted = UniqueAdjuster(ColumnMapper()).adjust({"code": spec}, {"code"}, count, columns)["code"]

        assert adjusted.params == {"min_length": min_length, "max_length": 2, "charset": "01"}

    @pytest.mark.parametrize("reverse", [False, True])
    def test_string_schema_bounds_intersect_without_using_other_columns(self, reverse: bool) -> None:
        checks = _checks("length(other) <= 1", "code < ceiling", "length(code) <= 3", "length(code) > 1")
        if reverse:
            checks.reverse()
        spec = GeneratorSpec(generator_name="string", params={"min_length": 0, "max_length": 10, "charset": "01"})
        columns = [_make_col_info("other", "VARCHAR(1)"), _make_col_info("code", "VARCHAR(4)")]
        adjuster = UniqueAdjuster(ColumnMapper())
        result = adjuster.adjust({"code": spec}, {"code"}, 12, columns, checks)["code"]

        assert result.params == {"min_length": 2, "max_length": 3, "charset": "01"}
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, 13, columns, checks)

    def test_string_lower_check_applies_without_an_upper_check(self) -> None:
        spec = GeneratorSpec(generator_name="string", params={"min_length": 0, "max_length": 10, "charset": "01"})
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"code": spec}, {"code"}, 1, check_constraints=_checks("length(code) >= 8")
        )["code"]

        assert result.params == {"min_length": 8, "max_length": 10, "charset": "01"}

    def test_string_length_domain_with_no_schema_intersection_is_rejected(self) -> None:
        spec = GeneratorSpec(generator_name="string", params={"min_length": 4, "max_length": 8})
        adjuster = UniqueAdjuster(ColumnMapper())
        columns = [_make_col_info("code", "CHAR(3)")]
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, 1, columns)

    @pytest.mark.parametrize("min_length,max_length,capacity", [(2, 2, 4), (0, 0, 1)])
    def test_fixed_string_domain_has_exact_capacity(self, min_length: int, max_length: int, capacity: int) -> None:
        spec = GeneratorSpec(
            generator_name="string", params={"min_length": min_length, "max_length": max_length, "charset": "01"}
        )
        checks = _checks(f"length(code) <= {max_length}")
        adjuster = UniqueAdjuster(ColumnMapper())
        assert (
            adjuster.adjust({"code": spec}, {"code"}, capacity, check_constraints=checks)["code"].params == spec.params
        )
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, capacity + 1, check_constraints=checks)

    def test_large_bounded_string_capacity_uses_exact_integer_arithmetic(self) -> None:
        # 2**55 - 1 lies above float's exact integer range. Planning must not
        # round the capacity upward and admit one impossible extra value.
        spec = GeneratorSpec(generator_name="string", params={"min_length": 0, "max_length": 54, "charset": "01"})
        capacity = 2**55 - 1
        columns = [_make_col_info("code", "VARCHAR(54)")]
        adjuster = UniqueAdjuster(ColumnMapper())
        assert adjuster.adjust({"code": spec}, {"code"}, capacity, columns)["code"].params == spec.params
        with pytest.raises(ConfigurationError):
            adjuster.adjust({"code": spec}, {"code"}, capacity + 1, columns)

    @pytest.mark.parametrize(
        ("canonical", "alias", "count"),
        [
            ("digits", "numeric", 1000),
            ("digits", "numbers", 1000),
            ("digits", string.digits, 1000),
            ("alpha", "letters", 500),
            ("alpha", "ascii_letters", 500),
            ("alpha", string.ascii_letters, 500),
            ("alphanumeric", "alphanum", 1000),
        ],
    )
    def test_equivalent_character_sets_have_identical_bounds_and_seeded_output(
        self, canonical: str, alias: str, count: int
    ) -> None:
        specs = {
            name: GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 1, "charset": charset})
            for name, charset in (("canonical_code", canonical), ("alias_code", alias))
        }
        adjusted = UniqueAdjuster(ColumnMapper()).adjust(specs, set(specs), count)
        canonical_params = adjusted["canonical_code"].params
        alias_params = adjusted["alias_code"].params
        assert (alias_params["min_length"], alias_params["max_length"]) == (
            canonical_params["min_length"],
            canonical_params["max_length"],
        )
        provider = BaseProvider()
        provider.set_seed(42)
        canonical_values = [provider.generate("string", **canonical_params) for _ in range(50)]
        provider.set_seed(42)
        assert [provider.generate("string", **alias_params) for _ in range(50)] == canonical_values

    @pytest.mark.parametrize("charset", ["01", "0011", "ab"])
    def test_small_custom_alphabet_can_generate_the_requested_unique_batch(self, charset: str) -> None:
        with capture_logs() as events:
            spec = UniqueAdjuster(ColumnMapper()).adjust(
                {
                    "code": GeneratorSpec(
                        generator_name="string", params={"min_length": 1, "max_length": 1, "charset": charset}
                    )
                },
                {"code"},
                1000,
            )["code"]
        assert len(set(charset)) ** spec.params["max_length"] >= 1000
        provider = BaseProvider()
        provider.set_seed(42)
        values = [provider.generate("string", **spec.params) for _ in range(1000)]

        assert len(set(values)) == 1000
        assert set("".join(values)) <= set(charset)
        assert not [event for event in events if event["log_level"] == "warning"]

    @pytest.mark.parametrize(("count", "original_length"), [(1, 0), (50, 1), (69, 1), (70, 1), (1000, 1)])
    def test_overflow_recalculation_agrees_with_the_resulting_alphabet(self, count: int, original_length: int) -> None:
        specs = {
            "narrow": GeneratorSpec(
                generator_name="string", params={"min_length": original_length, "max_length": original_length}
            ),
            "wide": GeneratorSpec(
                generator_name="string",
                params={"min_length": original_length, "max_length": 50, "charset": "alphanumeric"},
            ),
        }
        result = UniqueAdjuster(ColumnMapper()).adjust(specs, set(specs), count)
        narrow = result["narrow"].params
        wide = result["wide"].params
        assert narrow["charset"] == "alphanumeric"
        assert narrow["min_length"] == wide["min_length"]
        assert narrow["max_length"] == narrow["min_length"]
        provider = BaseProvider()
        provider.set_seed(42)
        values = [provider.generate("string", **narrow) for _ in range(count)]
        assert len(set(values)) == count
        assert set("".join(values)) <= set(string.ascii_letters + string.digits)

    def test_exact_length_fit_preserves_default_characters(self) -> None:
        spec = UniqueAdjuster(ColumnMapper()).adjust(
            {"code": GeneratorSpec(generator_name="string", params={"min_length": 5, "max_length": 5})},
            {"code"},
            10,
        )["code"]
        provider = BaseProvider()
        provider.set_seed(42)
        values = [provider.generate("string", **spec.params) for _ in range(100)]

        assert all(len(value) == 5 for value in values)
        assert set("".join(values)) & set(" _-")

    @pytest.mark.parametrize("charset", ["digits", "alpha"])
    def test_overflow_preserves_explicit_character_restrictions(self, charset: str) -> None:
        spec = UniqueAdjuster(ColumnMapper()).adjust(
            {
                "code": GeneratorSpec(
                    generator_name="string", params={"min_length": 1, "max_length": 1, "charset": charset}
                )
            },
            {"code"},
            100,
        )["code"]
        provider = BaseProvider()
        provider.set_seed(42)
        values = [provider.generate("string", **spec.params) for _ in range(100)]
        allowed = string.digits if charset == "digits" else string.ascii_letters

        assert set("".join(values)) <= set(allowed)
        assert all(spec.params["min_length"] <= len(value) <= spec.params["max_length"] for value in values)


class TestIntegerDomainInvariants:
    def test_omitted_integer_bounds_resolve_to_provider_defaults(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust({"rank": GeneratorSpec(generator_name="integer")}, {"rank"}, 1)[
            "rank"
        ]
        provider_defaults = signature(BaseProvider._gen_integer).parameters

        assert result.params == {
            "min_value": provider_defaults["min_value"].default,
            "max_value": provider_defaults["max_value"].default,
        }

    def test_shifted_narrow_range_expands_without_moving_the_lower_bound(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"min_value": 1000, "max_value": 1003})},
            {"rank"},
            8,
        )["rank"]

        assert result.params["min_value"] == 1000
        assert result.params["max_value"] - result.params["min_value"] + 1 >= 8

    def test_sufficient_integer_domain_is_never_shrunk(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 105})},
            {"rank"},
            10,
        )["rank"]

        assert result.params["min_value"] <= 0
        assert result.params["max_value"] >= 105

    def test_omitted_lower_bound_still_allows_the_default_zero(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", params={"max_value": 0})},
            {"rank"},
            1,
            check_constraints=_checks("rank >= 0 AND rank <= 0"),
        )["rank"]

        assert result.params == {"min_value": 0, "max_value": 0}
        assert BaseProvider().generate("integer", **result.params) == 0

    def test_nullable_integer_bounds_are_clamped_even_when_nonnull_capacity_is_exhausted(self) -> None:
        result = UniqueAdjuster(ColumnMapper()).adjust(
            {"rank": GeneratorSpec(generator_name="integer", null_ratio=0.2)},
            {"rank"},
            100_000,
            check_constraints=_checks("rank >= 0 AND rank <= 3"),
        )["rank"]

        assert result.params == {"min_value": 0, "max_value": 3}
        provider = BaseProvider()
        provider.set_seed(42)
        assert {provider.generate("integer", **result.params) for _ in range(100)} == {0, 1, 2, 3}
