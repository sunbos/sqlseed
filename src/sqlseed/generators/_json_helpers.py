from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def generate_json_from_schema(
    provider: Any,
    schema: dict[str, Any] | None,
    get_array_count: Callable[[], int],
) -> str:
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
    provider: Any,
    schema: dict[str, Any],
    get_array_count: Callable[[], int],
) -> Any:
    schema_type = schema.get("type", "string")
    if schema_type == "string":
        return provider.generate("string", min_length=5, max_length=20)
    if schema_type == "integer":
        return provider.generate("integer")
    if schema_type == "number":
        return provider.generate("float")
    if schema_type == "boolean":
        return provider.generate("boolean")
    if schema_type == "array":
        items = schema.get("items", {"type": "string"})
        count = get_array_count()
        return [_generate_from_schema(provider, items, get_array_count) for _ in range(count)]
    if schema_type == "object":
        properties = schema.get("properties", {})
        return {k: _generate_from_schema(provider, v, get_array_count) for k, v in properties.items()}
    return provider.generate("string")
