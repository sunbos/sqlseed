from __future__ import annotations

from typing import Any

from sqlseed.database.optimizer import PragmaOptimizer


class TestPragmaOptimizer:
    def _make_optimizer(self) -> tuple[PragmaOptimizer, list[str], dict[str, Any]]:
        executed = []
        fetched = {
            "synchronous": 2,
            "journal_mode": "wal",
            "cache_size": -2000,
            "temp_store": 0,
            "auto_vacuum": 0,
            "page_size": 4096,
            "mmap_size": 0,
        }

        def execute_fn(sql):
            executed.append(sql)

        def fetch_fn(name):
            return fetched.get(name)

        return PragmaOptimizer(execute_fn, fetch_fn), executed, fetched

    def test_preserve_and_restore(self) -> None:
        optimizer, executed, _ = self._make_optimizer()
        optimizer.preserve()
        assert optimizer._original is not None
        optimizer.restore()
        assert len(executed) > 0

    def test_light_optimization(self) -> None:
        optimizer, executed, _ = self._make_optimizer()
        optimizer.preserve()
        optimizer.optimize(1000)
        assert any("synchronous = NORMAL" in sql for sql in executed)

    def test_moderate_optimization(self) -> None:
        optimizer, executed, _ = self._make_optimizer()
        optimizer.preserve()
        optimizer.optimize(50000)
        assert any("synchronous = OFF" in sql for sql in executed)
        assert any("journal_mode = MEMORY" in sql for sql in executed)

    def test_aggressive_optimization(self) -> None:
        optimizer, executed, _ = self._make_optimizer()
        optimizer.preserve()
        optimizer.optimize(200000)
        assert any("journal_mode = OFF" in sql for sql in executed)
        assert any("mmap_size = 536870912" in sql for sql in executed)

    def test_optimize_default(self) -> None:
        optimizer, executed, _ = self._make_optimizer()
        optimizer.preserve()
        optimizer.optimize(None)
        assert any("synchronous = NORMAL" in sql for sql in executed)

    def test_restore_without_preserve(self) -> None:
        optimizer, _, _ = self._make_optimizer()
        optimizer.restore()
