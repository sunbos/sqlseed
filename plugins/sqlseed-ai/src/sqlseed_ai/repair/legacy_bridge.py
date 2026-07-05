"""Bridge existing 16 rules to stateless functions.

Adversarial fix (B3): The rule set is #14-#20, #22-#30 (16 rules total).
Rule #21 never existed in ``staged_analyzer.py`` — earlier doc references
to "17 rules (Rule #14-#30)" were factually wrong.

微调1 (Section 5.4): distinguishes table-level rules (16, 19, 22, 29)
from column-level rules. Table-level rules receive table_config in ctx.
"""

from __future__ import annotations

from typing import ClassVar


class LegacyRuleBridge:
    """Bridge existing 16 rules to stateless functions.

    Adversarial fix (B3): The rule set is #14-#20, #22-#30 (16 rules total).
    Rule #21 never existed in ``staged_analyzer.py`` — earlier doc references
    to "17 rules (Rule #14-#30)" were factually wrong.
    """

    TABLE_LEVEL_RULES: ClassVar[frozenset[int]] = frozenset({16, 19, 22, 29})
    RULE_MAPPING: ClassVar[dict[int, str]] = {
        14: "normalize_params",
        15: "bound_regex",  # Legacy-only (no stateless impl yet)
        16: "align_fk_max_value",
        17: "handle_boolean_derive",  # Legacy-only
        18: "limit_future_year",  # Legacy-only
        19: "adjust_bounds",
        20: "fix_self_reference",
        22: "isolate_date_ranges",
        23: "upgrade_phone_to_pattern",  # Legacy-only
        24: "upgrade_to_template",
        25: "downgrade_text_to_string",  # Legacy-only
        26: "coerce_float_to_int",
        27: "infer_derive_from_check",  # Legacy-only
        28: "semantic_upgrade",
        29: "break_derive_from_cycle",
        30: "switch_generator",
    }

    @staticmethod
    def is_table_level(rule_num: int) -> bool:
        """Return True if the rule operates at table level (微调1)."""
        return rule_num in LegacyRuleBridge.TABLE_LEVEL_RULES

    @staticmethod
    def strategy_name_for(rule_num: int) -> str | None:
        """Return the stateless strategy name for a legacy rule, or None."""
        return LegacyRuleBridge.RULE_MAPPING.get(rule_num)
