"""Tests for the bulk write optimizer."""

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


class TestBulkWriteOptimizerAbstraction:
    """Tests that the optimizer has been migrated to the BulkWriteOptimizer abstraction.

    Note: SQLiteBulkOptimizer.__init__ requires two arguments: execute_fn and fetch_pragma_fn.
    See sqlalchemy_adapter.py lines 208-219 for correct usage.
    """

    @staticmethod
    def _make_fetch_pragma_fn(adapter: Any) -> Any:
        """Create a fetch_pragma_fn from the adapter (retrieves current PRAGMA values)."""

        def fetch_pragma(name: str) -> Any:
            cursor = adapter.execute(f"PRAGMA {name}")
            row = cursor.fetchone() if hasattr(cursor, "fetchone") else cursor
            return row[0] if row else None

        return fetch_pragma

    def test_pragma_optimizer_via_sqlite_bulk_optimizer(self, tmp_db: str) -> None:
        """Invoke PragmaOptimizer via SQLiteBulkOptimizer."""
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer  # noqa: PLC0415
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter  # noqa: PLC0415

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        optimizer.preserve()
        optimizer.optimize(expected_rows=1000)
        optimizer.restore()
        adapter.close()

    def test_bulk_optimizer_protocol_satisfied(self, tmp_db: str) -> None:
        """SQLiteBulkOptimizer satisfies the BulkWriteOptimizer protocol."""
        from sqlseed.database._bulk_optimizer import BulkWriteOptimizer, SQLiteBulkOptimizer  # noqa: PLC0415
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter  # noqa: PLC0415

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        assert hasattr(optimizer, "preserve")
        assert hasattr(optimizer, "optimize")
        assert hasattr(optimizer, "restore")
        assert isinstance(optimizer, BulkWriteOptimizer)
        adapter.close()

    def test_sqlite_bulk_optimizer_three_tiers(self, tmp_db: str) -> None:
        """Three optimization tiers (light/moderate/aggressive) via the abstraction layer.

        Thresholds (strictly greater than, see _bulk_optimizer.py lines 85-87):
        - >100000: aggressive (synchronous=OFF, journal_mode=OFF)
        - >10000: moderate (synchronous=OFF, journal_mode=MEMORY)
        - else: light (synchronous=NORMAL, temp_store=MEMORY)
        """
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer  # noqa: PLC0415
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter  # noqa: PLC0415

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)
        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)

        # Different batch sizes trigger different optimization levels (use values > threshold to ensure the level)
        optimizer.preserve()
        optimizer.optimize(expected_rows=100)  # <=10000 -> light
        optimizer.restore()

        optimizer.preserve()
        optimizer.optimize(expected_rows=10001)  # >10000 -> moderate
        optimizer.restore()

        optimizer.preserve()
        optimizer.optimize(expected_rows=100001)  # >100000 -> aggressive
        optimizer.restore()

        adapter.close()

    def test_sqlite_bulk_optimizer_restore_after_optimize(self, tmp_db: str) -> None:
        """restore after optimize recovers original values."""
        from sqlseed.database._bulk_optimizer import SQLiteBulkOptimizer  # noqa: PLC0415
        from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter  # noqa: PLC0415

        adapter = RawSQLiteAdapter()
        adapter.connect(tmp_db)

        # Get original PRAGMA value
        original = adapter.execute("PRAGMA synchronous").fetchone()[0]

        fetch_pragma = self._make_fetch_pragma_fn(adapter)
        optimizer = SQLiteBulkOptimizer(adapter.execute, fetch_pragma)
        optimizer.preserve()
        optimizer.optimize(expected_rows=10000)
        optimizer.restore()

        # Verify the original value is restored
        restored = adapter.execute("PRAGMA synchronous").fetchone()[0]
        assert restored == original
        adapter.close()
