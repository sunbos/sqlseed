"""Shared CLI utility functions."""

from __future__ import annotations

import re
from typing import Any


def sanitize_table_config(config_dict: dict[str, Any]) -> None:
    """Remove leading dots/colons from table and column names in config dict.

    Args:
        config_dict: Configuration dictionary to sanitize in-place.
    """
    name = config_dict.get("name")
    if isinstance(name, str):
        config_dict["name"] = re.sub(r"^[:.]+", "", name)
    for col in config_dict.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)
