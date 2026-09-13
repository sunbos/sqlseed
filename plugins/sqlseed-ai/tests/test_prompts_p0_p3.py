"""Regression tests: prompts must teach LLM about P0-P3 capabilities.

These tests ensure the 3-tier system prompts (full, compact, ultra-compact)
mention template, weighted_choice, lookup, and multi-column derive_from.
If any prompt is rolled back or refactored without these keywords, the LLM
will silently regress to pre-P0-P3 behavior (uniform choice, generic string
codes, independent cross-table values).
"""

from __future__ import annotations

import json

import pytest
from sqlseed_ai._prompts import (
    _COMPACT_SYSTEM_PROMPT,
    _ULTRA_COMPACT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from sqlseed_ai.examples import FEW_SHOT_EXAMPLES

P0_P3_KEYWORDS = [
    "template",
    "weighted_choice",
    "lookup",
    "derive_from",
]

# Rules that must appear in full prompt (most detailed tier)
FULL_PROMPT_REQUIRED_RULES = [
    "round(value * 1.2, 2)",  # expression returns value, not boolean
    "user{sequence:04d}",  # template for UNIQUE username (not word)
    "lookup('items', 'price', value)",  # cross-table lookup example
    "value[0]",  # multi-column derive_from indexing
    "min_length",  # correct string param name (not length)
]


@pytest.mark.parametrize(
    "prompt,name",
    [
        (SYSTEM_PROMPT, "SYSTEM_PROMPT"),
        (_COMPACT_SYSTEM_PROMPT, "_COMPACT_SYSTEM_PROMPT"),
        (_ULTRA_COMPACT_SYSTEM_PROMPT, "_ULTRA_COMPACT_SYSTEM_PROMPT"),
    ],
)
@pytest.mark.parametrize("keyword", P0_P3_KEYWORDS)
def test_prompt_mentions_p0_p3_keyword(prompt: str, name: str, keyword: str) -> None:
    """All 3 prompt tiers must mention template, weighted_choice, lookup, derive_from."""
    assert keyword in prompt, (
        f"{name} missing P0-P3 keyword '{keyword}'. Without it the LLM will not use the corresponding capability."
    )


@pytest.mark.parametrize("rule", FULL_PROMPT_REQUIRED_RULES)
def test_full_prompt_has_p0_p3_rules(rule: str) -> None:
    """Full SYSTEM_PROMPT must contain specific P0-P3 usage rules."""
    assert rule in SYSTEM_PROMPT, (
        f"SYSTEM_PROMPT missing rule snippet '{rule}'. This rule prevents a known LLM failure mode."
    )


def test_ultra_compact_warns_against_word_for_unique() -> None:
    """Ultra-compact prompt must warn against 'word' for UNIQUE username."""
    assert "word" in _ULTRA_COMPACT_SYSTEM_PROMPT.lower()
    assert "unique" in _ULTRA_COMPACT_SYSTEM_PROMPT.lower()


def test_few_shot_examples_cover_p0_p3() -> None:
    """Few-shot examples must demonstrate >=2 P0-P3 features."""
    outputs = [json.dumps(e["output"]) for e in FEW_SHOT_EXAMPLES]
    all_text = "\n".join(outputs)
    features_found = 0
    if "template" in all_text:
        features_found += 1
    if "weighted_choice" in all_text:
        features_found += 1
    if "lookup(" in all_text:
        features_found += 1
    if "value[0]" in all_text:  # multi-column derive_from marker
        features_found += 1
    assert features_found >= 2, (
        f"Few-shot examples only demonstrate {features_found}/4 P0-P3 features; need at least 2 to prime the LLM."
    )


def test_few_shot_examples_includes_merchants_and_order_items() -> None:
    """Few-shot examples should include merchants (template+weighted_choice)
    and order_items (lookup + multi-column derive_from) to mirror the
    complex_biz.db schema used in loop engineering.
    """
    inputs = [e["input"] for e in FEW_SHOT_EXAMPLES]
    assert any("merchants" in i for i in inputs), "Missing merchants example"
    assert any("order_items" in i for i in inputs), "Missing order_items example"
