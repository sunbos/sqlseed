from __future__ import annotations

import pytest

from sqlseed.core.mapper import ColumnMapper
from tests.conftest import make_column_info


class TestCamelCaseMapping:
    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_hungarian_s_order_no_matches_no_pattern(self) -> None:
        spec = self.mapper.map_column(make_column_info("sOrderNo", "TEXT"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_hungarian_s_item_no_matches_no_pattern(self) -> None:
        spec = self.mapper.map_column(make_column_info("sItemNo", "TEXT"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_camel_user_name_matches_username_exact(self) -> None:
        spec = self.mapper.map_column(make_column_info("userName", "TEXT"))
        assert spec.generator_name == "username"

    def test_camel_user_email_matches_email_exact(self) -> None:
        spec = self.mapper.map_column(make_column_info("userEmail", "TEXT"))
        assert spec.generator_name == "email"

    def test_camel_is_active_matches_boolean_pattern(self) -> None:
        spec = self.mapper.map_column(make_column_info("isActive", "INTEGER"))
        assert spec.generator_name == "boolean"

    def test_camel_created_at_matches_datetime_pattern(self) -> None:
        spec = self.mapper.map_column(make_column_info("createdAt", "TEXT"))
        assert spec.generator_name == "datetime"

    def test_camel_user_password_matches_password_exact(self) -> None:
        spec = self.mapper.map_column(make_column_info("userPassword", "TEXT"))
        assert spec.generator_name == "password"

    def test_camel_home_address_matches_address_exact(self) -> None:
        spec = self.mapper.map_column(make_column_info("homeAddress", "TEXT"))
        assert spec.generator_name == "address"

    def test_sensitive_user_no_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("user_no", "TEXT"))
        assert spec.generator_name == "string"

    def test_sensitive_card_no_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("card_no", "TEXT"))
        assert spec.generator_name == "string"

    def test_sensitive_card_number_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("card_number", "TEXT"))
        assert spec.generator_name == "string"

    def test_sensitive_identity_no_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("identity_no", "TEXT"))
        assert spec.generator_name == "string"

    @pytest.mark.parametrize(
        "col_name",
        ["order_no", "item_no"],
        ids=["order_no", "item_no"],
    )
    def test_non_sensitive_no_still_integer(self, col_name: str) -> None:
        spec = self.mapper.map_column(make_column_info(col_name, "TEXT"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_hungarian_s_user_no_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("sUserNo", "TEXT"))
        assert spec.generator_name == "string"

    def test_hungarian_s_card_no_is_desensitized(self) -> None:
        spec = self.mapper.map_column(make_column_info("sCardNo", "TEXT"))
        assert spec.generator_name == "string"

    def test_all_lower_still_works(self) -> None:
        spec = self.mapper.map_column(make_column_info("email", "TEXT"))
        assert spec.generator_name == "email"

    def test_pascal_case_to_snake(self) -> None:
        spec = self.mapper.map_column(make_column_info("UserName", "TEXT"))
        assert spec.generator_name == "username"

    def test_consecutive_uppercase(self) -> None:
        spec = self.mapper.map_column(make_column_info("userID", "TEXT"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_hungarian_prefix_s_user_name(self) -> None:
        spec = self.mapper.map_column(make_column_info("sUserName", "TEXT"))
        assert spec.generator_name == "name"

    def test_hungarian_prefix_n_age(self) -> None:
        spec = self.mapper.map_column(make_column_info("nAge", "INTEGER"))
        assert spec.generator_name == "integer"

    def test_to_snake_case_helper(self) -> None:
        assert ColumnMapper._to_snake_case("sOrderNo") == "s_order_no"
        assert ColumnMapper._to_snake_case("sItemNo") == "s_item_no"
        assert ColumnMapper._to_snake_case("userName") == "user_name"
        assert ColumnMapper._to_snake_case("isActive") == "is_active"
        assert ColumnMapper._to_snake_case("userID") == "user_id"
        assert ColumnMapper._to_snake_case("HTTPResponse") == "http_response"
        assert ColumnMapper._to_snake_case("already_snake") == "already_snake"
        assert ColumnMapper._to_snake_case("simple") == "simple"
