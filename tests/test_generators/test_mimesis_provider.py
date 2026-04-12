from __future__ import annotations

import json

from sqlseed.generators.mimesis_provider import MimesisProvider


class TestMimesisProvider:
    def setup_method(self) -> None:
        self.provider = MimesisProvider()

    def test_name(self) -> None:
        assert self.provider.name == "mimesis"

    def test_set_locale(self) -> None:
        self.provider.set_locale("zh_CN")

    def test_set_seed(self) -> None:
        self.provider.set_seed(42)

    def test_generate_string(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10)
        assert 5 <= len(result) <= 10

    def test_generate_string_alpha(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="alpha")
        assert 5 <= len(result) <= 10

    def test_generate_string_digits(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="digits")
        assert 5 <= len(result) <= 10

    def test_generate_string_alphanumeric(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="alphanumeric")
        assert 5 <= len(result) <= 10

    def test_generate_string_custom_charset(self) -> None:
        result = self.provider.generate_string(min_length=5, max_length=10, charset="abc")
        assert all(c in "abc" for c in result)

    def test_generate_integer(self) -> None:
        result = self.provider.generate_integer(min_value=10, max_value=20)
        assert 10 <= result <= 20

    def test_generate_float(self) -> None:
        result = self.provider.generate_float(min_value=0.0, max_value=1.0, precision=2)
        assert 0.0 <= result <= 1.0

    def test_generate_boolean(self) -> None:
        result = self.provider.generate_boolean()
        assert isinstance(result, bool)

    def test_generate_bytes(self) -> None:
        result = self.provider.generate_bytes(length=16)
        assert len(result) == 16

    def test_generate_name(self) -> None:
        result = self.provider.generate_name()
        assert len(result) > 0

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
        assert len(result) > 0

    def test_generate_address(self) -> None:
        result = self.provider.generate_address()
        assert len(result) > 0

    def test_generate_company(self) -> None:
        result = self.provider.generate_company()
        assert len(result) > 0

    def test_generate_url(self) -> None:
        result = self.provider.generate_url()
        assert len(result) > 0

    def test_generate_ipv4(self) -> None:
        result = self.provider.generate_ipv4()
        assert len(result.split(".")) == 4

    def test_generate_uuid(self) -> None:
        result = self.provider.generate_uuid()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_date(self) -> None:
        result = self.provider.generate_date(start_year=2020, end_year=2024)
        assert len(result) > 0

    def test_generate_date_default_end_year(self) -> None:
        result = self.provider.generate_date(start_year=2020)
        assert len(result) > 0

    def test_generate_datetime(self) -> None:
        result = self.provider.generate_datetime(start_year=2020, end_year=2024)
        assert len(result) > 0

    def test_generate_timestamp(self) -> None:
        result = self.provider.generate_timestamp()
        assert isinstance(result, int)

    def test_generate_text(self) -> None:
        result = self.provider.generate_text(min_length=10, max_length=50)
        assert len(result) <= 50

    def test_generate_sentence(self) -> None:
        result = self.provider.generate_sentence()
        assert len(result) > 0

    def test_generate_password(self) -> None:
        result = self.provider.generate_password(length=20)
        assert len(result) == 20

    def test_generate_choice(self) -> None:
        result = self.provider.generate_choice(["a", "b", "c"])
        assert result in ["a", "b", "c"]

    def test_generate_json(self) -> None:
        result = self.provider.generate_json()
        data = json.loads(result)
        assert "id" in data

    def test_generate_json_with_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }
        result = self.provider.generate_json(schema=schema)
        data = json.loads(result)
        assert "name" in data
        assert "count" in data

    def test_generate_json_schema_string(self) -> None:
        result = self.provider.generate_json(schema={"type": "string"})
        assert isinstance(json.loads(result), str)

    def test_generate_json_schema_integer(self) -> None:
        result = self.provider.generate_json(schema={"type": "integer"})
        assert isinstance(json.loads(result), int)

    def test_generate_json_schema_number(self) -> None:
        result = self.provider.generate_json(schema={"type": "number"})
        assert isinstance(json.loads(result), float)

    def test_generate_json_schema_boolean(self) -> None:
        result = self.provider.generate_json(schema={"type": "boolean"})
        assert isinstance(json.loads(result), bool)

    def test_generate_json_schema_array(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        result = self.provider.generate_json(schema=schema)
        data = json.loads(result)
        assert isinstance(data, list)

    def test_generate_json_schema_unknown(self) -> None:
        result = self.provider.generate_json(schema={"type": "unknown"})
        assert isinstance(json.loads(result), str)
