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


def parse_json_response(content: str) -> dict[str, Any]:
    """Parse JSON from LLM response using 4-strategy fallback."""
    cleaned = _strip_channel_prefix(content.strip())

    return _try_direct_parse(cleaned) or _try_markdown_fence_parse(cleaned) or _try_raw_decode(cleaned) or {}


def _strip_channel_prefix(content: str) -> str:
    """Strip Gemma 4 ``<|channel>thought ... <channel|>`` prefix if present.

    Returns content unchanged when no ``<channel|>`` marker is found, so
    non-Gemma models (OpenAI, Anthropic, etc.) are unaffected.
    """
    idx = content.rfind(_CHANNEL_END_MARKER)
    if idx < 0:
        return content
    return content[idx + len(_CHANNEL_END_MARKER) :].strip()


def _try_direct_parse(content: str) -> dict[str, Any] | None:
    """Strategy 1: Direct parse (ideal case — model outputs raw JSON)."""
    try:
        result = json.loads(content)
        if isinstance(result, dict):
            _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    return None


def _try_markdown_fence_parse(content: str) -> dict[str, Any] | None:
    """Strategy 2: Strip markdown code fences (```json\n{...}\n```)."""
    open_idx = content.find("```")
    if open_idx < 0:
        return None
    after_open = content[open_idx + 3 :]
    nl_pos = after_open.find("\n")
    if nl_pos < 0:
        return None
    content_start = nl_pos + 1
    close_idx = after_open.find("```", content_start)
    if close_idx < 0:
        return None
    fence_content = after_open[content_start:close_idx].strip()
    try:
        result = json.loads(fence_content)
        if isinstance(result, dict):
            _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    return None


def _try_raw_decode(content: str) -> dict[str, Any] | None:
    """Strategy 3: Find first '{' and use json.JSONDecoder.raw_decode().

    Handles explanatory text before/after JSON without code fences.
    raw_decode() correctly handles braces inside JSON strings.

    Also repairs truncated JSON by attempting to add missing closing
    brackets/braces. Small LLMs (e.g., Gemma 4 E2B) sometimes emit JSON
    missing the final ``}`` or ``]`` characters even when stopReason is
    "eosFound". We try a small set of suffix combinations to recover.
    """
    first_brace = content.find("{")
    if first_brace < 0:
        return None
    decoder = json.JSONDecoder()
    # Try parsing as-is first (complete JSON embedded in prose).
    try:
        result, _ = decoder.raw_decode(content, idx=first_brace)
        if isinstance(result, dict):
            _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    # Repair truncated JSON by appending missing closers. The suffixes are
    # ordered from shortest to longest; each is tried in isolation. We stop
    # at the first suffix that yields a valid dict.
    for suffix in ("}", "]", "}}", "]}", "]}]}", "]}"):
        try:
            result, _ = decoder.raw_decode(content + suffix, idx=first_brace)
            if isinstance(result, dict):
                _sanitize_names(result)
                return result
        except json.JSONDecodeError:
            continue
    return None


def _sanitize_names(data: dict[str, Any]) -> None:
    """Strip leading colons/dots from table and column name fields.

    Some LLMs prepend ``:`` or ``.`` to names (e.g., ``":users"``).
    This mutates ``data`` in place, cleaning ``data["name"]`` and every
    column's ``name`` inside ``data["columns"]``.
    """
    name = data.get("name")
    if isinstance(name, str):
        data["name"] = re.sub(r"^[:.]+", "", name)

    for col in data.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
