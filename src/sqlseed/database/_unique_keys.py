"""Read complete UNIQUE keys with the equality rules used by their indexes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlseed._utils.sql_safe import quote_identifier, validate_table_name

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter


@dataclass(frozen=True)
class UniqueKey:
    """Columns and optional per-index collations for a complete UNIQUE key."""

    columns: tuple[str, ...]
    collations: tuple[str, ...] = ()

    def predicate(self, *, placeholder: str) -> str:
        """Build bound equality tests using the index's explicit collations."""
        terms = []
        for index, column in enumerate(self.columns):
            expression = quote_identifier(column)
            if self.collations:
                expression += f" COLLATE {quote_identifier(self.collations[index])}"
            terms.append(f"{expression} = {placeholder}")
        return " AND ".join(terms)


def get_unique_keys(db: DatabaseAdapter, *, table_name: str) -> list[UniqueKey]:
    """Read ordinary complete UNIQUE keys, retaining SQLite index collations.

    Partial and expression indexes remain database-enforced constraints; a
    subset of their columns must not become an unconditional UNIQUE key.
    """
    validate_table_name(table_name)
    if getattr(getattr(db, "dialect", None), "name", "") == "sqlite":
        return _sqlite_unique_keys(db, table_name)
    indexes = [*db.get_index_info(table_name), *db.get_unique_constraints(table_name)]
    return list(
        dict.fromkeys(
            UniqueKey(index.columns)
            for index in indexes
            if index.unique and not index.is_partial and index.columns and all(index.columns)
        )
    )


def _sqlite_unique_keys(db: DatabaseAdapter, table_name: str) -> list[UniqueKey]:
    cursor = db.execute(f"PRAGMA index_list({quote_identifier(table_name)})")
    try:
        names = sorted(row[1] for row in cursor.fetchall() if row[2] and not row[4])
    finally:
        cursor.close()
    keys = []
    for name in names:
        cursor = db.execute(f"PRAGMA index_xinfo({quote_identifier(name)})")
        try:
            parts = [row for row in cursor.fetchall() if row[5]]
        finally:
            cursor.close()
        if parts and all(part[2] is not None for part in parts):
            keys.append(UniqueKey(tuple(part[2] for part in parts), tuple(part[4] for part in parts)))
    return list(dict.fromkeys(keys))
