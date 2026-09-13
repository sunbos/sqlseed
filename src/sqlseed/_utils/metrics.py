"""Performance metrics collection for sqlseed.

Provides ``MetricsCollector`` for recording named numeric samples and
computing aggregate statistics (count / total / min / max / avg).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricEntry:
    """A single recorded metric sample.

    ``timestamp`` defaults to ``time.monotonic()`` — a monotonically
    increasing clock that is immune to system clock adjustments (NTP slews,
    manual changes, DST). Suitable for measuring elapsed durations but
    **not** for displaying wall-clock times to users.
    """

    name: str
    value: float
    timestamp: float = field(default_factory=time.monotonic)


class MetricsCollector:
    """Collects named metric samples and computes aggregate statistics."""

    def __init__(self) -> None:
        self._entries: list[MetricEntry] = []

    def __repr__(self) -> str:
        return f"MetricsCollector(entries={len(self._entries)})"

    def record(self, name: str, value: float) -> None:
        """Append a new metric sample."""
        self._entries.append(MetricEntry(name=name, value=value))

    def get_entries(self, name: str | None = None) -> list[MetricEntry]:
        """Return recorded entries, optionally filtered by name."""
        if name is None:
            return list(self._entries)
        return [e for e in self._entries if e.name == name]

    def summary(self) -> dict[str, Any]:
        """Aggregate recorded metrics by name: count / total / min / max / avg."""
        if not self._entries:
            return {}

        result: dict[str, dict[str, Any]] = {}
        for entry in self._entries:
            name = entry.name
            val = entry.value
            if name not in result:
                result[name] = {
                    "count": 1,
                    "total": val,
                    "min": val,
                    "max": val,
                }
            else:
                stats = result[name]
                stats["count"] += 1
                stats["total"] += val
                if val < stats["min"]:
                    stats["min"] = val
                if val > stats["max"]:
                    stats["max"] = val

        for stats in result.values():
            stats["avg"] = stats["total"] / stats["count"]

        return result

    def clear(self) -> None:
        """Remove all recorded entries."""
        self._entries.clear()
