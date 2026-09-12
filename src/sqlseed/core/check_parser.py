"""基于 sqlglot AST 的单列 CHECK 约束解析器。

本模块读取数据库 schema 语义（CHECK 约束），仅提取"能 100% 确定转换为生成参数"
的单列字面量约束，翻译成生成器提示。无法确定映射的形态一律明确降级（返回 None），
交由上层 AI/人工 YAML 配置处理，绝不硬猜：

- 跨列运算/比较（如 discount <= subtotal、price * quantity <= 10000）
- OR 连接的非等值条件（如 age >= 18 OR age IS NULL）；同列可空精确长度保护除外
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

_ASCII_CASE_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


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


@dataclass
class _CheckConstraints:
    """Accumulate conjunctive choices and bounds for one target column."""

    choices: list[Any] | None = None
    lower: tuple[float, bool] | None = None
    upper: tuple[float, bool] | None = None
    min_length: int | None = None
    max_length: int | None = None

    def add_bound(self, bound: _Bound) -> None:
        """Merge one numeric or integer-length bound without SQL coercion."""
        if bound.kind == "range":
            if bound.is_lower:
                self.lower = _merge_bound(self.lower, bound.value, strict=bound.strict, is_lower=True)
            else:
                self.upper = _merge_bound(self.upper, bound.value, strict=bound.strict, is_lower=False)
        elif (
            isinstance(bound.value, int)
            and (length_value := _tighten_length(bound.value, strict=bound.strict, is_lower=bound.is_lower)) >= 0
        ):
            if bound.is_lower:
                self.min_length = length_value if self.min_length is None else max(self.min_length, length_value)
            else:
                self.max_length = length_value if self.max_length is None else min(self.max_length, length_value)

    def result(self, target_column: str) -> ParsedCheck | None:
        """Preserve the result priority: choice, length range, then numeric range."""
        if self.choices is not None:
            choices = [
                value
                for value in self.choices
                if _choice_in_bounds(value, self.lower, self.upper, self.min_length, self.max_length)
            ]
            return ParsedCheck(column=target_column, kind="choice", choices=tuple(choices))
        if self.min_length is not None or self.max_length is not None:
            return ParsedCheck(
                column=target_column,
                kind="length_range",
                min_length=self.min_length,
                max_length=self.max_length,
            )
        if self.lower is not None or self.upper is not None:
            return ParsedCheck(
                column=target_column,
                kind="range",
                min_value=self.lower[0] if self.lower is not None else None,
                max_value=self.upper[0] if self.upper is not None else None,
                min_exclusive=self.lower[1] if self.lower is not None else False,
                max_exclusive=self.upper[1] if self.upper is not None else False,
            )
        return None


class CheckConstraintParser:
    """将单列 CHECK 约束解析为生成器提示。

    约束体解析完全基于 sqlglot AST（不使用正则）；仅保留 _CHECK_INNER_RE 一个
    正则用于剥离可选的 CONSTRAINT name CHECK(...) / CHECK(...) 前缀。
    所有方法均为静态方法，解析器无状态、线程安全。

    AND 连接的同列双边界会完整合并（如 age>=18 AND age<=120 → min=18, max=120）；
    多列 CHECK（如 price>=0 AND stock>=0）只提取目标列的条件，其余合取项跳过。
    LENGTH(col)=N 提取精确长度；同列 col IS NULL OR LENGTH(col)=N 保留该非空值约束，
    不改变列的可空性。其他非等值 OR 不据此扩展解析范围。
    跨列引用与其他不可确定映射的形态明确降级，返回 None。
    枚举涉及未知 affinity/collation 且没有 Python 精确交集时保留原候选，
    不据此断定 SQL 无解；这些候选仍须由数据库 CHECK 验证。
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
        if (tree := _parse_expression(expression)) is None:
            return None

        target = target_column.translate(_ASCII_CASE_FOLD)
        constraints = _CheckConstraints()
        for conjunct in _flatten_and(tree):
            node = _unwrap_nullable_length_equality(_unwrap(conjunct), target)
            if (values := _node_choice_values(node, target)) is not None:
                constraints.choices = _intersect_choices(constraints.choices, values)
                continue
            for bound in _node_bounds(node, target):
                constraints.add_bound(bound)
        return constraints.result(target_column)

    @staticmethod
    def parse_all(target_column: str, expressions: list[str]) -> ParsedCheck | None:
        """按 AND 语义合并多个 CHECK 表达式的可确定性约束。

        Args:
            target_column: 目标列名。
            expressions: CHECK 约束 SQL 表达式列表。

        Returns:
            合取后的 ParsedCheck；全部不可解析时返回 None。
        """
        if not (trees := [tree for expression in expressions if (tree := _parse_expression(expression)) is not None]):
            return None
        combined = trees[0]
        for tree in trees[1:]:
            combined = exp.And(this=exp.Paren(this=combined), expression=exp.Paren(this=tree))
        return CheckConstraintParser.parse(target_column, combined.sql(dialect="sqlite"))

    @staticmethod
    def is_cross_column(expression: str, all_columns: list[str]) -> bool:
        """检测 CHECK 表达式是否引用了 all_columns 中的多个列。

        基于 AST 的精确标识符匹配，无子串误报（'price' 不会匹配
        'unit_price'）。表达式无法解析时返回 False。
        """
        if (tree := _parse_expression(expression)) is None:
            return False
        known = {col.translate(_ASCII_CASE_FOLD) for col in all_columns}
        referenced = {col.name.translate(_ASCII_CASE_FOLD) for col in tree.find_all(exp.Column) if col.name}
        return len(referenced & known) >= 2


