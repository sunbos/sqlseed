from __future__ import annotations

import json
import re
from typing import Any


def parse_json_response(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            _sanitize_names(result)
            return result
    except json.JSONDecodeError:
        pass

    return {}


def _sanitize_names(data: dict[str, Any]) -> None:
    name = data.get("name")
    if isinstance(name, str):
        data["name"] = re.sub(r"^[:.]+", "", name)

    for col in data.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
