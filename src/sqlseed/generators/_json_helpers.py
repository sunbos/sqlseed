"""JSON Schema-based data generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.generators._protocol import DataProvider


def generate_json_from_schema(
    provider: DataProvider,
    schema: dict[str, Any] | None,
    get_array_count: Callable[[], int],
) -> str:
    """Generate a JSON string from a JSON Schema.

    When ``schema`` is ``None``, a default template (id, name, active fields) is used;
    otherwise ``_generate_from_schema`` is invoked to recursively produce data that
    conforms to the schema, which is then serialized to a JSON string.
    """
    if schema is None:
        data = {
            "id": provider.generate("integer", min_value=1, max_value=999999),
            "name": provider.generate("name"),
            "active": provider.generate("boolean"),
        }
    else:
        data = _generate_from_schema(provider, schema, get_array_count)
    return json.dumps(data)


def _generate_from_schema(
    provider: DataProvider,
    schema: dict[str, Any],
    get_array_count: Callable[[], int],
) -> Any:
    """Recursively generate data for a JSON Schema node.

    Supports ``string``, ``integer``, ``number``, ``boolean``, ``array`` and ``object`` types.
    For ``array`` the element count is decided by ``get_array_count``; for ``object`` the
    ``properties`` are iterated and generated recursively. Scalar types delegate to
    :func:`_generate_scalar`.
    """
    schema_type = schema.get("type", "string")

    # Complex types require schema-driven recursion.
    if schema_type == "array":
        items = schema.get("items", {"type": "string"})
        count = get_array_count()
        return [_generate_from_schema(provider, items, get_array_count) for _ in range(count)]
    if schema_type == "object":
        properties = schema.get("properties", {})
        return {k: _generate_from_schema(provider, v, get_array_count) for k, v in properties.items()}

    # Scalar types (string, integer, number, boolean, fallback).
    return _generate_scalar(provider, schema_type)


def _generate_scalar(provider: DataProvider, schema_type: str) -> Any:
    """Generate a scalar value for the given JSON Schema type.

    Handles ``string``, ``integer``, ``number``, ``boolean``. Falls back to a
    plain string for unknown or missing types.
    """
    if schema_type == "string":
        return provider.generate("string", min_length=5, max_length=20)
    if schema_type == "integer":
        return provider.generate("integer")
    if schema_type == "number":
        return provider.generate("float")
    if schema_type == "boolean":
        return provider.generate("boolean")
    return provider.generate("string")
