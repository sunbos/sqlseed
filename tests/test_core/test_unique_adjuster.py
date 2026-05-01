from __future__ import annotations

from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.unique_adjuster import UniqueAdjuster


class TestUniqueAdjuster:
    def test_adjust_string_increases_min_length(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"code": GeneratorSpec(generator_name="string", params={"min_length": 1, "max_length": 50})}
        result = adjuster.adjust(specs, {"code"}, 10000)
        assert result["code"].params["min_length"] > 1

    def test_adjust_integer_expands_range(self) -> None:
        mapper = ColumnMapper()
        adjuster = UniqueAdjuster(mapper)
        specs = {"id": GeneratorSpec(generator_name="integer", params={"min_value": 0, "max_value": 100})}
        result = adjuster.adjust(specs, {"id"}, 10000)
        assert result["id"].params["max_value"] > 100

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
        assert result["code"].params["min_length"] > 1

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
        assert result["code"].params["min_length"] > 1

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
