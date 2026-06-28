"""TDD characterization tests for cli._utils.sanitize_table_config.

These tests document and verify the existing behavior of the config sanitization
function that strips leading dots/colons from table and column names. The function
is critical for cleaning LLM-generated config names that may have YAML key artifacts.
"""

from __future__ import annotations

from sqlseed_cli._utils import sanitize_table_config


class TestSanitizeTableName:
    """Tests for table name sanitization."""

    def test_strips_leading_dots(self) -> None:
        config = {"name": "....users"}
        sanitize_table_config(config)
        assert config["name"] == "users"

    def test_strips_leading_colons(self) -> None:
        config = {"name": ":::users"}
        sanitize_table_config(config)
        assert config["name"] == "users"

    def test_strips_mixed_leading_dots_and_colons(self) -> None:
        config = {"name": ":.:.users"}
        sanitize_table_config(config)
        assert config["name"] == "users"

    def test_preserves_name_without_leading_punct(self) -> None:
        config = {"name": "users"}
        sanitize_table_config(config)
        assert config["name"] == "users"

    def test_preserves_internal_dots_and_colons(self) -> None:
        # Only LEADING punctuation is stripped; internal chars stay
        config = {"name": "my.table:name"}
        sanitize_table_config(config)
        assert config["name"] == "my.table:name"

    def test_handles_none_name(self) -> None:
        config = {"name": None}
        sanitize_table_config(config)
        assert config["name"] is None

    def test_handles_missing_name_key(self) -> None:
        config = {"columns": []}
        sanitize_table_config(config)
        assert "name" not in config

    def test_handles_non_string_name(self) -> None:
        # Non-string name should be left untouched
        config = {"name": 123}
        sanitize_table_config(config)
        assert config["name"] == 123

    def test_preserves_empty_string_name(self) -> None:
        config = {"name": ""}
        sanitize_table_config(config)
        assert config["name"] == ""


class TestSanitizeColumnNames:
    """Tests for column name sanitization."""

    def test_strips_leading_dots_from_columns(self) -> None:
        config = {
            "name": "users",
            "columns": [{"name": "...email", "generator": "email"}],
        }
        sanitize_table_config(config)
        assert config["columns"][0]["name"] == "email"

    def test_strips_leading_colons_from_columns(self) -> None:
        config = {
            "name": "users",
            "columns": [{"name": "::id", "generator": "skip"}],
        }
        sanitize_table_config(config)
        assert config["columns"][0]["name"] == "id"

    def test_preserves_column_name_without_leading_punct(self) -> None:
        config = {
            "name": "users",
            "columns": [{"name": "email", "generator": "email"}],
        }
        sanitize_table_config(config)
        assert config["columns"][0]["name"] == "email"

    def test_handles_empty_columns_list(self) -> None:
        config = {"name": "users", "columns": []}
        sanitize_table_config(config)
        assert not config["columns"]

    def test_handles_missing_columns_key(self) -> None:
        config = {"name": "users"}
        sanitize_table_config(config)
        assert "columns" not in config

    def test_handles_column_dict_without_name_key(self) -> None:
        config = {
            "name": "users",
            "columns": [{"generator": "email"}],
        }
        sanitize_table_config(config)
        assert config["columns"][0] == {"generator": "email"}

    def test_handles_non_dict_column_entry(self) -> None:
        # Non-dict column entries should be skipped without crashing
        config = {
            "name": "users",
            "columns": ["not_a_dict", 42, None],
        }
        sanitize_table_config(config)
        assert config["columns"] == ["not_a_dict", 42, None]

    def test_handles_none_column_name(self) -> None:
        config = {
            "name": "users",
            "columns": [{"name": None}],
        }
        sanitize_table_config(config)
        assert config["columns"][0]["name"] is None

    def test_sanitizes_multiple_columns(self) -> None:
        config = {
            "name": "..users",
            "columns": [
                {"name": "::id", "generator": "skip"},
                {"name": "...email", "generator": "email"},
                {"name": "name", "generator": "name"},
            ],
        }
        sanitize_table_config(config)
        assert config["name"] == "users"
        assert config["columns"][0]["name"] == "id"
        assert config["columns"][1]["name"] == "email"
        assert config["columns"][2]["name"] == "name"


class TestSanitizeInPlace:
    """Tests verifying that sanitization mutates the dict in place."""

    def test_mutates_config_in_place(self) -> None:
        config = {"name": "...users", "columns": []}
        # Function returns None and mutates in place
        sanitize_table_config(config)
        assert config["name"] == "users"

    def test_preserves_other_config_keys(self) -> None:
        config = {
            "name": "...users",
            "count": 100,
            "provider": "faker",
            "columns": [],
        }
        sanitize_table_config(config)
        assert config["count"] == 100
        assert config["provider"] == "faker"
