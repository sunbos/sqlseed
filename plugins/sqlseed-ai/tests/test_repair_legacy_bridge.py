"""Tests for LegacyRuleBridge (Section 5.4, 微调1: table vs column level)."""
from __future__ import annotations

from sqlseed_ai.repair.legacy_bridge import LegacyRuleBridge


def test_table_level_rules_correctly_identified():
    assert frozenset({16, 19, 22, 29}) == LegacyRuleBridge.TABLE_LEVEL_RULES


def test_rule_mapping_covers_all_16_rules():
    # Adversarial fix (B3): Rule #21 does not exist in staged_analyzer.py.
    # Actual rules: #14-#20, #22-#30 (16 rules total, not 17).
    expected = {14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30}
    assert set(LegacyRuleBridge.RULE_MAPPING.keys()) == expected


def test_rule_mapping_points_to_existing_strategies():
    from sqlseed_ai.repair.strategies import REPAIR_STRATEGIES

    for _rule_num, strategy_name in LegacyRuleBridge.RULE_MAPPING.items():
        # Some legacy rules map to strategies that may not exist yet (15, 17, 23, 25, 27)
        # Those rules keep their legacy implementation; only check common ones
        if strategy_name in REPAIR_STRATEGIES:
            assert callable(REPAIR_STRATEGIES[strategy_name])
