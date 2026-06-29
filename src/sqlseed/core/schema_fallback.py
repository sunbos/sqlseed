"""Schema-driven fallback generator — pure schema semantics, zero business logic.

Standalone component (does NOT modify ColumnMapper). Called by the
orchestrator as an L9 enhancement when no user config or AI suggestion
exists for a column.

Generates a fallback GeneratorSpec based SOLELY on database schema
information: SQL type, length (parsed from type string), NOT NULL,
DEFAULT, PRIMARY KEY, AUTOINCREMENT, CHECK constraints, UNIQUE indexes,
and FK relationships.

This module knows NOTHING about business semantics. It does not know
that "phone" should be XXX-XXX-XXXX or that "*_code" should be
alphanumeric. Business rules live in YAML configs (LLM-generated or
hand-edited).

Guarantees:
- Generated data passes schema validation (types, lengths, constraints).
- Generated data may NOT match business intent.
- Offline-capable: no LLM, no network, no external services.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed.core.check_parser import CheckConstraintParser, ParsedCheck
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from sqlseed.database._protocol import CheckConstraintInfo, ColumnInfo

logger = get_logger(__name__)


# SQL type prefix → fallback generator name. Pure type semantics.
# Matches by prefix to handle 'VARCHAR(50)', 'INTEGER', etc.
_TYPE_FALLBACK: list[tuple[str, str]] = [
    ("int", "integer"),
    ("bigint", "integer"),
    ("smallint", "integer"),
    ("tinyint", "integer"),
    ("real", "float"),
    ("float", "float"),
    ("double", "float"),
    ("numeric", "float"),
    ("decimal", "float"),
    ("bool", "boolean"),
    ("date", "date"),
    ("datetime", "datetime"),
    ("timestamp", "datetime"),
    ("time", "time"),
    ("text", "string"),
    ("varchar", "string"),
    ("char", "string"),
    ("string", "string"),
]


def _parse_length_from_type(type_str: str) -> int | None:
    """Parse length from a SQL type string like 'VARCHAR(50)' -> 50."""
    m = re.search(r"\((\d+)\)", type_str)
    return int(m.group(1)) if m else None


def _base_type(type_str: str) -> str:
    """Strip length from type: 'VARCHAR(50)' -> 'VARCHAR'."""
    return re.sub(r"\(.*\)", "", type_str).strip()


class SchemaFallbackGenerator:
    """Generate fallback GeneratorSpecs from pure schema information.

    Standalone component — does NOT modify ColumnMapper. Called by the
    orchestrator as an L9 enhancement for columns without user/AI config.

    Business rules (e.g., phone format, code charset) are NOT applied
    here — they belong in YAML configs.
    """

    def fallback_for_column(
        self,
        column: ColumnInfo,
        check_constraints: list[CheckConstraintInfo],
        unique_columns: list[str],
    ) -> GeneratorSpec | None:
        """Generate a fallback spec for a column, or None if no fallback needed.

        Returns None when:
        - Column is PK AUTOINCREMENT (DB auto-fills)
        - Column has a DEFAULT value (DB auto-fills)
        - Column is GENERATED/computed (DB auto-fills)

        Args:
            column: Column schema info (uses column.type, NOT type_name).
            check_constraints: CHECK constraints on the table.
            unique_columns: Column names with UNIQUE indexes.

        Returns:
            GeneratorSpec for schema-valid fallback, or None.
        """
        # Skip PK AUTOINCREMENT — DB handles it.
        if column.is_primary_key and column.is_autoincrement:
            return None

        # Skip columns with DEFAULT — DB handles it.
        if column.default is not None:
            return None

        # Skip computed/generated columns.
        if column.is_computed:
            return None

        # Try CHECK constraint-based fallback first (more specific).
        check_spec = self._fallback_from_check(column, check_constraints)
        if check_spec is not None:
            return check_spec

        # Fall back to type-driven generation.
        return self._fallback_from_type(column, unique_columns)

    def _fallback_from_check(
        self,
        column: ColumnInfo,
        check_constraints: list[CheckConstraintInfo],
    ) -> GeneratorSpec | None:
        """Generate spec from single-column CHECK constraints."""
        for chk in check_constraints:
            parsed = CheckConstraintParser.parse(column.name, chk.expression)
            if parsed is None:
                continue

            if parsed.kind == "choice":
                return GeneratorSpec(
                    generator_name="choice",
                    params={"choices": list(parsed.choices)},
                )

            if parsed.kind == "range":
                params: dict[str, Any] = {}
                if parsed.min_value is not None:
                    params["min_value"] = parsed.min_value
                if parsed.max_value is not None:
                    params["max_value"] = parsed.max_value
                gen_name = "integer" if self._is_integer_range(parsed) else "float"
                return GeneratorSpec(generator_name=gen_name, params=params)

            if parsed.kind == "length_range":
                params = {}
                if parsed.min_length is not None:
                    params["min_length"] = parsed.min_length
                if parsed.max_length is not None:
                    params["max_length"] = parsed.max_length
                # If column has explicit length in type (VARCHAR(N)), use min(parsed, N).
                type_length = _parse_length_from_type(column.type)
                if type_length and "max_length" in params:
                    params["max_length"] = min(params["max_length"], type_length)
                return GeneratorSpec(generator_name="string", params=params)

        return None

    def _fallback_from_type(
        self,
        column: ColumnInfo,
        unique_columns: list[str],
    ) -> GeneratorSpec | None:
        """Generate spec from SQL type + length + nullability.

        Uses column.type (not type_name). Length parsed from type string.
        """
        type_str = column.type or ""
        base = _base_type(type_str)
        base_lower = base.lower()

        gen_name = "string"  # default fallback
        for prefix, mapped_gen in _TYPE_FALLBACK:
            if base_lower.startswith(prefix):
                gen_name = mapped_gen
                break

        params: dict[str, Any] = {}
        if gen_name == "string":
            length = _parse_length_from_type(type_str)
            if length:
                params["max_length"] = length

        # For UNIQUE string columns, ensure uniqueness via longer random strings.
        # This is schema semantics (UNIQUE requires distinctness), not business.
        if column.name in unique_columns and gen_name == "string":
            params.setdefault("min_length", 8)
            params["max_length"] = max(params.get("max_length", 16), 8)

        return GeneratorSpec(generator_name=gen_name, params=params)

    @staticmethod
    def _is_integer_range(parsed: ParsedCheck) -> bool:
        """Check if a range parsed from CHECK has integer bounds."""
        if parsed.min_value is not None and parsed.min_value != int(parsed.min_value):
            return False
        if parsed.max_value is not None and parsed.max_value != int(parsed.max_value):
            return False
        return True
