"""Parse single-column CHECK constraints into generator hints.

This module reads database schema semantics (CHECK constraints) and
translates them into generator parameters. It handles ONLY single-column
constraints; cross-column constraints (e.g., sale_price >= cost_price)
return None and require user-provided YAML configuration.

This is schema semantics, NOT business logic: parsing CHECK(x >= 0) into
min_value=0 is reading the schema declaration, not understanding business
intent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedCheck:
    """Result of parsing a CHECK constraint for a specific column.

    Attributes:
        column: The column name this check applies to.
        kind: Generator hint kind: "choice", "range", "length_range".
        choices: For "choice" kind, the allowed values tuple.
        min_value: For "range" kind, the minimum value (inclusive).
        max_value: For "range" kind, the maximum value (inclusive).
        min_length: For "length_range" kind, the minimum length (inclusive).
        max_length: For "length_range" kind, the maximum length (inclusive).
    """
    column: str
    kind: str
    choices: tuple[Any, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None


class CheckConstraintParser:
    """Parse single-column CHECK constraints into generator hints.

    All methods are static. The parser is stateless and thread-safe.

    Cross-column constraints (referencing multiple columns) are not parsed
    and return None — they require user-provided YAML configuration.
    """

    _IN_PATTERN = re.compile(
        r"(?P<col>\w+)\s+IN\s*\((?P<values>[^)]+)\)",
        re.IGNORECASE,
    )
    _BETWEEN_PATTERN = re.compile(
        r"(?P<col>\w+)\s+BETWEEN\s+(?P<low>-?\d+(?:\.\d+)?)\s+AND\s+(?P<high>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    _LENGTH_BETWEEN_PATTERN = re.compile(
        r"length\s*\(\s*(?P<col>\w+)\s*\)\s+BETWEEN\s+(?P<low>\d+)\s+AND\s+(?P<high>\d+)",
        re.IGNORECASE,
    )
    _LENGTH_GE_PATTERN = re.compile(
        r"length\s*\(\s*(?P<col>\w+)\s*\)\s*>=\s*(?P<val>\d+)",
        re.IGNORECASE,
    )
    _LENGTH_LE_PATTERN = re.compile(
        r"length\s*\(\s*(?P<col>\w+)\s*\)\s*<=\s*(?P<val>\d+)",
        re.IGNORECASE,
    )
    _COL_GE_PATTERN = re.compile(
        r"(?P<col>\w+)\s*>=\s*(?P<val>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    _COL_LE_PATTERN = re.compile(
        r"(?P<col>\w+)\s*<=\s*(?P<val>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    @staticmethod
    def parse(target_column: str, expression: str) -> ParsedCheck | None:
        """Parse a CHECK expression for the given target column.

        Args:
            target_column: The column to extract constraints for.
            expression: The CHECK constraint SQL expression.

        Returns:
            ParsedCheck if the expression constrains target_column with a
            parseable single-column pattern; None otherwise (including
            cross-column constraints).
        """
        target_lower = target_column.lower()
        expr = expression.strip()

        # IN clause: col IN ('A', 'B', 'C') or col IN (1, 2, 3)
        m = CheckConstraintParser._IN_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            values = CheckConstraintParser._parse_value_list(m.group("values"))
            if values:
                return ParsedCheck(
                    column=target_column,
                    kind="choice",
                    choices=tuple(values),
                )

        # length BETWEEN: length(col) BETWEEN 3 AND 50
        m = CheckConstraintParser._LENGTH_BETWEEN_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="length_range",
                min_length=int(m.group("low")),
                max_length=int(m.group("high")),
            )

        # length >= N
        m = CheckConstraintParser._LENGTH_GE_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="length_range",
                min_length=int(m.group("val")),
                max_length=None,
            )

        # length <= N
        m = CheckConstraintParser._LENGTH_LE_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="length_range",
                min_length=None,
                max_length=int(m.group("val")),
            )

        # BETWEEN: col BETWEEN 1 AND 100
        m = CheckConstraintParser._BETWEEN_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="range",
                min_value=float(m.group("low")),
                max_value=float(m.group("high")),
            )

        # col >= N
        m = CheckConstraintParser._COL_GE_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="range",
                min_value=float(m.group("val")),
                max_value=None,
            )

        # col <= N
        m = CheckConstraintParser._COL_LE_PATTERN.search(expr)
        if m and m.group("col").lower() == target_lower:
            return ParsedCheck(
                column=target_column,
                kind="range",
                min_value=None,
                max_value=float(m.group("val")),
            )

        return None

    @staticmethod
    def _parse_value_list(values_str: str) -> list[Any]:
        """Parse a comma-separated value list from an IN clause."""
        items: list[Any] = []
        for raw in values_str.split(","):
            raw = raw.strip()
            if not raw:
                continue
            if (raw.startswith("'") and raw.endswith("'")) or (
                raw.startswith('"') and raw.endswith('"')
            ):
                items.append(raw[1:-1])
            else:
                try:
                    items.append(int(raw))
                except ValueError:
                    try:
                        items.append(float(raw))
                    except ValueError:
                        items.append(raw)
        return items

    @staticmethod
    def is_cross_column(expression: str, all_columns: list[str]) -> bool:
        """Detect if a CHECK expression references multiple target columns.

        Uses word boundary matching to avoid substring false positives
        (e.g., 'price' should NOT match inside 'unit_price').
        """
        referenced = set()
        for col in all_columns:
            # Word boundary match: \bprice\b won't match 'unit_price'
            if re.search(rf"\b{re.escape(col)}\b", expression, re.IGNORECASE):
                referenced.add(col.lower())
        return len(referenced) >= 2
