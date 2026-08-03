"""基于 sqlglot AST 的单列 CHECK 约束解析器。

本模块读取数据库 schema 语义（CHECK 约束），仅提取"能 100% 确定转换为生成参数"
的单列字面量约束，翻译成生成器提示。无法确定映射的形态一律明确降级（返回 None），
交由上层 AI/人工 YAML 配置处理，绝不硬猜：

- 跨列运算/比较（如 discount <= subtotal、price * quantity <= 10000）
- OR 连接的非等值条件（如 age >= 18 OR age IS NULL）
- LIKE 模式匹配、IS NULL / IS NOT NULL、NOT IN / NOT BETWEEN
- 非纯字面量（含函数调用、子查询、表达式）

这是 schema 语义而非业务逻辑：把 CHECK(x >= 0) 解析为 min_value=0 是读取 schema
声明，不是理解业务意图。core 是确定性执行器，CHECK 是既定事实。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, cast

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError


@dataclass(frozen=True)
class ParsedCheck:
    """针对某一列解析 CHECK 约束的结果。

    Attributes:
        column: 该约束作用的目标列名。
        kind: 生成器提示类型："choice" | "range" | "length_range"。
        choices: kind 为 "choice" 时的允许取值元组。
        min_value: kind 为 "range" 时的下界（含），保持与字面量一致的 int/float 类型。
        max_value: kind 为 "range" 时的上界（含），同上。
        min_length: kind 为 "length_range" 时的最小长度（含）。
        max_length: kind 为 "length_range" 时的最大长度（含）。
        min_exclusive: min_value 为严格下界（浮点严格不等式无法按整数语义收一，仅记录）。
        max_exclusive: max_value 为严格上界（同上）。
    """

    column: str
    kind: str
    choices: tuple[Any, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_exclusive: bool = False
    max_exclusive: bool = False


class _Bound(NamedTuple):
    """从单次比较中提取的一个边界。"""

    kind: Literal["range", "length"]
    is_lower: bool
    value: int | float
    strict: bool


class CheckConstraintParser:
    """将单列 CHECK 约束解析为生成器提示。

    约束体解析完全基于 sqlglot AST（不使用正则）；仅保留 _CHECK_INNER_RE 一个
    正则用于剥离可选的 CONSTRAINT name CHECK(...) / CHECK(...) 前缀。
    所有方法均为静态方法，解析器无状态、线程安全。

    AND 连接的同列双边界会完整合并（如 age>=18 AND age<=120 → min=18, max=120）；
    多列 CHECK（如 price>=0 AND stock>=0）只提取目标列的条件，其余合取项跳过。
    跨列引用与其他不可确定映射的形态明确降级，返回 None。
    """

    _CHECK_INNER_RE = re.compile(
        r"^\s*"
        r'(?:CONSTRAINT\s+(?:\w+|"[^"]+"|`[^`]+`|\[[^\]]+\])\s+)?'
        r"CHECK\s*\((?P<inner>.*)\)\s*$",
        re.IGNORECASE | re.DOTALL,
    )

    @staticmethod
    def parse(target_column: str, expression: str) -> ParsedCheck | None:
        """解析针对 target_column 的单列 CHECK 表达式。

        Args:
            target_column: 目标列名。
            expression: CHECK 约束 SQL 表达式（可带 CONSTRAINT name CHECK(...) 前缀）。

        Returns:
            表达式以可确定性解析的单列字面量模式约束 target_column 时返回
            ParsedCheck；否则返回 None（包括跨列约束与完全无法解析的输入）。
        """
        tree = _parse_expression(expression)
        if tree is None:
            return None

        target = target_column.lower()
        choices: list[Any] = []
        lower: tuple[float, bool] | None = None  # (下界值, 是否严格)
        upper: tuple[float, bool] | None = None  # (上界值, 是否严格)
        min_length: int | None = None
        max_length: int | None = None

        for conjunct in _flatten_and(tree):
            node = _unwrap(conjunct)

            # OR：唯一确定可处理的形态是同列等值析取（col = a OR col = b）。
            if isinstance(node, exp.Or):
                values = _or_choice_values(node, target)
                if values:
                    choices.extend(v for v in values if v not in choices)
                continue

            # col IN (lit, ...)：全部为纯字面量才可确定；子查询/表达式降级。
            if isinstance(node, exp.In):
                values = _in_choice_values(node, target)
                if values:
                    choices.extend(v for v in values if v not in choices)
                continue

            # col = lit：单值枚举。
            if isinstance(node, exp.EQ):
                matched, value = _eq_choice_value(node, target)
                if matched and value not in choices:
                    choices.append(value)
                continue

            # col BETWEEN lo AND hi / length(col) BETWEEN lo AND hi（含双边界）。
            # col OP lit / lit OP col / length(col) OP lit（单边界）。
            bounds: list[_Bound] = []
            if isinstance(node, exp.Between):
                pair = _between_bounds(node, target)
                if pair is not None:
                    bounds.extend(pair)
            else:
                single = _comparison_bound(node, target)
                if single is not None:
                    bounds.append(single)

            for bound in bounds:
                if bound.kind == "range":
                    value, strict = _tighten(bound.value, strict=bound.strict, is_lower=bound.is_lower)
                    if bound.is_lower:
                        lower = _merge_bound(lower, value, strict=strict, is_lower=True)
                    else:
                        upper = _merge_bound(upper, value, strict=strict, is_lower=False)
                elif isinstance(bound.value, int):
                    length_value = _tighten_length(bound.value, strict=bound.strict, is_lower=bound.is_lower)
                    if length_value >= 0:
                        if bound.is_lower:
                            min_length = length_value if min_length is None else max(min_length, length_value)
                        else:
                            max_length = length_value if max_length is None else min(max_length, length_value)

        # 结果类型优先级与历史行为一致：choice > length_range > range。
        if choices:
            return ParsedCheck(column=target_column, kind="choice", choices=tuple(choices))
        if min_length is not None or max_length is not None:
            return ParsedCheck(
                column=target_column,
                kind="length_range",
                min_length=min_length,
                max_length=max_length,
            )
        if lower is not None or upper is not None:
            return ParsedCheck(
                column=target_column,
                kind="range",
                min_value=lower[0] if lower is not None else None,
                max_value=upper[0] if upper is not None else None,
                min_exclusive=lower[1] if lower is not None else False,
                max_exclusive=upper[1] if upper is not None else False,
            )
        return None

    @staticmethod
    def parse_all(target_column: str, expressions: list[str]) -> ParsedCheck | None:
        """依次解析多个 CHECK 表达式，返回首个可确定性解析的结果。

        Args:
            target_column: 目标列名。
            expressions: CHECK 约束 SQL 表达式列表。

        Returns:
            首个命中表达式的 ParsedCheck；全部不可解析时返回 None。
        """
        for expression in expressions:
            parsed = CheckConstraintParser.parse(target_column, expression)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def is_cross_column(expression: str, all_columns: list[str]) -> bool:
        """检测 CHECK 表达式是否引用了 all_columns 中的多个列。

        基于 AST 的精确标识符匹配，无子串误报（'price' 不会匹配
        'unit_price'）。表达式无法解析时返回 False。
        """
        tree = _parse_expression(expression)
        if tree is None:
            return False
        known = {col.lower() for col in all_columns}
        referenced = {col.name.lower() for col in tree.find_all(exp.Column) if col.name}
        return len(referenced & known) >= 2


def _parse_expression(expression: str) -> exp.Expression | None:
    """剥离可选的 CHECK 前缀并用 sqlglot（sqlite 方言）解析约束体。"""
    text = expression.strip()
    match = CheckConstraintParser._CHECK_INNER_RE.match(text)
    if match:
        text = match.group("inner").strip()
    if not text:
        return None
    try:
        # parse_one 的类型标注是宽泛的 exp.Expr（Expression 的父类）；SQLite
        # CHECK 约束体解析结果在运行时必为 Expression 子类（GTE/And/Column 等，
        # 已用 isinstance 验证），此处显式收窄以满足 mypy strict。
        return cast("exp.Expression", parse_one(text, dialect="sqlite"))
    except SqlglotError:
        return None


def _unwrap(node: exp.Expression) -> exp.Expression:
    """剥离冗余括号（Paren 节点）。"""
    while isinstance(node, exp.Paren):
        node = node.this
    return node


def _flatten_and(node: exp.Expression) -> list[exp.Expression]:
    """将 AND 链展开为合取项列表。"""
    node = _unwrap(node)
    if isinstance(node, exp.And):
        return [*_flatten_and(node.this), *_flatten_and(node.expression)]
    return [node]


def _flatten_or(node: exp.Expression) -> list[exp.Expression]:
    """将 OR 链展开为析取项列表。"""
    node = _unwrap(node)
    if isinstance(node, exp.Or):
        return [*_flatten_or(node.this), *_flatten_or(node.expression)]
    return [node]


def _column_name(node: exp.Expression) -> str | None:
    """节点为列引用时返回小写列名（忽略表限定与引号），否则返回 None。"""
    node = _unwrap(node)
    if isinstance(node, exp.Column) and node.name:
        return node.name.lower()
    return None


def _length_column(node: exp.Expression) -> str | None:
    """节点为 length(col) 调用时返回小写列名，否则返回 None。"""
    node = _unwrap(node)
    if isinstance(node, exp.Length):
        return _column_name(node.this)
    return None


def _literal_value(node: exp.Expression | None) -> tuple[bool, Any]:
    """提取纯字面量值（str/int/float，支持一元负号）。

    Returns:
        (True, value) 当节点为纯字面量；含列引用、函数调用、子查询或
        其他任何表达式时返回 (False, None) —— 明确降级，绝不硬猜。
    """
    if node is None:
        return False, None
    node = _unwrap(node)
    negative = False
    if isinstance(node, exp.Neg):
        negative = True
        node = _unwrap(node.this)
    if not isinstance(node, exp.Literal):
        return False, None
    if node.is_string:
        return (False, None) if negative else (True, node.this)
    try:
        value: int | float = float(node.this) if ("." in node.this or "e" in node.this.lower()) else int(node.this)
    except ValueError:
        return False, None
    return True, -value if negative else value


def _eq_choice_value(node: exp.EQ, target: str) -> tuple[bool, Any]:
    """从 col = lit（任一方向）提取目标列的单值枚举。"""
    left = _unwrap(node.this)
    right = _unwrap(node.expression)
    if _column_name(left) == target:
        return _literal_value(right)
    if _column_name(right) == target:
        return _literal_value(left)
    return False, None


def _or_choice_values(node: exp.Or, target: str) -> list[Any] | None:
    """同列等值析取（col = a OR col = b）合并为取值列表。

    任一析取项不是目标列的等值条件时返回 None（OR 语义无法确定合并）。
    """
    values: list[Any] = []
    for disjunct in _flatten_or(node):
        item = _unwrap(disjunct)
        if not isinstance(item, exp.EQ):
            return None
        matched, value = _eq_choice_value(item, target)
        if not matched:
            return None
        values.append(value)
    return values or None


def _in_choice_values(node: exp.In, target: str) -> list[Any] | None:
    """col IN (lit, ...) 提取字面量取值列表；含子查询/非字面量时返回 None。"""
    if _column_name(node.this) != target:
        return None
    values: list[Any] = []
    for item in node.expressions:
        matched, value = _literal_value(item)
        if not matched:
            return None
        values.append(value)
    return values or None


def _between_bounds(node: exp.Between, target: str) -> tuple[_Bound, _Bound] | None:
    """col BETWEEN lo AND hi / length(col) BETWEEN lo AND hi 提取双边界（含）。

    range 要求数值字面量；length 要求非负整数字面量；其余形态返回 None。
    """
    subject = _unwrap(node.this)
    if _column_name(subject) == target:
        kind: Literal["range", "length"] = "range"
    elif _length_column(subject) == target:
        kind = "length"
    else:
        return None
    ok_lo, lo = _literal_value(node.args.get("low"))
    ok_hi, hi = _literal_value(node.args.get("high"))
    if not (ok_lo and ok_hi):
        return None
    if kind == "range":
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
            return None
    elif not (isinstance(lo, int) and isinstance(hi, int)) or lo < 0 or hi < 0:
        return None
    return (
        _Bound(kind=kind, is_lower=True, value=lo, strict=False),
        _Bound(kind=kind, is_lower=False, value=hi, strict=False),
    )


def _comparison_bound(node: exp.Expression, target: str) -> _Bound | None:
    """从 col OP lit / lit OP col / length(col) OP lit 提取单边界。

    字面量侧为列引用（跨列比较）或任何非纯字面量时返回 None。
    """
    if not isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE)):
        return None
    left = _unwrap(node.this)
    right = _unwrap(node.expression)
    strict = isinstance(node, (exp.GT, exp.LT))
    is_lower_op = isinstance(node, (exp.GT, exp.GTE))
    # 方向一：col OP lit（列在左，方向原样）。
    bound = _side_bound(left, right, target, is_lower=is_lower_op, strict=strict)
    if bound is not None:
        return bound
    # 方向二：lit OP col（列在右，比较方向翻转）。
    return _side_bound(right, left, target, is_lower=not is_lower_op, strict=strict)


def _side_bound(
    col_side: exp.Expression,
    lit_side: exp.Expression,
    target: str,
    *,
    is_lower: bool,
    strict: bool,
) -> _Bound | None:
    """col_side 为目标列（或 length(目标列)）且 lit_side 为纯字面量时生成边界。"""
    if _column_name(col_side) == target:
        matched, value = _literal_value(lit_side)
        if matched and isinstance(value, (int, float)):
            return _Bound(kind="range", is_lower=is_lower, value=value, strict=strict)
        return None
    if _length_column(col_side) == target:
        matched, value = _literal_value(lit_side)
        if matched and isinstance(value, int) and value >= 0:
            return _Bound(kind="length", is_lower=is_lower, value=value, strict=strict)
    return None


def _tighten(value: int | float, *, strict: bool, is_lower: bool) -> tuple[int | float, bool]:
    """严格不等式收一：整数字面量 ±1 转为含边界；浮点保持原值并记录严格标记。"""
    if strict and isinstance(value, int):
        return (value + 1 if is_lower else value - 1), False
    return value, strict


def _tighten_length(value: int, *, strict: bool, is_lower: bool) -> int:
    """长度边界收一：长度恒为整数语义，严格不等式直接 ±1。"""
    if strict:
        return value + 1 if is_lower else value - 1
    return value


def _merge_bound(
    current: tuple[float, bool] | None,
    value: int | float,
    *,
    strict: bool,
    is_lower: bool,
) -> tuple[float, bool]:
    """按 AND 语义合并同侧边界：更紧者胜（下界取大、上界取小，等值时严格者胜）。"""
    if current is None:
        return value, strict
    current_value, current_strict = current
    if (is_lower and value > current_value) or (not is_lower and value < current_value):
        return value, strict
    if value == current_value and strict and not current_strict:
        return value, True
    return current
