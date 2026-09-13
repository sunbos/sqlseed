"""Constraint solver supporting backtracking and composite unique constraints.

ConstraintSolver maintains sets of generated values, supporting single-column
and composite unique constraints. For large datasets (>100K rows), probabilistic
mode (hash-based) can be enabled to reduce memory usage.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class RegisterResult:
    """Constraint registration result, carrying backtracking need and target column info."""

    is_registered: bool = True
    should_backtrack: bool = False
    backtrack_targets: list[str] = field(default_factory=list)


class ConstraintSolver:
    """Constraint solver supporting backtracking and composite unique constraints.

    For large datasets (>100K rows), set probabilistic=True to use
    a hash-based probabilistic set that trades a small false-positive
    rate for significantly reduced memory usage.

    ``existing_value_check`` optionally checks candidate keys against a
    database. Existing values are never registered locally, so backtracking
    cannot accidentally make an existing database key available again.
    """

    def __init__(
        self,
        *,
        probabilistic: bool = False,
        existing_value_check: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self._probabilistic = probabilistic
        self._existing_value_check = existing_value_check
        self._seen: dict[str, set[Any]] = {}
        self._composite_seen: dict[str, set[tuple[Any, ...]]] = {}
        if probabilistic:
            self._hash_seen: dict[str, set[int]] = {}

    def _deterministic_hash(self, value: Any) -> int:
        data = f"{value!r}".encode()
        return int(hashlib.sha256(data).hexdigest()[:16], 16)

    def _is_seen(self, column_name: str, value: Any) -> bool:
        if self._probabilistic:
            h = self._deterministic_hash(value)
            seen = column_name in self._hash_seen and h in self._hash_seen[column_name]
        else:
            seen = column_name in self._seen and value in self._seen[column_name]
        return seen or bool(self._existing_value_check and self._existing_value_check({column_name: value}))

    def _register(self, column_name: str, value: Any) -> None:
        if self._probabilistic:
            h = self._deterministic_hash(value)
            if column_name not in self._hash_seen:
                self._hash_seen[column_name] = set()
            self._hash_seen[column_name].add(h)
        else:
            if column_name not in self._seen:
                self._seen[column_name] = set()
            self._seen[column_name].add(value)

    def _unregister_value(self, column_name: str, value: Any) -> None:
        if self._probabilistic:
            if column_name in self._hash_seen:
                self._hash_seen[column_name].discard(self._deterministic_hash(value))
        elif column_name in self._seen:
            self._seen[column_name].discard(value)

    def check_and_register(
        self,
        column_name: str,
        value: Any,
        is_unique: bool = False,
    ) -> bool:
        """Check whether a single-column value satisfies the unique constraint and register it.

        Args:
            column_name: Column name.
            value: The value to check.
            is_unique: Whether to enable unique constraint checking.

        Returns:
            True means the value passed the check and was registered;
            False means the value already exists (unique constraint violated).
            None values always return True (NULL does not participate in uniqueness checks).
        """
        if not is_unique:
            return True
        if value is None:
            return True
        if self._is_seen(column_name, value):
            return False
        self._register(column_name, value)
        return True

    def try_register(
        self,
        column_name: str,
        value: Any,
        is_unique: bool = False,
        source_columns: list[str] | None = None,
        *,
        min_value: int | float | None = None,
        max_value: int | float | None = None,
        regex: str | None = None,
    ) -> RegisterResult:
        """Attempt to register a single-column value, returning a result carrying backtracking info.

        Unlike check_and_register, this method returns a RegisterResult when
        the unique constraint is violated, containing the list of target columns
        to backtrack, enabling upper-layer streaming generators to perform
        backtracking retries.

        Args:
            column_name: Column name.
            value: The value to register.
            is_unique: Whether to enable unique constraint checking.
            source_columns: Optional list of backtracking target columns, defaults to [column_name].
            min_value: Optional inclusive lower bound.
            max_value: Optional inclusive upper bound.
            regex: Optional full-string pattern constraint.

        Returns:
            RegisterResult: is_registered=True means registration succeeded;
            is_registered=False with should_backtrack=True means backtracking is required.
        """
        if value is None:
            return RegisterResult(is_registered=True)

        valid = self._matches_value_constraints(column_name, value, min_value, max_value, regex)
        if not valid or (is_unique and self._is_seen(column_name, value)):
            return RegisterResult(
                is_registered=False,
                should_backtrack=True,
                backtrack_targets=source_columns if source_columns else [column_name],
            )
        if is_unique:
            self._register(column_name, value)
        return RegisterResult(is_registered=True)

    @staticmethod
    def _matches_value_constraints(
        column_name: str,
        value: Any,
        min_value: int | float | None,
        max_value: int | float | None,
        regex: str | None,
    ) -> bool:
        try:
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
        except TypeError as exc:
            raise ValueError(f"Column '{column_name}' produced a value incompatible with numeric constraints") from exc
        if regex is not None:
            try:
                pattern = re.compile(regex)
            except re.error as exc:
                raise ValueError(f"Column '{column_name}' has an invalid constraint regex: {exc}") from exc
            return isinstance(value, str) and pattern.fullmatch(value) is not None
        return True

    def _is_composite_seen(self, key_name: str, values: tuple[Any, ...]) -> bool:
        if any(v is None for v in values):
            return False
        return key_name in self._composite_seen and values in self._composite_seen[key_name]

    def _register_composite(self, key_name: str, values: tuple[Any, ...]) -> None:
        if key_name not in self._composite_seen:
            self._composite_seen[key_name] = set()
        self._composite_seen[key_name].add(values)

    def check_and_register_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
        *,
        columns: list[str] | None = None,
    ) -> bool:
        """Check the composite unique constraint and register the tuple value.

        Used for multi-column composite unique constraints (e.g., (col_a, col_b) joint unique).
        Skips the check when any value is None (under SQL semantics, NULL does not
        participate in unique constraints).

        Args:
            key_name: Unambiguous identifier for the composite constraint.
            values: Tuple of column values to check.
            columns: Column names for the optional existing-database lookup.

        Returns:
            True means the composite value passed the check and was registered;
            False means an identical composite already exists.
        """
        if any(v is None for v in values):
            return True

        if self._is_composite_seen(key_name, values):
            return False
        if (
            self._existing_value_check
            and columns is not None
            and self._existing_value_check(dict(zip(columns, values, strict=True)))
        ):
            return False
        self._register_composite(key_name, values)
        return True

    def unregister_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
    ) -> None:
        """Remove a previously registered composite unique-constraint value tuple."""
        if key_name in self._composite_seen:
            self._composite_seen[key_name].discard(values)

    def reset(self) -> None:
        """Clear all registered single-column and composite unique constraint values.

        Called before generating data for a new table, to avoid values registered
        for the previous table affecting the current table.
        """
        self._seen.clear()
        self._composite_seen.clear()
        if self._probabilistic:
            self._hash_seen.clear()

    def reset_column(self, column_name: str) -> None:
        """Clear all registered unique values for a single column."""
        self._seen.pop(column_name, None)
        if self._probabilistic:
            self._hash_seen.pop(column_name, None)

    def unregister(self, column_name: str, value: Any) -> None:
        """Remove a previously registered single-column unique value, allowing it to be re-registered."""
        self._unregister_value(column_name, value)

    def get_seen(self, column_name: str) -> set[Any]:
        """Return a copy of the seen values for a column.

        Used by ``DataStream`` to pass ``exclude_values`` to generators on
        UNIQUE retry, so generators can avoid producing values already in
        use. This is the root-cause fix for the "UNIQUE + semantic
        generators" failure pattern where ``faker.email()`` etc. produce
        duplicates on large row counts.

        Args:
            column_name: The column name.

        Returns:
            A copy of the set of seen values for the column. Empty set if
            the column has no registered values. In probabilistic mode,
            returns an empty set — generators cannot perform value-based
            exclude against hashes, so we skip the exclude fast-path and
            rely solely on ``try_register`` hash collision detection to
            trigger backtracking. Returning the hash set here would cause
            ``_dispatch.generate`` to compare generated values against
            hashes (always mismatch), making the exclude logic a no-op
            while falsely appearing to work.
        """
        if self._probabilistic:
            return set()
        return set(self._seen.get(column_name, set()))
