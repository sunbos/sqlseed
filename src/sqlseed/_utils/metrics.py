from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricEntry:
    name: str
    value: float
    timestamp: float = field(default_factory=time.monotonic)


class MetricsCollector:
    def __init__(self) -> None:
        self._entries: list[MetricEntry] = []

    def record(self, name: str, value: float) -> None:
        self._entries.append(MetricEntry(name=name, value=value))

    def get_entries(self, name: str | None = None) -> list[MetricEntry]:
        if name is None:
            return list(self._entries)
        return [e for e in self._entries if e.name == name]

    def summary(self) -> dict[str, Any]:
        if not self._entries:
            return {}
        by_name: dict[str, list[float]] = {}
        for entry in self._entries:
            by_name.setdefault(entry.name, []).append(entry.value)
        result: dict[str, Any] = {}
        for name, values in by_name.items():
            result[name] = {
                "count": len(values),
                "total": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }
        return result

    def clear(self) -> None:
        self._entries.clear()
