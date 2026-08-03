"""基于 CHECK 约束的用户 YAML 配置确定性适配。

core 是确定性执行器，CHECK 是既定事实。本模块在 ``_resolve_specs`` 阶段，
把用户 YAML 配置（``ColumnConfig.params``）与该列 CHECK 解析结果（
``CheckConstraintParser``）做机械比对，用 CHECK 边界钳制生成值域：

- **有交集** → 钳制到交集（生成数据必然合法），并 ``logger.info`` 告知。
- **无交集** → 必然全部违规，抛出 ``ConfigurationError``（指明列名 +
  CHECK + 用户值），不生成。

明确不处理（保持原样，交由 AI / 人工）：
- 派生列（``derive_from`` 模式，无独立生成值域）
- CHECK 无法确定性解析的列（跨列 / OR / 引用列边界 —— check_parser 已降级返回 None）

提示语言跟随 orchestrator 的 ``locale``：``zh*`` → 中文，其余 → 英文。
这是"用既定事实修正配置"，不是理解业务意图。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.core.check_parser import CheckConstraintParser, ParsedCheck
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from sqlseed.config.models import ColumnConfig

logger = get_logger(__name__)

# 生成器门控：只有这些生成器接受对应参数（与修复管线的
# _GENERATOR_PARAM_WHITELIST 对齐）。不在门控内的生成器（如 pattern、
# template）无法机械映射 CHECK 边界，保持原样交由 AI/人工。
_RANGE_GENERATORS = frozenset({"integer", "random_int", "float", "random_float"})
_INT_RANGE_GENERATORS = frozenset({"integer", "random_int"})
_LENGTH_GENERATORS = frozenset({"string", "text"})
_CHOICE_GENERATORS = frozenset({"choice", "weighted_choice"})


def _is_chinese_locale(locale: str) -> bool:
    """locale 以 zh 开头（zh / zh_CN / zh-CN ...）视为中文。"""
    return locale.lower().replace("-", "_").startswith("zh")


class CheckAdapter:
    """用 CHECK 既定事实钳制用户配置的生成值域。

    无状态；``locale`` 决定提示语言。
    """

    def __init__(self, locale: str = "en_US") -> None:
        self._zh = _is_chinese_locale(locale)

    def adapt_user_configs(
        self,
        user_configs: dict[str, ColumnConfig],
        check_expressions: list[str],
    ) -> None:
        """就地钳制 user_configs 中每个 source-mode 列的 params。

        Args:
            user_configs: 用户配置的列名 -> ColumnConfig。
            check_expressions: 该表的全部 CHECK 表达式（含 CONSTRAINT/CHECK 前缀）。

        Raises:
            ConfigurationError: 用户值域与 CHECK 完全无交集（必然全部违规）。
        """
        if not check_expressions:
            return
        for col_name, cc in user_configs.items():
            if not self._is_source_mode(cc):
                continue
            parsed = CheckConstraintParser.parse_all(col_name, check_expressions)
            if parsed is None:
                continue  # 跨列 / 无法解析 → 保持原样，交 AI/人工
            self._adapt_column(cc, parsed)

    @staticmethod
    def _is_source_mode(cc: ColumnConfig) -> bool:
        """仅 source-mode（有 generator，无 derive_from）才有独立生成值域可钳制。"""
        return bool(getattr(cc, "generator", None)) and not getattr(cc, "derive_from", None)

    def _adapt_column(self, cc: ColumnConfig, parsed: ParsedCheck) -> None:
        params: dict[str, Any] = cc.params
        generator = getattr(cc, "generator", "") or ""
        if parsed.kind == "range" and generator in _RANGE_GENERATORS:
            self._clamp_range(cc, params, parsed, integer=generator in _INT_RANGE_GENERATORS)
        elif parsed.kind == "choice" and generator in _CHOICE_GENERATORS:
            self._clamp_choices(cc, params, parsed, weighted=(generator == "weighted_choice"))
        elif parsed.kind == "length_range" and generator in _LENGTH_GENERATORS:
            self._clamp_length(cc, params, parsed)

    # ------------------------------------------------------------------ range
    def _clamp_range(
        self,
        cc: ColumnConfig,
        params: dict[str, Any],
        parsed: ParsedCheck,
        *,
        integer: bool,
    ) -> None:
        lo = parsed.min_value
        hi = parsed.max_value
        user_lo = params.get("min_value")
        user_hi = params.get("max_value")

        # 用户未设置的边界直接采用 CHECK 边界（不视为"修正"，仅 logger.info）。
        eff_lo = user_lo if user_lo is not None else lo
        eff_hi = user_hi if user_hi is not None else hi

        new_lo = eff_lo if lo is None or eff_lo is None else max(eff_lo, lo)
        new_hi = eff_hi if hi is None or eff_hi is None else min(eff_hi, hi)

        # 严格边界处理（仅当 CHECK 边界为生效边界时才需要内收）：
        # - integer 生成器：值域为整数，x > 0.5 → min=1（floor+1），x < 5.0 → max=4（ceil-1）；
        #   非严格浮点边界按 ceil/floor 取整（0.5 <= x <= 9.5 → [1, 9]）。
        # - float 生成器：round(uniform(lo, hi), precision) 可能恰好命中边界值
        #   （uniform 含下界，banker's rounding 会吞掉 nextafter 级别的 epsilon），
        #   故向域内收进一个完整精度单位，保证生成值严格满足不等式。
        precision = params.get("precision", 2)
        step = 10 ** -int(precision)
        if new_lo is not None:
            exclusive = parsed.min_exclusive and lo is not None and new_lo == lo
            if integer:
                new_lo = math.floor(new_lo) + 1 if exclusive else math.ceil(new_lo)
            elif exclusive:
                new_lo = new_lo + step
        if new_hi is not None:
            exclusive = parsed.max_exclusive and hi is not None and new_hi == hi
            if integer:
                new_hi = math.ceil(new_hi) - 1 if exclusive else math.floor(new_hi)
            elif exclusive:
                new_hi = new_hi - step

        if new_lo is not None and new_hi is not None and new_lo > new_hi:
            self._raise_no_intersection(cc, parsed, f"[{user_lo}, {user_hi}]")

        changed = False
        if new_lo is not None and new_lo != user_lo:
            params["min_value"] = new_lo
            changed = True
        if new_hi is not None and new_hi != user_hi:
            params["max_value"] = new_hi
            changed = True
        if changed:
            if user_lo is not None or user_hi is not None:
                self._notify_clamped(cc, parsed, f"[{user_lo}, {user_hi}] -> [{new_lo}, {new_hi}]")
            else:
                # 裸生成器补全：用户未设边界，静默采用 CHECK 边界（与
                # SchemaFallbackGenerator 的零配置推断行为一致）。
                logger.info("check_adopt", column=cc.name, min_value=new_lo, max_value=new_hi)

    # ----------------------------------------------------------------- choice
    def _clamp_choices(self, cc: ColumnConfig, params: dict[str, Any], parsed: ParsedCheck, *, weighted: bool) -> None:
        allowed = list(parsed.choices)
        if weighted:
            self._clamp_weighted(cc, params, allowed, parsed)
            return

        user_choices = params.get("choices")
        if not isinstance(user_choices, list) or not user_choices:
            # 裸 choice 生成器缺 choices 会在生成时 ValueError；CHECK 枚举
            # 既是钳制也是补全（静默采用，与零配置推断一致）。
            params["choices"] = allowed
            logger.info("check_adopt", column=cc.name, choices=allowed)
            return
        intersection = [c for c in user_choices if c in allowed]
        if not intersection:
            self._raise_no_intersection(cc, parsed, repr(user_choices))
        if len(intersection) != len(user_choices):
            dropped = [c for c in user_choices if c not in allowed]
            params["choices"] = intersection
            self._notify_clamped(cc, parsed, f"dropped {dropped}")

    def _clamp_weighted(
        self,
        cc: ColumnConfig,
        params: dict[str, Any],
        allowed: list[Any],
        parsed: ParsedCheck,
    ) -> None:
        """weighted_choice 的两种参数形态钳制：

        - ``weighted_choices`` 字典 {value: weight}
        - ``choices`` 字典列表 [{\"value\": v, \"weight\": w}, ...]

        标量列表等未文档化形态保持原样。裸配置（无有效参数）采用均匀权重补全。
        """
        weighted_choices = params.get("weighted_choices")
        choices = params.get("choices")

        if isinstance(weighted_choices, dict) and weighted_choices:
            intersection = {v: w for v, w in weighted_choices.items() if v in allowed}
            if not intersection:
                self._raise_no_intersection(cc, parsed, repr(weighted_choices))
            if len(intersection) != len(weighted_choices):
                dropped = [v for v in weighted_choices if v not in allowed]
                params["weighted_choices"] = intersection
                self._notify_clamped(cc, parsed, f"dropped {dropped}")
            return

        if isinstance(choices, list) and choices:
            dict_form = [c for c in choices if isinstance(c, dict) and "value" in c]
            if len(dict_form) != len(choices):
                return  # 非标量/字典混排等未文档化形态 → 保持原样
            kept = [c for c in dict_form if c["value"] in allowed]
            if not kept:
                self._raise_no_intersection(cc, parsed, repr(choices))
            if len(kept) != len(dict_form):
                dropped = [c["value"] for c in dict_form if c["value"] not in allowed]
                params["choices"] = kept
                self._notify_clamped(cc, parsed, f"dropped {dropped}")
            return

        # 裸 weighted_choice：采用 CHECK 枚举 + 均匀权重（静默补全）。
        params["weighted_choices"] = {v: 1 for v in allowed}
        logger.info("check_adopt", column=cc.name, weighted_choices=params["weighted_choices"])

    # ----------------------------------------------------------------- length
    def _clamp_length(self, cc: ColumnConfig, params: dict[str, Any], parsed: ParsedCheck) -> None:
        lo = parsed.min_length
        hi = parsed.max_length
        user_lo = params.get("min_length")
        user_hi = params.get("max_length")

        eff_lo = user_lo if user_lo is not None else lo
        eff_hi = user_hi if user_hi is not None else hi
        new_lo = eff_lo if lo is None or eff_lo is None else max(eff_lo, lo)
        new_hi = eff_hi if hi is None or eff_hi is None else min(eff_hi, hi)

        if new_lo is not None and new_hi is not None and new_lo > new_hi:
            self._raise_no_intersection(cc, parsed, f"length[{user_lo}, {user_hi}]")

        changed = False
        if new_lo is not None and new_lo != user_lo:
            params["min_length"] = new_lo
            changed = True
        if new_hi is not None and new_hi != user_hi:
            params["max_length"] = new_hi
            changed = True
        if changed:
            if user_lo is not None or user_hi is not None:
                self._notify_clamped(cc, parsed, f"length[{user_lo}, {user_hi}] -> [{new_lo}, {new_hi}]")
            else:
                # 裸生成器补全：静默采用 CHECK 长度边界。
                logger.info("check_adopt", column=cc.name, min_length=new_lo, max_length=new_hi)

    # ----------------------------------------------------------------- output
    def _describe_check(self, parsed: ParsedCheck) -> str:
        if parsed.kind == "range":
            return f"[{parsed.min_value}, {parsed.max_value}]"
        if parsed.kind == "choice":
            return f"IN {list(parsed.choices)}"
        return f"length[{parsed.min_length}, {parsed.max_length}]"

    def _notify_clamped(self, cc: ColumnConfig, parsed: ParsedCheck, detail: str) -> None:
        check_desc = self._describe_check(parsed)
        if self._zh:
            msg = f"列 '{cc.name}' 的 YAML 取值已按 CHECK 约束 {check_desc} 钳制: {detail}"
        else:
            msg = f"Column '{cc.name}' YAML value clamped to CHECK constraint {check_desc}: {detail}"
        logger.info("check_clamp", column=cc.name, detail=detail)
        # 同时走 warning，确保 CLI 默认日志级别下用户能看到这次修正。
        logger.warning(msg)

    def _raise_no_intersection(self, cc: ColumnConfig, parsed: ParsedCheck, user_desc: str) -> None:
        check_desc = self._describe_check(parsed)
        if self._zh:
            msg = (
                f"列 '{cc.name}' 的 YAML 取值 {user_desc} 与 CHECK 约束 {check_desc} "
                f"完全无交集，生成数据必然违规。请调整 YAML 配置（或改用 AI 分析）。"
            )
        else:
            msg = (
                f"Column '{cc.name}' YAML value {user_desc} has no overlap with CHECK "
                f"constraint {check_desc}; generated data would always violate it. "
                f"Adjust the YAML config (or use AI analysis)."
            )
        logger.error("check_no_intersection", column=cc.name, user=user_desc, check=check_desc)
        raise ConfigurationError(msg)
