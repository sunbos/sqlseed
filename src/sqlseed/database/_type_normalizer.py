"""Type normalization layer.

Normalizes type names from different databases to sqlseed internal unified types,
protecting the 74 exact match rules in ``mapper.py`` from becoming invalid.

Normalization rules:
- Extract the base type name and parameters (length, precision)
- Map to sqlseed internal types (uppercase form) by dialect
- Preserve parameter information for generators to use

Examples:
    "character varying(255)" -> NormalizedType(base="VARCHAR", params=(255,))
    "numeric(10,2)"          -> NormalizedType(base="NUMERIC", params=(10, 2))
    "integer"                -> NormalizedType(base="INTEGER", params=())
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Regex to extract the base type name and parameters
# "character varying(255)" -> group(1)="character varying", group(2)="255"
# "numeric(10,2)"          -> group(1)="numeric", group(2)="10,2"
# "integer"                -> group(1)="integer", group(2)=None
_TYPE_PARAMS_RE = re.compile(r"^([^(]+?)\s*(?:\(([^)]+)\))?\s*$")


@dataclass(frozen=True)
class NormalizedType:
    """Normalized type information.

    Attributes:
        base: Normalized base type name (uppercase), e.g. "VARCHAR", "INTEGER"
        params: Type parameter tuple, e.g. (255,) or (10, 2)
        raw: Original type string
    """

    base: str
    params: tuple[int, ...]
    raw: str

    @property
    def display(self) -> str:
        """Display form: "VARCHAR(255)" or "INTEGER"."""
        if self.params:
            return f"{self.base}({','.join(str(p) for p in self.params)})"
        return self.base


# PostgreSQL type mapping table
_PG_TYPE_MAP: dict[str, str] = {
    "serial": "INTEGER",
    "bigserial": "INTEGER",
    "smallserial": "INTEGER",
    "character varying": "VARCHAR",
    "character": "CHAR",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMPTZ",
    "double precision": "FLOAT",
    "boolean": "BOOLEAN",
    "smallint": "INTEGER",
    "bigint": "INTEGER",
    "integer": "INTEGER",
    "real": "FLOAT",
    "bytea": "BLOB",
    "jsonb": "JSON",
    "json": "JSON",
    "uuid": "UUID",
    "text": "TEXT",
    "numeric": "NUMERIC",
    "decimal": "NUMERIC",
    "date": "DATE",
    "time without time zone": "TIME",
    "time with time zone": "TIMETZ",
    "interval": "INTERVAL",
    "money": "DECIMAL",
    "inet": "TEXT",
    "cidr": "TEXT",
    "macaddr": "TEXT",
    "bit varying": "BLOB",
    "bit": "BLOB",
}


class TypeNormalizer:
    """Normalizes type names from different databases so that mapper.py rules keep working.

    Usage:
        normalizer = TypeNormalizer()
        result = normalizer.normalize("character varying(255)", "postgresql")
        # result.base == "VARCHAR"
        # result.params == (255,)
        # result.display == "VARCHAR(255)"
    """

    def normalize(self, raw_type: str, dialect_name: str) -> NormalizedType:
        """Normalize a type name.

        Args:
            raw_type: Original type string returned by the database
            dialect_name: Dialect name ("sqlite", "postgresql")

        Returns:
            NormalizedType: Normalized type information
        """
        if not raw_type or not raw_type.strip():
            return NormalizedType(base="TEXT", params=(), raw=raw_type)

        match = _TYPE_PARAMS_RE.match(raw_type.strip())
        if not match:
            return NormalizedType(base=raw_type.upper(), params=(), raw=raw_type)

        base_raw = match.group(1).strip().lower()
        params_str = match.group(2)

        # Map the base type by dialect
        base = self._map_base_type(base_raw, dialect_name)

        # Parse parameters (length, precision)
        params = self._parse_params(params_str)

        return NormalizedType(base=base, params=params, raw=raw_type)

    def _map_base_type(self, base_raw: str, dialect_name: str) -> str:
        """Map the base type name to sqlseed internal type by dialect."""
        if dialect_name == "postgresql":
            return _PG_TYPE_MAP.get(base_raw, base_raw.upper())
        # SQLite types are already in normalized uppercase form
        return base_raw.upper()

    def _parse_params(self, params_str: str | None) -> tuple[int, ...]:
        """Parse a type parameter string into a tuple of integers.

        "255"    -> (255,)
        "10,2"   -> (10, 2)
        None     -> ()
        "abc"    -> ()  # non-numeric parameters are ignored
        """
        if not params_str:
            return ()

        params: list[int] = []
        for raw_part in params_str.split(","):
            part = raw_part.strip()
            if not part:
                continue
            try:
                params.append(int(part))
            except ValueError:
                # Non-numeric parameters (e.g. ENUM values) are ignored, only numbers are kept
                continue
        return tuple(params)


__all__ = ["NormalizedType", "TypeNormalizer"]
