"""Tests for prompt templates (_prompts.py) and Gemma tool definitions (_tools.py).

Verifies that all system prompts are non-empty strings, that the three
verbosity tiers decrease in length, that critical column-exclusion keywords
appear across the prompts, and that GEMMA_TOOLS is a well-formed function
declaration with the expected parameters.
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from sqlseed_ai._prompts import (
        _COMPACT_SYSTEM_PROMPT,
        _ULTRA_COMPACT_SYSTEM_PROMPT,
        SYSTEM_PROMPT,
        TEMPLATE_SYSTEM_PROMPT,
    )
    from sqlseed_ai._tools import GEMMA_TOOLS
except ImportError:
    pytest.skip("sqlseed-ai not installed", allow_module_level=True)


class TestPromptTemplates:
    def test_system_prompt_is_nonempty_string(self) -> None:
        """Verify SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 0

    def test_compact_system_prompt_is_nonempty_string(self) -> None:
        """Verify _COMPACT_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(_COMPACT_SYSTEM_PROMPT, str)
        assert len(_COMPACT_SYSTEM_PROMPT) > 0

    def test_ultra_compact_system_prompt_is_nonempty_string(self) -> None:
        """Verify _ULTRA_COMPACT_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(_ULTRA_COMPACT_SYSTEM_PROMPT, str)
        assert len(_ULTRA_COMPACT_SYSTEM_PROMPT) > 0

    def test_ultra_compact_shorter_than_compact(self) -> None:
        """Verify _ULTRA_COMPACT_SYSTEM_PROMPT is shorter than _COMPACT_SYSTEM_PROMPT."""
        assert len(_ULTRA_COMPACT_SYSTEM_PROMPT) < len(_COMPACT_SYSTEM_PROMPT)

    def test_compact_shorter_than_system(self) -> None:
        """Verify _COMPACT_SYSTEM_PROMPT is shorter than SYSTEM_PROMPT."""
        assert len(_COMPACT_SYSTEM_PROMPT) < len(SYSTEM_PROMPT)

    def test_template_system_prompt_is_nonempty_string(self) -> None:
        """Verify TEMPLATE_SYSTEM_PROMPT is a non-empty string."""
        assert isinstance(TEMPLATE_SYSTEM_PROMPT, str)
        assert len(TEMPLATE_SYSTEM_PROMPT) > 0

    def test_prompts_contain_critical_exclusions(self) -> None:
        """Verify the prompts collectively mention PRIMARY KEY, AUTOINCREMENT,
        DEFAULT, UNIQUE, and CHECK exclusions.

        The ultra-compact prompt explicitly lists all five; the full and compact
        prompts cover subsets. This assertion checks the union of all prompts so
        that a regression removing any keyword from every prompt is caught.
        """
        all_prompts = SYSTEM_PROMPT + "\n" + _COMPACT_SYSTEM_PROMPT + "\n" + _ULTRA_COMPACT_SYSTEM_PROMPT
        upper = all_prompts.upper()
        for keyword in ("PRIMARY KEY", "AUTOINCREMENT", "DEFAULT", "UNIQUE", "CHECK"):
            assert keyword in upper, f"Critical exclusion keyword '{keyword}' not found in any prompt"


class TestGemmaTools:
    def test_gemma_tools_is_list(self) -> None:
        """Verify GEMMA_TOOLS is a list or tuple."""
        assert isinstance(GEMMA_TOOLS, (list, tuple))
        assert len(GEMMA_TOOLS) > 0

    def test_gemma_tools_has_function_declaration(self) -> None:
        """Verify GEMMA_TOOLS contains a function declaration with a name.

        The current implementation declares an ``analyze_schema`` function
        (the README references ``generate_column_config``; both are valid
        historical names for the schema-analysis tool).
        """
        tool: dict[str, Any]
        for tool in GEMMA_TOOLS:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                assert "name" in func
                assert isinstance(func["name"], str)
                assert len(func["name"]) > 0
                return
        raise RuntimeError("No function declaration found in GEMMA_TOOLS")

    def test_gemma_tools_function_has_required_params(self) -> None:
        """Verify the function declaration has parameters with expected keys.

        The ``analyze_schema`` tool declares ``table_name`` and ``columns`` as
        required parameters (the README references ``column_name`` and
        ``generator_name`` for the legacy ``generate_column_config`` name).
        """
        tool: dict[str, Any]
        for tool in GEMMA_TOOLS:
            if tool.get("type") == "function" and "function" in tool:
                params = tool["function"].get("parameters", {})
                assert params.get("type") == "object"
                properties = params.get("properties", {})
                required = params.get("required", [])
                # The tool must declare at least one property and mark it required
                assert len(properties) > 0
                assert len(required) > 0
                # table_name and columns are the canonical required params
                assert "table_name" in properties
                assert "columns" in properties
                assert "table_name" in required
                assert "columns" in required
                return
        raise RuntimeError("No function declaration found in GEMMA_TOOLS")
