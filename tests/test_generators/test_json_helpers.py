"""Tests for JSON Schema-based data generation helpers.

Covers ``generate_json_from_schema`` and ``_generate_from_schema`` with a
fake provider for deterministic unit tests and ``BaseProvider`` for
integration tests.
"""

from __future__ import annotations

import json
from typing import Any

from sqlseed.generators._json_helpers import (
    _generate_from_schema,
    generate_json_from_schema,
)
from sqlseed.generators.base_provider import BaseProvider

# Shared schema used by both TestGenerateJsonFromSchema.test_nested_object_in_array
# and TestGenerateFromSchema.test_nested_array_of_objects. Extracted to eliminate
# a CodeDuplication warning across the two test classes.
_NESTED_OBJECT_ARRAY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
        },
    },
}


class FakeProvider:
    """Fake DataProvider that records calls and returns predictable values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "fake"

    def set_locale(self, locale: str) -> None:
        pass

    def set_seed(self, seed: int) -> None:
        pass

    def generate(self, type_name: str, **params: Any) -> Any:
        self.calls.append((type_name, params))
        if type_name == "integer":
            return 42
        if type_name == "float":
            return 3.14
        if type_name == "boolean":
            return True
        if type_name == "name":
            return "fake_name"
        if type_name == "string":
            return "fake_string"
        return f"fake_{type_name}"


# ---------------------------------------------------------------------------
# generate_json_from_schema
# ---------------------------------------------------------------------------


class TestGenerateJsonFromSchema:
    """Tests for ``generate_json_from_schema``."""

    def test_returns_json_string(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "string"}, lambda: 2)
        assert isinstance(result, str)
        # Must be valid JSON
        json.loads(result)

    def test_schema_none_uses_default_template(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, None, lambda: 2)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert set(data.keys()) == {"id", "name", "active"}

    def test_schema_none_calls_correct_generators(self) -> None:
        provider = FakeProvider()
        generate_json_from_schema(provider, None, lambda: 2)
        type_names = [c[0] for c in provider.calls]
        assert "integer" in type_names
        assert "name" in type_names
        assert "boolean" in type_names

    def test_schema_none_integer_params(self) -> None:
        provider = FakeProvider()
        generate_json_from_schema(provider, None, lambda: 2)
        integer_call = next(c for c in provider.calls if c[0] == "integer")
        assert integer_call[1] == {"min_value": 1, "max_value": 999999}

    def test_schema_none_active_is_boolean(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, None, lambda: 2)
        data = json.loads(result)
        assert isinstance(data["active"], bool)

    def test_schema_none_id_is_integer(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, None, lambda: 2)
        data = json.loads(result)
        assert isinstance(data["id"], int)

    def test_schema_object(self) -> None:
        provider = FakeProvider()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }
        result = generate_json_from_schema(provider, schema, lambda: 2)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "name" in data
        assert "count" in data

    def test_schema_string(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "string"}, lambda: 2)
        assert json.loads(result) == "fake_string"

    def test_schema_integer(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "integer"}, lambda: 2)
        assert json.loads(result) == 42

    def test_schema_number(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "number"}, lambda: 2)
        assert json.loads(result) == 3.14

    def test_schema_boolean(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "boolean"}, lambda: 2)
        assert json.loads(result) is True

    def test_schema_array(self) -> None:
        provider = FakeProvider()
        schema = {"type": "array", "items": {"type": "integer"}}
        result = generate_json_from_schema(provider, schema, lambda: 3)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 3
        assert all(v == 42 for v in data)

    def test_schema_unknown_type_defaults_to_string(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {"type": "unknown"}, lambda: 2)
        assert json.loads(result) == "fake_string"

    def test_schema_missing_type_defaults_to_string(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, {}, lambda: 2)
        assert json.loads(result) == "fake_string"

    def test_array_count_from_callback(self) -> None:
        provider = FakeProvider()
        schema = {"type": "array", "items": {"type": "integer"}}
        result = generate_json_from_schema(provider, schema, lambda: 5)
        data = json.loads(result)
        assert len(data) == 5

    def test_array_without_items_defaults_to_string(self) -> None:
        provider = FakeProvider()
        schema = {"type": "array"}
        result = generate_json_from_schema(provider, schema, lambda: 2)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2
        assert all(v == "fake_string" for v in data)

    def test_object_without_properties(self) -> None:
        provider = FakeProvider()
        schema = {"type": "object"}
        result = generate_json_from_schema(provider, schema, lambda: 2)
        data = json.loads(result)
        assert data == {}

    def test_nested_object_in_array(self) -> None:
        provider = FakeProvider()
        result = generate_json_from_schema(provider, _NESTED_OBJECT_ARRAY_SCHEMA, lambda: 2)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 2
        for item in data:
            assert isinstance(item, dict)
            assert item["id"] == 42
            assert item["name"] == "fake_string"

    def test_nested_object_with_array_property(self) -> None:
        provider = FakeProvider()
        schema = {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
        result = generate_json_from_schema(provider, schema, lambda: 3)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert isinstance(data["tags"], list)
        assert len(data["tags"]) == 3

    def test_deeply_nested_structure(self) -> None:
        provider = FakeProvider()
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "integer"},
                            "nested": {
                                "type": "array",
                                "items": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        }
        result = generate_json_from_schema(provider, schema, lambda: 2)
        data = json.loads(result)
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 2
        assert isinstance(data["items"][0]["nested"], list)
        assert len(data["items"][0]["nested"]) == 2

    def test_integration_with_base_provider_default(self) -> None:
        provider = BaseProvider()
        result = generate_json_from_schema(provider, None, lambda: 2)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "id" in data
        assert "name" in data
        assert "active" in data

    def test_integration_with_base_provider_object(self) -> None:
        provider = BaseProvider()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "active": {"type": "boolean"},
            },
        }
        result = generate_json_from_schema(provider, schema, lambda: 3)
        data = json.loads(result)
        assert isinstance(data, dict)
        assert "name" in data
        assert "count" in data
        assert "active" in data


# ---------------------------------------------------------------------------
# _generate_from_schema
# ---------------------------------------------------------------------------


class TestGenerateFromSchema:
    """Tests for the internal ``_generate_from_schema`` function."""

    def test_string_type(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "string"}, lambda: 2)
        assert result == "fake_string"

    def test_string_type_passes_length_params(self) -> None:
        provider = FakeProvider()
        _generate_from_schema(provider, {"type": "string"}, lambda: 2)
        string_call = next(c for c in provider.calls if c[0] == "string")
        assert string_call[1] == {"min_length": 5, "max_length": 20}

    def test_integer_type(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "integer"}, lambda: 2)
        assert result == 42

    def test_number_type(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "number"}, lambda: 2)
        assert result == 3.14

    def test_boolean_type(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "boolean"}, lambda: 2)
        assert result is True

    def test_array_type(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "array", "items": {"type": "integer"}}, lambda: 3)
        assert result == [42, 42, 42]

    def test_array_uses_get_array_count(self) -> None:
        provider = FakeProvider()
        count_calls: list[int] = []

        def get_count() -> int:
            count_calls.append(1)
            return 4

        result = _generate_from_schema(provider, {"type": "array", "items": {"type": "integer"}}, get_count)
        assert len(result) == 4
        assert len(count_calls) == 1

    def test_array_without_items_defaults_to_string(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "array"}, lambda: 2)
        assert result == ["fake_string", "fake_string"]

    def test_object_type(self) -> None:
        provider = FakeProvider()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
            },
        }
        result = _generate_from_schema(provider, schema, lambda: 2)
        assert result == {"name": "fake_string", "count": 42}

    def test_object_without_properties(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "object"}, lambda: 2)
        assert result == {}

    def test_unknown_type_defaults_to_string(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "null"}, lambda: 2)
        assert result == "fake_string"

    def test_missing_type_defaults_to_string(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {}, lambda: 2)
        assert result == "fake_string"

    def test_nested_array_of_objects(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, _NESTED_OBJECT_ARRAY_SCHEMA, lambda: 2)
        assert result == [
            {"id": 42, "name": "fake_string"},
            {"id": 42, "name": "fake_string"},
        ]

    def test_object_with_array_property(self) -> None:
        provider = FakeProvider()
        schema = {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
        result = _generate_from_schema(provider, schema, lambda: 3)
        assert result == {"tags": ["fake_string", "fake_string", "fake_string"]}

    def test_empty_array_when_count_is_zero(self) -> None:
        provider = FakeProvider()
        result = _generate_from_schema(provider, {"type": "array", "items": {"type": "integer"}}, lambda: 0)
        assert result == []

    def test_integration_with_base_provider(self) -> None:
        provider = BaseProvider()
        result = _generate_from_schema(
            provider,
            {"type": "object", "properties": {"name": {"type": "string"}}},
            lambda: 2,
        )
        assert isinstance(result, dict)
        assert "name" in result
