from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.unique_adjuster import UniqueAdjuster

# Import the shared ColumnInfo factory from tests.conftest to avoid
# CodeDuplication with test_plugin_mediator.py (both files previously
# defined an identical _make_col_info helper).
from tests.conftest import make_col_info_varchar as _make_col_info


class TestUniqueAdjuster:
    def test_adjust_string_increases_min_length(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"code": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, {"code"}, 10000)
        # Exact value: ceil(log(10000^2 * 50) / log(62)) = ceil(5.40) = 6.
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
        # count=1: count^2 * 50 = 50, log(50)/log(62) = 0.83, ceil = 1.
        # So min_needed=1 and current_min=1 (from setdefault), max(1,1)=1.
        result = adjuster.adjust(specs, {"code"}, 1)
        assert result["code"].params["max_length"] == 50  # setdefault default
        assert result["code"].params["min_length"] == 1  # setdefault default

    def test_adjust_string_no_charset_uses_alphanumeric_62(self) -> None:
        """Verify charset_size=62 default for None charset.

        Pins the `charset_size = 62` constant on line 78. Without this test,
        a mutant like `charset_size = 63` survives because no test asserts
        the exact min_length derived from charset_size=62.
        """
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        # No charset key → charset_size defaults to 62.
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 1, "max_length": 50},
            )
        }
        # count=1000: log(1000^2 * 50)/log(62) = log(5e7)/log(62) = 4.55, ceil = 5.
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

    def test_adjust_choice_with_sufficient_choices_no_fallback(self) -> None:
        # When choices >= count, no fallback needed
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": ["a", "b", "c", "d", "e"]},
            )
        }
        col_infos = [_make_col_info("status", "VARCHAR(10)")]
        result = adjuster.adjust(specs, {"status"}, 3, col_infos)
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
        # min_length to satisfy uniqueness for count=10000 over a 62-char alphabet:
        # ceil(log(10000 * 10000 * 50) / log(62)) = ceil(5.40) = 6.
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
        # to 6 (math: ceil(log(10000^2 * 50)/log(62)) = 6).
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


class TestAdjustIntegerWarnings:
    """Tests for INT8/INT16 warning paths (lines 130-138)."""

    @pytest.mark.parametrize(
        ("col_type", "count", "expected_min_max"),
        [
            ("INT8", 300, 3000),
            ("INT16", 70000, 700000),
            ("INT8", 200, 2000),
        ],
        ids=["int8_over_255_warns", "int16_over_65535_warns", "int8_under_256_no_warning"],
    )
    def test_int_column_range_expanded(
        self,
        caplog: pytest.LogCaptureFixture,
        col_type: str,
        count: int,
        expected_min_max: int,
    ) -> None:
        """INT8/INT16 integer ranges are expanded to fit ``count`` unique rows.

        The first two cases (count > 255 for INT8, count > 65535 for INT16)
        trigger a WARNING log; the third (count < 256 for INT8) expands the
        range silently. All three assert only that ``max_value`` grew enough
        to hold ``count * 10`` unique values.
        """
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {
            "code": GeneratorSpec(
                generator_name="integer",
                params={"min_value": 0, "max_value": 100},
            )
        }
        col_infos = [_make_col_info("code", col_type)]
        with caplog.at_level("WARNING"):
            result = adjuster.adjust(specs, {"code"}, count, col_infos)
        assert result["code"].params["max_value"] >= expected_min_max

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
