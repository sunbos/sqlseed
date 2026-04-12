from __future__ import annotations

from sqlseed._utils.sql_safe import build_insert_sql, quote_identifier, validate_table_name


class TestSqlSafe:
    def test_quote_identifier_simple(self) -> None:
        result = quote_identifier("users")
        assert result == '"users"'

    def test_quote_identifier_with_quotes(self) -> None:
        result = quote_identifier('my"table')
        assert result == '"my""table"'

    def test_quote_identifier_empty(self) -> None:
        try:
            quote_identifier("")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_validate_table_name_simple(self) -> None:
        result = validate_table_name("users")
        assert result == '"users"'

    def test_validate_table_name_special_chars(self) -> None:
        result = validate_table_name("my-table")
        assert result == '"my-table"'

    def test_build_insert_sql(self) -> None:
        result = build_insert_sql("users", ["name", "email"])
        assert result == 'INSERT INTO "users" ("name", "email") VALUES (?, ?)'

    def test_build_insert_sql_single_column(self) -> None:
        result = build_insert_sql("users", ["id"])
        assert result == 'INSERT INTO "users" ("id") VALUES (?)'
