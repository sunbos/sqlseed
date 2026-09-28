"""Explicit, language-independent Web messages and additive wire descriptors.

Only Message values constructed by this module are annotated. Ordinary strings
and user dictionaries are never interpreted as translation keys. The Chinese
string remains the legacy API value; browsers translate its descriptor locally.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from typing_extensions import Self


@lru_cache(maxsize=1)
def catalog() -> dict[str, list[str]]:
    """Read the same bundled catalog served to the browser, without network IO."""
    path = Path(__file__).parent / "static" / "i18n" / "backend-messages.json"
    value: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    return value


def _safe_parameter(value: Any) -> Any:
    if isinstance(value, Message) or value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_parameter(item) for item in value]
    # Import lazily: diagnostics also preserves messages originating here.
    from sqlseed_web.diagnostics import public_error

    return public_error(ValueError(str(value)))


class Message(str):
    """A legacy-compatible string with explicitly authored presentation metadata."""

    key: str
    params: dict[str, Any]
    fallback_index: int
    key_error_repr: bool

    def __new__(cls, key: str, *, _fallback_index: int = 0, _key_error_repr: bool = False, **params: Any) -> Self:
        template = catalog()[key][_fallback_index]
        safe = {name: _safe_parameter(value) for name, value in params.items()}
        if key == "backend.message_list":
            rendered = str(safe["separator"]).join(str(item) for item in safe["items"])
        else:
            rendered = template.format_map(safe)
        if _key_error_repr:
            rendered = repr(rendered)
        result = super().__new__(cls, rendered)
        result.key, result.params = key, safe
        result.fallback_index = _fallback_index
        result.key_error_repr = _key_error_repr
        return result

    def descriptor(self) -> dict[str, Any]:
        """Return an inert JSON descriptor; nested messages remain explicit."""
        return {"key": self.key, "params": {name: _parameter_wire(value) for name, value in self.params.items()}}

    def __reduce__(self) -> tuple[Any, ...]:
        return _restore_message, (self.key, self.params, self.fallback_index, self.key_error_repr)


def _restore_message(key: str, params: dict[str, Any], fallback_index: int, key_error_repr: bool = False) -> Message:
    return Message(key, _fallback_index=fallback_index, _key_error_repr=key_error_repr, **params)


def key_error_message(value: Message) -> Message:
    """Preserve KeyError's legacy repr wrapper without changing its descriptor."""
    return Message(value.key, _fallback_index=value.fallback_index, _key_error_repr=True, **value.params)


def message(key: str, **params: Any) -> Message:
    """Construct a message by stable key, never by matching its visible text."""
    return Message(key, **params)


def legacy_message(key: str, **params: Any) -> Message:
    """Retain the original English fallback on older API contracts."""
    return Message(key, _fallback_index=1, **params)


def message_list(items: Iterable[str], separator: str = "; ") -> Message:
    """Compose feedback while retaining each item's independent descriptor."""
    return message("backend.message_list", items=list(items), separator=separator)


def _parameter_wire(value: Any) -> Any:
    if isinstance(value, Message):
        return materialize_messages({"message": value})
    if isinstance(value, list):
        return [_parameter_wire(item) for item in value]
    return value


def materialize_messages(value: Any) -> Any:
    """Expand Message values at HTTP, stream, IPC and persistence boundaries."""
    if isinstance(value, dict):
        result = {key: materialize_messages(item) for key, item in value.items()}
        for key, item in value.items():
            if isinstance(item, Message):
                descriptor = item.descriptor()
                result[f"{key}_key"] = descriptor["key"]
                result[f"{key}_params"] = descriptor["params"]
            elif isinstance(item, (list, tuple)) and any(isinstance(entry, Message) for entry in item):
                result[f"{key}_i18n"] = [entry.descriptor() if isinstance(entry, Message) else None for entry in item]
        return result
    if isinstance(value, (list, tuple)):
        return [materialize_messages(item) for item in value]
    return str(value) if isinstance(value, Message) else value


def restore_private_message(record: dict[str, Any], field: str) -> Any:
    """Restore a scalar from a trusted IPC error envelope, never user data.

    Reconstructed text must match the original fallback exactly. Nested
    descriptors are accepted only inside explicitly authored parameters.
    """
    value = record.get(field)
    key, params = record.get(f"{field}_key"), record.get(f"{field}_params", {})
    if not isinstance(value, str) or not isinstance(key, str) or key not in catalog() or not isinstance(params, dict):
        return value

    def restore_parameter(parameter: Any) -> Any:
        if isinstance(parameter, list):
            return [restore_parameter(item) for item in parameter]
        if isinstance(parameter, dict):
            return restore_private_message(parameter, "message")
        return parameter

    try:
        restored = {name: restore_parameter(parameter) for name, parameter in params.items()}
        for fallback in (0, 1):
            candidate = Message(key, _fallback_index=fallback, **restored)
            if candidate == value:
                return candidate
            quoted = key_error_message(candidate)
            if quoted == value:
                return quoted
    except (KeyError, TypeError, ValueError):
        pass
    return value


def validation_descriptor(error_type: str) -> dict[str, Any]:
    """Describe Pydantic validation by its stable type, never rejected inputs.

    Keep the original sanitized ``msg`` on the response. No validator context,
    rejected body, expected literal value or credential enters these parameters.
    """
    kinds = {
        "missing": "required",
        "extra_forbidden": "extra",
        "string_type": "string",
        "string_too_short": "too_short",
        "string_too_long": "too_long",
        "int_type": "integer",
        "int_parsing": "integer",
        "int_from_float": "integer",
        "float_type": "number",
        "float_parsing": "number",
        "bool_type": "boolean",
        "bool_parsing": "boolean",
        "list_type": "list",
        "dict_type": "object",
        "model_type": "object",
        "model_attributes_type": "object",
        "literal_error": "choice",
        "enum": "choice",
        "greater_than": "lower_bound",
        "greater_than_equal": "lower_bound",
        "less_than": "upper_bound",
        "less_than_equal": "upper_bound",
        "finite_number": "finite_number",
        "json_invalid": "json",
    }
    return {"msg_key": f"backend.validation.{kinds.get(error_type, 'invalid')}", "msg_params": {}}


class MessageJSONResponse(JSONResponse):
    """Preserve descriptors in explicit responses as well as endpoint results."""

    def render(self, content: Any) -> bytes:
        return super().render(materialize_messages(content))


class MessageRoute(APIRoute):
    """Expand messages before FastAPI response validation can coerce strings."""

    def __init__(self, path: str, endpoint: Any, **kwargs: Any) -> None:
        if inspect.iscoroutinefunction(endpoint):

            @wraps(endpoint)
            async def async_wrapped(*args: Any, **values: Any) -> Any:
                return materialize_messages(await endpoint(*args, **values))

            wrapped: Any = async_wrapped
        else:

            @wraps(endpoint)
            def sync_wrapped(*args: Any, **values: Any) -> Any:
                return materialize_messages(endpoint(*args, **values))

            wrapped = sync_wrapped
        # Resolve forward references in the original module before wrapping it.
        # FastAPI otherwise resolves them against this helper's module globals.
        wrapped.__signature__ = inspect.signature(endpoint, eval_str=True)
        super().__init__(path, wrapped, **kwargs)
