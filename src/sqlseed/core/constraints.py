from __future__ import annotations

from typing import Any


class ConstraintSolver:
    """约束求解器"""

    def __init__(self) -> None:
        self._seen: dict[str, set[Any]] = {}

    def check_and_register(
        self,
        column_name: str,
        value: Any,
        unique: bool = False,
    ) -> bool:
        if unique:
            if column_name not in self._seen:
                self._seen[column_name] = set()
            if value in self._seen[column_name]:
                return False
            self._seen[column_name].add(value)

        return True

    def reset(self) -> None:
        self._seen.clear()

    def reset_column(self, column_name: str) -> None:
        self._seen.pop(column_name, None)

    def unregister(self, column_name: str, value: Any) -> None:
        if column_name in self._seen:
            self._seen[column_name].discard(value)
