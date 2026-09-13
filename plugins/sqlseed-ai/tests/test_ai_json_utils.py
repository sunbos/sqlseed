"""Tests for JSON parsing utilities in _json_utils.py.

Covers the ``_sanitize_names`` mutation helper (strips leading colons
and dots from table/column name fields), the ``_try_raw_decode``
strategy that extracts JSON embedded in prose text, and the Gemma 4
channel-format prefix stripping (``<|channel>thought ... <channel|>``).
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from sqlseed_ai._json_utils import _sanitize_names, _strip_channel_prefix, _try_raw_decode, parse_json_response
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

    def test_try_raw_decode_repairs_truncated_json(self) -> None:
        """Truncated JSON missing final closing brace is repaired and parsed."""
        # Simulates Gemma 4 E2B output that ends with `]}]` instead of `]}]}`.
        content = '{"tables":[{"name":"users","columns":[{"name":"id","generator":"integer"}]}]'
        result = _try_raw_decode(content)
        assert result is not None
        assert "tables" in result
        assert result["tables"][0]["name"] == "users"
        assert len(result["tables"][0]["columns"]) == 1


class TestStripChannelPrefix:
    """Gemma 4 (and similar reasoning models in LM Studio) emit reasoning in
    a ``<|channel>thought ... <channel|>`` envelope before the actual JSON.
    """

    def test_strip_channel_prefix_returns_content_after_marker(self) -> None:
        """Content after the <channel|> marker is returned verbatim."""
        content = '<|channel>thought\nSome reasoning.\n<channel|>{"tables":[]}'
        result = _strip_channel_prefix(content)
        assert result == '{"tables":[]}'

    def test_strip_channel_prefix_returns_content_unchanged_without_marker(self) -> None:
        """Content without the marker is returned unchanged."""
        content = '{"tables":[]}'
        result = _strip_channel_prefix(content)
        assert result == '{"tables":[]}'

    def test_strip_channel_prefix_uses_last_marker(self) -> None:
        """When multiple <channel|> markers exist, the LAST one is used."""
        content = "<channel|>first<channel|>second"
        result = _strip_channel_prefix(content)
        assert result == "second"


class TestParseJsonResponseGemma4:
    """End-to-end tests using realistic Gemma 4 E2B output captured from
    LM Studio log stream. These regress the bug where the parser returned
    ``{}`` because the reasoning text contained regex quantifiers (``{3}``)
    and example JSON snippets (``{"weighted_choices": ...}``) that confused
    the raw_decode strategy.
    """

    def test_parse_gemma4_channel_format_with_regex_in_thinking(self) -> None:
        """Reasoning text with regex quantifiers {3} {4} no longer breaks parsing."""
        content = (
            "<|channel>thought\n"
            "Thinking Process:\n"
            '1. Use pattern("^\\d{3}-\\d{3}-\\d{4}$") for phone.\n'
            '2. Use weighted_choice({"weighted_choices": {"a": 50, "b": 30}}) for role.\n'
            '<channel|>{"tables":[{"name":"users","count":1000,"columns":['
            '{"name":"phone","generator":"pattern","params":{"pattern":"^[0-9]{3}-[0-9]{3}-[0-9]{4}$"}},'
            '{"name":"role","generator":"weighted_choice","params":{"weighted_choices":{"a":50,"b":30}}}'
            "]}]}"
        )
        result = parse_json_response(content)
        assert "tables" in result
        assert result["tables"][0]["name"] == "users"
        assert len(result["tables"][0]["columns"]) == 2
        assert result["tables"][0]["columns"][1]["generator"] == "weighted_choice"

    def test_parse_gemma4_channel_format_truncated_json(self) -> None:
        """Truncated JSON (missing final }) is repaired even after channel strip."""
        # Real Gemma 4 E2B output: ends with `]}]` instead of `]}]}`.
        content = (
            "<|channel>thought\n"
            'Reasoning here with example {"weighted_choices": {"a": 1}} in text.\n'
            '<channel|>{"tables":[{"name":"users","count":1000,"columns":['
            '{"name":"id","generator":"integer"}]}]'
        )
        result = parse_json_response(content)
        assert "tables" in result
        assert result["tables"][0]["name"] == "users"
