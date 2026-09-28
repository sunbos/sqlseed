"""JSON parsing utilities for LLM responses.

Provides :func:`parse_json_response`, a robust 4-strategy parser that
extracts JSON from LLM output (raw JSON, markdown-fenced JSON, or JSON
embedded in prose) and normalizes the resulting dict via
:func:`_sanitize_names`.

Strategy order:
1. Strip Gemma 4 channel-format prefix (``<|channel>thought ... <channel|>``)
   if present, so reasoning text with regex quantifiers (``{3}``) or example
   JSON snippets (``{"weighted_choices": ...}``) does not confuse later
   strategies.
2. Direct parse (ideal case — model outputs raw JSON).
3. Strip markdown code fences.
4. Find first ``{`` and use ``json.JSONDecoder.raw_decode()`` to handle
   JSON embedded in prose.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Gemma 4 (and similar reasoning models in LM Studio) emit reasoning in a
# "thought channel" before the actual response. The format is:
#     <|channel>thought
#     ... reasoning text ...
#     <channel|>actual response
# The reasoning text often contains regex quantifiers ({3}, {4}) and example
# JSON snippets ({"weighted_choices": {...}}) that confuse JSON parsers.
# We strip everything before the LAST <channel|> separator so downstream
# strategies see only the actual model response.
_CHANNEL_END_MARKER = "<channel|>"


class JSONResponseError(ValueError):
    """A safe, content-free diagnostic for an unusable model response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_json_response(content: str, *, strict: bool = False, preserve_names: bool = False) -> dict[str, Any]:
    """Parse JSON, optionally preserving identifiers for schema-aware validation.

    Strict mode diagnoses failures without inventing missing values. Name
    preservation leaves leading punctuation untouched; it does not relax JSON
    parsing or the caller's responsibility to validate the returned document.
    """
    cleaned = _strip_channel_prefix(content.strip())

    if strict and not cleaned:
        raise JSONResponseError("empty_response")
    for parser in (_try_direct_parse, _try_markdown_fence_parse, _try_raw_decode):
        result = parser(cleaned, preserve_names=preserve_names)
        if result is not None:
            return result
    if strict:
        raise JSONResponseError("invalid_json")
    return {}


def _strip_channel_prefix(content: str) -> str:
    """Strip Gemma 4 ``<|channel>thought ... <channel|>`` prefix if present.

    Returns content unchanged when no ``<channel|>`` marker is found, so
    non-Gemma models (OpenAI, Anthropic, etc.) are unaffected.
    """
    if (idx := content.rfind(_CHANNEL_END_MARKER)) < 0:
        return content
    return content[idx + len(_CHANNEL_END_MARKER) :].strip()


def _try_direct_parse(content: str, *, preserve_names: bool = False) -> dict[str, Any] | None:
    """Strategy 1: Direct parse (ideal case — model outputs raw JSON)."""
    try:
        result = json.loads(content)
        if isinstance(result, dict):
            if not preserve_names:
                _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    return None


def _try_markdown_fence_parse(content: str, *, preserve_names: bool = False) -> dict[str, Any] | None:
    """Strategy 2: Strip markdown code fences (```json\n{...}\n```)."""
    if (open_idx := content.find("```")) < 0:
        return None
    after_open = content[open_idx + 3 :]
    if (nl_pos := after_open.find("\n")) < 0:
        return None
    content_start = nl_pos + 1
    if (close_idx := after_open.find("```", content_start)) < 0:
        return None
    fence_content = after_open[content_start:close_idx].strip()
    return _try_raw_decode(fence_content, preserve_names=preserve_names)


def _try_raw_decode(content: str, *, preserve_names: bool = False) -> dict[str, Any] | None:
    """Strategy 3: Find first '{' and use json.JSONDecoder.raw_decode().

    Handles explanatory text before/after JSON without code fences.
    raw_decode() correctly handles braces inside JSON strings.

    Also repairs truncated JSON by attempting to add missing closing
    brackets/braces. Small LLMs (e.g., Gemma 4 E2B) sometimes emit JSON
    missing the final ``}`` or ``]`` characters even when stopReason is
    "eosFound". Recover only the delimiters determined by the JSON nesting.
    """
    if (first_brace := content.find("{")) < 0:
        return None
    decoder = json.JSONDecoder()
    # Try parsing as-is first (complete JSON embedded in prose).
    try:
        result, _ = decoder.raw_decode(content, idx=first_brace)
        if isinstance(result, dict):
            if not preserve_names:
                _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    # Never invent missing strings, values or separators.
    candidate = content[first_brace:].strip()
    closers = _missing_closers(candidate)
    if closers:
        return _try_direct_parse(candidate + closers, preserve_names=preserve_names)
    return None


def _missing_closers(content: str) -> str:
    """Complete delimiters only, never strings, keys, commas or business values."""
    stack: list[str] = []
    quoted = escaped = False
    for char in content:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and (not stack or stack.pop() != char):
            return ""
    if quoted or not stack or len(stack) > 8:
        return ""
    return "".join(reversed(stack))


def _sanitize_names(data: dict[str, Any]) -> None:
    """Strip leading colons/dots from table and column name fields.

    Some LLMs prepend ``:`` or ``.`` to names (e.g., ``":users"``).
    This mutates ``data`` in place, cleaning ``data["name"]`` and every
    column's ``name`` inside ``data["columns"]``.
    """
    name = data.get("name")
    if isinstance(name, str):
        data["name"] = re.sub(r"^[:.]+", "", name)

    columns = data.get("columns")
    if not isinstance(columns, list):
        # Preserve malformed containers for the configuration validator. Name
        # normalization must not turn valid JSON into an incidental TypeError.
        return
    for col in columns:
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
