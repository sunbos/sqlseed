from __future__ import annotations

from sqlseed._utils.metrics import MetricsCollector


class TestMetricsCollector:
    def test_record(self) -> None:
        mc = MetricsCollector()
        mc.record("test", 1.0)
        mc.record("test", 2.0)
        assert len(mc._entries) == 2

    def test_get_entries_all(self) -> None:
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        entries = mc.get_entries()
        assert len(entries) == 2

    def test_get_entries_by_name(self) -> None:
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        mc.record("a", 3.0)
        entries = mc.get_entries("a")
        assert len(entries) == 2

    def test_summary_empty(self) -> None:
        mc = MetricsCollector()
        result = mc.summary()
        assert result == {}

    def test_summary_with_data(self) -> None:
        mc = MetricsCollector()
        mc.record("latency", 1.0)
        mc.record("latency", 3.0)
        mc.record("latency", 5.0)
        result = mc.summary()
        assert "latency" in result
        assert result["latency"]["count"] == 3
        assert result["latency"]["total"] == 9.0
        assert result["latency"]["avg"] == 3.0
        assert result["latency"]["min"] == 1.0
        assert result["latency"]["max"] == 5.0

    def test_clear(self) -> None:
        mc = MetricsCollector()
        mc.record("test", 1.0)
        mc.clear()
        assert len(mc._entries) == 0
