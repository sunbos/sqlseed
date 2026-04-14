from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RegisterResult:
    registered: bool = True
    need_backtrack: bool = False
    backtrack_targets: list[str] = field(default_factory=list)


class ConstraintSolver:
    """约束求解器，支持回溯和复合唯一约束

    For large datasets (>100K rows), set probabilistic=True to use
    a hash-based probabilistic set that trades a small false-positive
    rate for significantly reduced memory usage.
    """

    def __init__(
        self,
        *,
        probabilistic: bool = False,
        expected_count: int = 10000,
    ) -> None:
        self._probabilistic = probabilistic
        self._expected_count = expected_count
        self._seen: dict[str, set[Any]] = {}
        self._composite_seen: dict[str, set[tuple[Any, ...]]] = {}
        if probabilistic:
            self._hash_seen: dict[str, set[int]] = {}

    def _is_seen(self, column_name: str, value: Any) -> bool:
        if self._probabilistic:
            h = hash(value)
            if column_name not in self._hash_seen:
                self._hash_seen[column_name] = set()
            if h in self._hash_seen[column_name]:
                return True
            self._hash_seen[column_name].add(h)
            return False
        if column_name not in self._seen:
            self._seen[column_name] = set()
        if value in self._seen[column_name]:
            return True
        self._seen[column_name].add(value)
        return False

    def _unregister_value(self, column_name: str, value: Any) -> None:
        if self._probabilistic:
            if column_name in self._hash_seen:
                self._hash_seen[column_name].discard(hash(value))
        elif column_name in self._seen:
            self._seen[column_name].discard(value)

    def check_and_register(
        self,
        column_name: str,
        value: Any,
        unique: bool = False,
    ) -> bool:
        if unique:
            return not self._is_seen(column_name, value)
        return True

    def try_register(
        self,
        column_name: str,
        value: Any,
        unique: bool = False,
        source_columns: list[str] | None = None,
    ) -> RegisterResult:
        if not unique:
            return RegisterResult(registered=True)

        if self._is_seen(column_name, value):
            return RegisterResult(
                registered=False,
                need_backtrack=True,
                backtrack_targets=source_columns if source_columns else [column_name],
            )
        return RegisterResult(registered=True)

    def check_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
    ) -> bool:
        if key_name not in self._composite_seen:
            self._composite_seen[key_name] = set()
        if values in self._composite_seen[key_name]:
            return False
        self._composite_seen[key_name].add(values)
        return True

    def unregister_composite(
        self,
        key_name: str,
        values: tuple[Any, ...],
    ) -> None:
        if key_name in self._composite_seen:
            self._composite_seen[key_name].discard(values)

    def reset(self) -> None:
        self._seen.clear()
        self._composite_seen.clear()
        if self._probabilistic:
            self._hash_seen.clear()

    def reset_column(self, column_name: str) -> None:
        self._seen.pop(column_name, None)

    def unregister(self, column_name: str, value: Any) -> None:
        self._unregister_value(column_name, value)
