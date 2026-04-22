from __future__ import annotations

import hashlib
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
    ) -> None:
        self._probabilistic = probabilistic
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
            return column_name in self._hash_seen and h in self._hash_seen[column_name]
        return column_name in self._seen and value in self._seen[column_name]

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
        unique: bool = False,
    ) -> bool:
        if not unique:
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
        unique: bool = False,
        source_columns: list[str] | None = None,
    ) -> RegisterResult:
        if not unique:
            return RegisterResult(registered=True)

        if value is None:
            return RegisterResult(registered=True)

        if self._is_seen(column_name, value):
            return RegisterResult(
                registered=False,
                need_backtrack=True,
                backtrack_targets=source_columns if source_columns else [column_name],
            )
        self._register(column_name, value)
        return RegisterResult(registered=True)

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
    ) -> bool:
        if any(v is None for v in values):
            return True

        if self._is_composite_seen(key_name, values):
            return False
        self._register_composite(key_name, values)
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
        if self._probabilistic:
            self._hash_seen.pop(column_name, None)

    def unregister(self, column_name: str, value: Any) -> None:
        self._unregister_value(column_name, value)