def _node_choice_values(node: exp.Expression, target: str) -> list[Any] | None:
    """Recognize only literal equality, IN, and same-column equality OR choices."""
    if isinstance(node, exp.Or):
        return _or_choice_values(node, target)
    if isinstance(node, exp.In):
        return _in_choice_values(node, target)
    if isinstance(node, exp.EQ):
        matched, value = _eq_choice_value(node, target)
        if matched:
            return [value]
    return None


def _node_bounds(node: exp.Expression, target: str) -> list[_Bound]:
    """Extract exact lengths, BETWEEN pairs, or a single comparison bound."""
    if isinstance(node, exp.EQ):
        return list(_length_equality_bounds(node, target) or ())
    if isinstance(node, exp.Between):
        return list(_between_bounds(node, target) or ())
    single = _comparison_bound(node, target)
    return [single] if single is not None else []


def _parse_expression(expression: str) -> exp.Expression | None:
    """剥离可选的 CHECK 前缀并用 sqlglot（sqlite 方言）解析约束体。"""
    text = expression.strip()
    if match := CheckConstraintParser._CHECK_INNER_RE.match(text):
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
    """返回仅折叠 ASCII 大小写的列名；SQLite 的非 ASCII 标识符保持独立。"""
    node = _unwrap(node)
    if isinstance(node, exp.Column) and node.name:
        return node.name.translate(_ASCII_CASE_FOLD)
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


def _length_equality_bounds(node: exp.Expression, target: str) -> tuple[_Bound, _Bound] | None:
    """Match length(target) = nonnegative integer in either direction."""
    if not isinstance(node, exp.EQ):
        return None
    for subject, literal in ((node.this, node.expression), (node.expression, node.this)):
        if _length_column(subject) != target:
            continue
        matched, value = _literal_value(literal)
        if matched and isinstance(value, int) and value >= 0:
            return _Bound("length", True, value, False), _Bound("length", False, value, False)
    return None


def _unwrap_nullable_length_equality(node: exp.Expression, target: str) -> exp.Expression:
    """Extract only target IS NULL OR length(target) = N, preserving SQL NULL.

    NULL remains allowed independently of the non-NULL value's length. Other
    guards, additional OR branches and predicates retain conservative fallback.
    """
    if isinstance(node, exp.Or):
        for guard_node, predicate_node in ((node.this, node.expression), (node.expression, node.this)):
            guard, predicate = _unwrap(guard_node), _unwrap(predicate_node)
            if (
                isinstance(guard, exp.Is)
                and _column_name(guard.this) == target
                and isinstance(_unwrap(guard.expression), exp.Null)
                and _length_equality_bounds(predicate, target) is not None
            ):
                return predicate
    return node


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
    if (bound := _side_bound(left, right, target, is_lower=is_lower_op, strict=strict)) is not None:
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


def _intersect_choices(current: list[Any] | None, values: list[Any]) -> list[Any]:
    """Intersect known equal literals; defer ambiguous SQL equality to the DB.

    Without column affinity/collation, Python inequality cannot establish
    that string or mixed literal domains are disjoint. Preserve the previous
    candidates in that case, without claiming they satisfy every CHECK.
    """
    if current is None:
        return list(dict.fromkeys(values))
    intersection = [v for v in current if v in values]
    if not intersection and any(isinstance(v, str) for v in (*current, *values)):
        return current
    return intersection


def _choice_in_bounds(
    value: Any,
    lower: tuple[float, bool] | None,
    upper: tuple[float, bool] | None,
    min_length: int | None,
    max_length: int | None,
) -> bool:
    """Apply known literal bounds without guessing SQL coercion of strings."""
    if isinstance(value, int | float):
        if lower is not None and (value < lower[0] or (lower[1] and value == lower[0])):
            return False
        if upper is not None and (value > upper[0] or (upper[1] and value == upper[0])):
            return False
    if isinstance(value, str):
        if min_length is not None and len(value) < min_length:
            return False
        if max_length is not None and len(value) > max_length:
            return False
    return True


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
