from __future__ import annotations

import json

from sqlseed.generators.base_provider import BaseProvider


class TestBaseProvider:
    def setup_method(self) -> None:
        self.provider = BaseProvider()

    def test_name(self) -> None:
        assert self.provider.name == "base"

    def test_generate_string(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10)
        assert 5 <= len(result) <= 10

    def test_generate_string_alpha(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="alpha")
        assert all(c.isalpha() for c in result)

    def test_generate_string_digits(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="digits")
        assert result.isdigit()

    def test_generate_string_alphanumeric(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="alphanumeric")
        assert all(c.isalnum() for c in result)

    def test_generate_string_custom_charset(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="abc")
        assert all(c in "abc" for c in result)

    def test_generate_string_default_charset(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset=None)
        assert len(result) >= 5

    def test_generate_integer(self) -> None:
        result = self.provider.generate_integer(min_value=10, max_value=20)
        assert 10 <= result <= 20

    def test_generate_float(self) -> None:
        result = self.provider.generate_float(min_value=0.0, max_value=1.0, precision=2)
        assert 0.0 <= result <= 1.0

    def test_generate_boolean(self) -> None:
        result = self.provider.generate_boolean()
        assert isinstance(result, bool)

    def test_generate_name(self) -> None:
        result = self.provider.generate_name()
        assert " " in result

    def test_generate_first_name(self) -> None:
        result = self.provider.generate_first_name()
        assert len(result) > 0

    def test_generate_last_name(self) -> None:
        result = self.provider.generate_last_name()
        assert len(result) > 0

    def test_generate_email(self) -> None:
        result = self.provider.generate_email()
        assert "@" in result

    def test_generate_phone(self) -> None:
        result = self.provider.generate_phone()
        assert "-" in result

    def test_generate_address(self) -> None:
        result = self.provider.generate_address()
        assert len(result) > 0

    def test_generate_company(self) -> None:
        result = self.provider.generate_company()
        assert len(result) > 0

    def test_generate_url(self) -> None:
        result = self.provider.generate_url()
        assert result.startswith("http")

    def test_generate_ipv4(self) -> None:
        result = self.provider.generate_ipv4()
        parts = result.split(".")
        assert len(parts) == 4

    def test_generate_uuid(self) -> None:
        result = self.provider.generate_uuid()
        assert len(result) == 36
        assert result.count("-") == 4

    def test_generate_date(self) -> None:
        result = self.provider.generate_date(start_year=2020, end_year=2024)
        assert result.startswith("20")

    def test_generate_datetime(self) -> None:
        result = self.provider.generate_datetime(start_year=2020, end_year=2024)
        assert " " in result

    def test_generate_timestamp(self) -> None:
        result = self.provider.generate_timestamp()
        assert isinstance(result, int)

    def test_generate_text(self) -> None:
        result = self.provider.generate_text(min_length=50, max_length=200)
        assert len(result) <= 200

    def test_generate_sentence(self) -> None:
        result = self.provider.generate_sentence()
        assert len(result) > 0
        assert result.endswith(".")

    def test_generate_password(self) -> None:
        result = self.provider.generate_password(length=20)
        assert len(result) == 20

    def test_generate_choice(self) -> None:
        choices = ["a", "b", "c"]
        result = self.provider.generate_choice(choices)
        assert result in choices

    def test_seed_reproducibility(self) -> None:
        self.provider.set_seed(42)
        r1 = self.provider.generate_integer(min_value=0, max_value=999999)
        self.provider.set_seed(42)
        r2 = self.provider.generate_integer(min_value=0, max_value=999999)
        assert r1 == r2

    def test_generate_json_default(self) -> None:
        result = self.provider.generate_json()
        data = json.loads(result)
        assert "id" in data
        assert "name" in data
        assert "active" in data

    def test_generate_json_with_schema_string(self) -> None:
        schema = {"type": "string"}
        result = self.provider.generate_json(schema=schema)
        assert isinstance(json.loads(result), str)

    def test_generate_json_with_schema_integer(self) -> None:
        schema = {"type": "integer"}
        result = self.provider.generate_json(schema=schema)
        assert isinstance(json.loads(result), int)

    def test_generate_json_with_schema_number(self) -> None:
        schema = {"type": "number"}
        result = self.provider.generate_json(schema=schema)
        assert isinstance(json.loads(result), float)

    def test_generate_json_with_schema_boolean(self) -> None:
        schema = {"type": "boolean"}
        result = self.provider.generate_json(schema=schema)
        assert isinstance(json.loads(result), bool)

    def test_generate_json_with_schema_array(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        result = self.provider.generate_json(schema=schema)
        data = json.loads(result)
        assert isinstance(data, list)
        assert all(isinstance(x, int) for x in data)

    def test_generate_json_with_schema_object(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }
        result = self.provider.generate_json(schema=schema)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "name" in data
        assert "count" in data

    def test_generate_json_with_unknown_type(self) -> None:
        schema = {"type": "unknown_type"}
        result = self.provider.generate_json(schema=schema)
        data = json.loads(result)
        assert isinstance(data, str)

    def test_generate_bytes(self) -> None:
        result = self.provider.generate_bytes(length=16)
        assert len(result) == 16
