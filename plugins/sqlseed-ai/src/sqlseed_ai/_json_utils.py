from __future__ import annotations

import json
import re
from typing import Any


def parse_json_response(content: str) -> dict[str, Any]:
    """Parse JSON from LLM response using 3-strategy fallback."""
    cleaned = content.strip()

    return _try_direct_parse(cleaned) or _try_markdown_fence_parse(cleaned) or _try_raw_decode(cleaned) or {}


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
    """Strategy 2: Strip markdown code fences (```json\\n{...}\\n```)."""
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
    """
    first_brace = content.find("{")
    if first_brace < 0:
        return None
    try:
        decoder = json.JSONDecoder()
        result, _ = decoder.raw_decode(content, idx=first_brace)
        if isinstance(result, dict):
            _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass
    return None


def _sanitize_names(data: dict[str, Any]) -> None:
    name = data.get("name")
    if isinstance(name, str):
        data["name"] = re.sub(r"^[:.]+", "", name)

    for col in data.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
