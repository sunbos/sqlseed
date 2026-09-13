"""Assign deferred self references using complete identities and UNIQUE probes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database._unique_keys import UniqueKey, get_unique_keys

if TYPE_CHECKING:
    import random
    from types import ModuleType

    from sqlseed.database._protocol import DatabaseAdapter, ForeignKeyInfo

_MAX_PARENT_ATTEMPTS = 100


class SelfReferenceUpdater:
    """Update one deferred FK while retaining valid NULL rows when no parent fits.

    Only already-persisted key columns are read. Candidate UNIQUE keys are
    checked against the database, preserving its affinity and collation rules.
    Each UPDATE retains the adapter's existing commit/error semantics.
    """

    def __init__(
        self,
        db: DatabaseAdapter,
        table_name: str,
        primary_keys: list[str],
        fk: ForeignKeyInfo,
        condition: tuple[str | None, list[str | int]],
        placeholder: str,
        rng: random.Random | ModuleType,
    ) -> None:
        self._db = db
        self._table = quote_identifier(table_name)
        self._primary_keys = primary_keys
        self._fk = fk
        self._condition_column, self._condition_values = condition
        self._placeholder = placeholder
        self._rng = rng
        changed = {fk.column}
        if self._condition_column and self._condition_values:
            changed.add(self._condition_column)
        self._unique_keys = [
            key for key in get_unique_keys(db, table_name=table_name) if changed.intersection(key.columns)
        ]
        if changed.intersection(primary_keys) and not any(
            key.columns == tuple(primary_keys) for key in self._unique_keys
        ):
            self._unique_keys.append(UniqueKey(tuple(primary_keys)))
        self._known_keys: dict[UniqueKey, set[tuple[Any, ...]]] = {key: set() for key in self._unique_keys}

    @staticmethod
    def _cacheable(values: tuple[Any, ...]) -> bool:
        try:
            hash(values)
        except TypeError:
            # Some DBAPI values, such as PostgreSQL JSONB dicts, need SQL
            # equality even when their serialized database keys are unique.
            return False
        return True

    def _remember_keys(self, row: dict[str, Any]) -> None:
        for key, seen in self._known_keys.items():
            values = tuple(row[column] for column in key.columns)
            if all(value is not None for value in values) and self._cacheable(values):
                seen.add(values)

    def _read_rows(self) -> list[dict[str, Any]]:
        columns = set(self._primary_keys) | {self._fk.ref_column, self._fk.column}
        columns.update(column for key in self._unique_keys for column in key.columns)
        if self._condition_column:
            columns.add(self._condition_column)
        selected = sorted(columns)
        order = dict.fromkeys([*self._primary_keys, self._fk.ref_column])
        sql = (
            f"SELECT {', '.join(quote_identifier(column) for column in selected)} FROM {self._table} "
            f"ORDER BY {', '.join(quote_identifier(column) for column in order)}"
        )
        cursor = self._db.execute(sql)
        try:
            return [dict(zip(selected, row, strict=True)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _conflicts(self, row: dict[str, Any], changes: dict[str, Any]) -> bool:
        for key in self._unique_keys:
            values = tuple(changes.get(column, row[column]) for column in key.columns)
            # SQLite/PostgreSQL ordinary UNIQUE permits repeated NULL tuples.
            # An unchanged key already belongs to this row and remains valid.
            if any(value is None for value in values) or values == tuple(row[column] for column in key.columns):
                continue
            cacheable = self._cacheable(values)
            if cacheable and values in self._known_keys[key]:
                return True
            predicate = key.predicate(placeholder=self._placeholder)
            cursor = self._db.execute(f"SELECT 1 FROM {self._table} WHERE {predicate} LIMIT 1", values)
            try:
                if cursor.fetchone() is not None:
                    if cacheable:
                        self._known_keys[key].add(values)
                    return True
            finally:
                cursor.close()
        return False

    def _choose_changes(self, row: dict[str, Any], parents: list[Any]) -> dict[str, Any]:
        # A sparse or exhausted UNIQUE pool must not turn the optional
        # hierarchy pass into a quadratic scan. Retaining NULL is valid.
        # Sample across the pool: scanning a consecutive window would bias
        # old, densely occupied prefixes and leave avoidable NULL roots.
        candidates = (
            self._rng.sample(range(len(parents)), min(len(parents), _MAX_PARENT_ATTEMPTS))
            if self._unique_keys
            else [self._rng.randrange(len(parents))]
        )
        for index in candidates:
            parent = parents[index]
            changes = {self._fk.column: parent}
            choices = self._condition_values
            if self._condition_column and choices:
                condition_start = self._rng.randrange(len(choices))
                for condition_offset in range(len(choices)):
                    changes[self._condition_column] = choices[(condition_start + condition_offset) % len(choices)]
                    if not self._conflicts(row, changes):
                        return changes
            elif not self._conflicts(row, changes):
                return changes
        return {}

    def _identity(self, row: dict[str, Any]) -> dict[str, Any]:
        identity = {column: row[column] for column in self._primary_keys}
        if any(value is None for value in identity.values()):
            # SQLite permits duplicate PRIMARY KEY tuples containing NULL.
            # A non-NULL referenced UNIQUE value disambiguates such rows.
            if (reference := row[self._fk.ref_column]) is None:
                return {}
            identity[self._fk.ref_column] = reference
        return identity

    def apply(self) -> tuple[int, int]:
        """Return updated/total counts after linking only to preceding rows."""
        rows = self._read_rows()
        updated = 0
        parents: list[Any] = []
        for index, row in enumerate(rows):
            if index and (parent := rows[index - 1][self._fk.ref_column]) is not None:
                parents.append(parent)
            if not parents or self._rng.random() > 0.7 or row[self._fk.column] is not None:
                continue
            identity = self._identity(row)
            if not identity or not (changes := self._choose_changes(row, parents)):
                continue
            setters = ", ".join(f"{quote_identifier(column)} = {self._placeholder}" for column in changes)
            predicate = " AND ".join(
                f"{quote_identifier(column)} IS NULL"
                if value is None
                else f"{quote_identifier(column)} = {self._placeholder}"
                for column, value in identity.items()
            )
            params = (*changes.values(), *(value for value in identity.values() if value is not None))
            cursor = self._db.execute(f"UPDATE {self._table} SET {setters} WHERE {predicate}", params)
            try:
                updated += cursor.rowcount
            finally:
                cursor.close()
            row.update(changes)
            self._remember_keys(row)
        return updated, len(rows)
