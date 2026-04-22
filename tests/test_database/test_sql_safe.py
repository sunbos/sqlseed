from __future__ import annotations

import pytest

from sqlseed._utils.sql_safe import build_insert_sql, quote_identifier, validate_table_name


class TestSqlSafe:
    def test_quote_identifier_simple(self) -> None:
        result = quote_identifier("users")
        assert result == '"users"'

    def test_quote_identifier_with_underscore(self) -> None:
        result = quote_identifier("my_table")
        assert result == '"my_table"'

    def test_quote_identifier_with_quotes(self) -> None:
        result = quote_identifier('my"table')
        assert result == '"my""table"'

    def test_quote_identifier_empty(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            quote_identifier("")

    def test_quote_identifier_rejects_semicolon(self) -> None:
        with pytest.raises(ValueError, match="dangerous characters"):
            quote_identifier("users; DROP TABLE")

    def test_quote_identifier_rejects_newline(self) -> None:
        with pytest.raises(ValueError, match="dangerous characters"):
            quote_identifier("users\ntable")

    def test_quote_identifier_rejects_single_quote(self) -> None:
        with pytest.raises(ValueError, match="dangerous characters"):
            quote_identifier("users' OR 1=1")

    def test_quote_identifier_rejects_dash(self) -> None:
        with pytest.raises(ValueError, match="dangerous characters"):
            quote_identifier("my-table")

    def test_validate_table_name_simple(self) -> None:
        result = validate_table_name("users")
        assert result == '"users"'

    def test_validate_table_name_special_chars_warns(self) -> None:
        result = validate_table_name("my_table_2")
        assert result == '"my_table_2"'

    def test_build_insert_sql(self) -> None:
        result = build_insert_sql("users", ["name", "email"])
        assert result == 'INSERT INTO "users" ("name", "email") VALUES (?, ?)'

    def test_build_insert_sql_single_column(self) -> None:
        result = build_insert_sql("users", ["id"])
        assert result == 'INSERT INTO "users" ("id") VALUES (?)'
