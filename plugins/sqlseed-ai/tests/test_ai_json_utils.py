"""Tests for JSON parsing utilities in _json_utils.py.

Covers the ``_sanitize_names`` mutation helper (strips leading colons
and dots from table/column name fields) and the ``_try_raw_decode``
strategy that extracts JSON embedded in prose text.
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from sqlseed_ai._json_utils import _sanitize_names, _try_raw_decode
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestSanitizeNames:
    def test_sanitize_names_strips_leading_colon(self) -> None:
        """Leading colons are stripped from table and column name fields."""
        data: dict[str, Any] = {
            "name": ":users",
            "columns": [{"name": ":id", "generator": "integer"}],
        }
        _sanitize_names(data)
        assert data["name"] == "users"
        assert data["columns"][0]["name"] == "id"

    def test_sanitize_names_strips_leading_dot(self) -> None:
        """Leading dots are stripped from table and column name fields."""
        data: dict[str, Any] = {
            "name": ".users",
            "columns": [{"name": ".id", "generator": "integer"}],
        }
        _sanitize_names(data)
        assert data["name"] == "users"
        assert data["columns"][0]["name"] == "id"

    def test_sanitize_names_handles_nested_dicts(self) -> None:
        """All column dicts within the columns list are processed."""
        data: dict[str, Any] = {
            "name": ":orders",
            "columns": [
                {"name": ":order_id", "generator": "integer"},
                {"name": ".customer_id", "generator": "integer"},
                {"name": "::total", "generator": "float"},
            ],
        }
        _sanitize_names(data)
        assert data["name"] == "orders"
        assert data["columns"][0]["name"] == "order_id"
        assert data["columns"][1]["name"] == "customer_id"
        assert data["columns"][2]["name"] == "total"


class TestTryRawDecode:
    def test_try_raw_decode_extracts_embedded_json(self) -> None:
        """JSON embedded in prose text is extracted and parsed correctly."""
        content = (
            "Here is the suggested configuration for the users table:\n"
            '{"name": "users", "count": 100, "columns": [{"name": "id", "generator": "integer"}]}\n'
            "Let me know if you need any adjustments."
        )
        result = _try_raw_decode(content)
        assert result is not None
        assert result["name"] == "users"
        assert result["count"] == 100
        assert len(result["columns"]) == 1
        assert result["columns"][0]["name"] == "id"
