"""Pure-logic tests for ContextWindowDetector (no LLM calls)."""

from __future__ import annotations

from sqlseed_ai.config import AIConfig
from sqlseed_ai.healer.context_detector import ContextWindowDetector


def test_get_context_window_from_config():
    """AIConfig.max_context_tokens takes priority."""
    cfg = AIConfig(max_context_tokens=16384)
    det = ContextWindowDetector(cfg, model="gemma-4-e2b")
    assert det.get_context_window() == 16384


def test_get_context_window_from_model_map():
    """Model mapping table is used when max_context_tokens is None."""
    cfg = AIConfig(max_context_tokens=None)
    det = ContextWindowDetector(cfg, model="gemma-4-e2b")
    assert det.get_context_window() == 8192


def test_get_context_window_default_fallback():
    """Conservative default 4096 for unknown models."""
    cfg = AIConfig(max_context_tokens=None)
    det = ContextWindowDetector(cfg, model="unknown-model-xyz")
    assert det.get_context_window() == 4096


def test_estimate_tokens_rough():
    """Token estimate is roughly chars / 4."""
    cfg = AIConfig()
    det = ContextWindowDetector(cfg, model="any")
    assert det.estimate_tokens("abcd") == 1
    assert det.estimate_tokens("abcdefgh") == 2


def test_should_skip_level1_above_threshold():
    """token > 60% of context window → skip Level 1."""
    cfg = AIConfig(max_context_tokens=1000)
    det = ContextWindowDetector(cfg, model="any")
    # 700 tokens > 60% of 1000 (600) → True
    assert det.should_skip_level1(prompt="x" * 2800) is True  # 2800 chars / 4 = 700 tokens


def test_should_skip_level1_below_threshold():
    """token ≤ 60% of context window → do not skip Level 1."""
    cfg = AIConfig(max_context_tokens=1000)
    det = ContextWindowDetector(cfg, model="any")
    # 500 tokens ≤ 60% of 1000 (600) → False
    assert det.should_skip_level1(prompt="x" * 2000) is False  # 2000 chars / 4 = 500 tokens
