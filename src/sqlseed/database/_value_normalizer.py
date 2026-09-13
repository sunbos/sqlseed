"""Convert generated values to the native inputs expected by typed SQL bindings."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Date, DateTime, Time
from sqlalchemy.sql.elements import Null

if TYPE_CHECKING:
    from sqlalchemy.types import TypeEngine


def normalize_typed_value(value: Any, column_type: TypeEngine[Any], column_name: str, dialect_name: str) -> Any:
    """Prepare JSON documents and parse ISO temporal strings by column type.

    JSON generators return serialized documents, including quoted JSON strings.
    SQLite JSON uses text bindings to preserve lexical FK/UNIQUE equality;
    PostgreSQL JSON/JSONB uses SQLAlchemy's native bindings. Explicit ``null()``
    retains SQL NULL semantics; serialized ``null`` always means JSON null.
    Other types (notably TEXT) never undergo JSON or temporal parsing.
    """
    try:
        if isinstance(column_type, JSON):
            return _json_value(value, column_type, as_text=dialect_name == "sqlite")
        if value is None:
            return None
        return _temporal_value(value, column_type)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {column_type} value for column '{column_name}': {exc}") from exc


def _temporal_value(value: Any, column_type: TypeEngine[Any]) -> Any:
    """Parse ISO temporal inputs while retaining existing native type validation."""
    if isinstance(column_type, DateTime):
        if isinstance(value, str):
            return datetime.fromisoformat(_iso_offset(value))
        if not isinstance(value, date):
            raise ValueError("Expected a date, datetime or ISO datetime string")
    elif isinstance(column_type, Date):
        if isinstance(value, str):
            return date.fromisoformat(value)
        if not isinstance(value, date):
            raise ValueError("Expected a date or ISO date string")
    elif isinstance(column_type, Time):
        if isinstance(value, str):
            return time.fromisoformat(_iso_offset(value))
        if not isinstance(value, time):
            raise ValueError("Expected a time or ISO time string")
    return value


def _iso_offset(value: str) -> str:
    # Python 3.10's fromisoformat does not yet recognize the ISO UTC suffix.
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def _json_value(value: Any, column_type: JSON, *, as_text: bool) -> Any:
    if isinstance(value, Null):
        return None if as_text else value
    if value is JSON.NULL:
        return "null" if as_text else value
    if value is None and column_type.none_as_null:
        return None
    parsed = json.loads(value) if isinstance(value, str) else value
    # Python's JSON encoder/decoder otherwise accepts non-JSON NaN/Infinity,
    # including values nested inside native objects or overflowing exponents.
    encoded = json.dumps(parsed, allow_nan=False)
    if as_text:
        # Reformatting an existing SQLite JSON document would change FK/UNIQUE
        # equality, which compares its stored text rather than JSON structure.
        return value if isinstance(value, str) else encoded
    return JSON.NULL if isinstance(value, str) and parsed is None else parsed
