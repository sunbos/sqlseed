"""Tests for database adapter shared helper functions.

Covers ``fetch_index_info``, ``fetch_sample_rows``, ``batch_insert_rows``,
``apply_bulk_optimize`` and ``apply_bulk_restore`` with both mock execute_fn
unit tests and integration tests using the ``raw_adapter`` fixture.
"""

from __future__ import annotations

from typing import Any

from sqlseed.database._helpers import (
    apply_bulk_optimize,
    apply_bulk_restore,
    batch_insert_rows,
    fetch_index_info,
    fetch_sample_rows,
)
from sqlseed.database._protocol import ColumnInfo, IndexInfo


class FakeCursor:
    """Minimal cursor-like object returning predefined rows from fetchall()."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = list(rows) if rows is not None else []

    def fetchall(self) -> list[Any]:
        return self._rows


def make_column(name: str, col_type: str = "TEXT") -> ColumnInfo:
    """Create a ColumnInfo instance for testing."""
    return ColumnInfo(
        name=name,
        type=col_type,
        nullable=True,
        default=None,
        is_primary_key=False,
        is_autoincrement=False,
    )


class FakeOptimizer:
    """Fake bulk write optimizer that records call order and arguments."""

    def __init__(self) -> None:
        self.preserve_called = False
        self.optimize_arg: Any = "not_called"
        self.restore_called = False
        self.call_order: list[str] = []

    def preserve(self) -> None:
        self.preserve_called = True
        self.call_order.append("preserve")

    def optimize(self, expected_rows: int | None = None) -> None:
        self.optimize_arg = expected_rows
        self.call_order.append("optimize")

    def restore(self) -> None:
        self.restore_called = True
        self.call_order.append("restore")


# ---------------------------------------------------------------------------
# fetch_index_info
# ---------------------------------------------------------------------------


class TestFetchIndexInfo:
    """Tests for ``fetch_index_info``."""

    @staticmethod
    def _make_execute_fn(
        index_list_rows: list[Any],
        index_info_map: dict[str, list[Any]] | None = None,
    ) -> tuple[Any, list[tuple[str, Any]]]:
        """Build a mock execute_fn that routes PRAGMA queries to predefined rows.

        Args:
            index_list_rows: Rows returned by ``PRAGMA index_list``.
            index_info_map: Mapping of index name to rows returned by
                ``PRAGMA index_info`` for that index.

        Returns:
            A tuple of (execute_fn, call log).
        """
        index_info_map = index_info_map or {}
        calls: list[tuple[str, Any]] = []

        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            calls.append((sql, params))
            if "PRAGMA index_list" in sql:
                return FakeCursor(index_list_rows)
            if "PRAGMA index_info" in sql:
                for idx_name, rows in index_info_map.items():
                    if f'"{idx_name}"' in sql:
                        return FakeCursor(rows)
                return FakeCursor([])
            return FakeCursor([])

        return execute_fn, calls

    def test_no_indexes_returns_empty(self) -> None:
        execute_fn, _ = self._make_execute_fn([])
        result = fetch_index_info(execute_fn, "users")
        assert result == []

    def test_single_unique_index_single_column(self) -> None:
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx_email", 1)],
            index_info_map={"idx_email": [(0, "users", "email")]},
        )
        result = fetch_index_info(execute_fn, "users")
        assert len(result) == 1
        idx = result[0]
        assert idx.name == "idx_email"
        assert idx.table == "users"
        assert idx.columns == ("email",)
        assert idx.unique is True

    def test_non_unique_index(self) -> None:
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx_name", 0)],
            index_info_map={"idx_name": [(0, "users", "name")]},
        )
        result = fetch_index_info(execute_fn, "users")
        assert len(result) == 1
        assert result[0].unique is False

    def test_multi_column_index(self) -> None:
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx_composite", 1)],
            index_info_map={
                "idx_composite": [
                    (0, "users", "last_name"),
                    (1, "users", "first_name"),
                ],
            },
        )
        result = fetch_index_info(execute_fn, "users")
        assert len(result) == 1
        assert result[0].columns == ("last_name", "first_name")

    def test_multiple_indexes(self) -> None:
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[
                (1, "idx_a", 1),
                (2, "idx_b", 0),
            ],
            index_info_map={
                "idx_a": [(0, "users", "a")],
                "idx_b": [(0, "users", "b")],
            },
        )
        result = fetch_index_info(execute_fn, "users")
        assert len(result) == 2
        names = [r.name for r in result]
        assert "idx_a" in names
        assert "idx_b" in names
        unique_flags = {r.name: r.unique for r in result}
        assert unique_flags["idx_a"] is True
        assert unique_flags["idx_b"] is False

    def test_none_column_values_filtered(self) -> None:
        """When ``cr[2]`` is None, it should be excluded from the columns tuple."""
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx_x", 0)],
            index_info_map={
                "idx_x": [
                    (0, "users", "col1"),
                    (1, "users", None),
                ],
            },
        )
        result = fetch_index_info(execute_fn, "users")
        assert result[0].columns == ("col1",)

    def test_returns_index_info_instances(self) -> None:
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx", 1)],
            index_info_map={"idx": [(0, "t", "c")]},
        )
        result = fetch_index_info(execute_fn, "t")
        assert all(isinstance(r, IndexInfo) for r in result)

    def test_table_name_quoted_in_pragma(self) -> None:
        execute_fn, calls = self._make_execute_fn([])
        fetch_index_info(execute_fn, "users")
        sqls = [c[0] for c in calls]
        assert any('PRAGMA index_list("users")' in sql for sql in sqls)

    def test_index_name_quoted_in_pragma(self) -> None:
        execute_fn, calls = self._make_execute_fn(
            index_list_rows=[(1, "idx_email", 1)],
            index_info_map={"idx_email": [(0, "users", "email")]},
        )
        fetch_index_info(execute_fn, "users")
        sqls = [c[0] for c in calls]
        assert any('PRAGMA index_info("idx_email")' in sql for sql in sqls)

    def test_index_with_no_columns(self) -> None:
        """An index with no column rows yields an empty columns tuple."""
        execute_fn, _ = self._make_execute_fn(
            index_list_rows=[(1, "idx_empty", 0)],
            index_info_map={"idx_empty": []},
        )
        result = fetch_index_info(execute_fn, "users")
        assert len(result) == 1
        assert result[0].columns == ()

    def test_integration_with_raw_adapter(self, raw_adapter) -> None:
        """Integration: the users table has an autoindex for its PRIMARY KEY."""
        result = raw_adapter.get_index_info("users")
        assert isinstance(result, list)
        # SQLite creates an autoindex for INTEGER PRIMARY KEY
        for idx in result:
            assert isinstance(idx, IndexInfo)
            assert idx.table == "users"


# ---------------------------------------------------------------------------
# fetch_sample_rows
# ---------------------------------------------------------------------------


class TestFetchSampleRows:
    """Tests for ``fetch_sample_rows``."""

    @staticmethod
    def _make_execute_fn(rows: list[Any]) -> Any:
        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            return FakeCursor(rows)

        return execute_fn

    def test_empty_table(self) -> None:
        execute_fn = self._make_execute_fn([])
        columns = [make_column("id"), make_column("name")]
        result = fetch_sample_rows(execute_fn, columns, "users")
        assert result == []

    def test_single_row(self) -> None:
        execute_fn = self._make_execute_fn([(1, "alice")])
        columns = [make_column("id"), make_column("name")]
        result = fetch_sample_rows(execute_fn, columns, "users")
        assert len(result) == 1
        assert result[0] == {"id": 1, "name": "alice"}

    def test_multiple_rows(self) -> None:
        execute_fn = self._make_execute_fn([
            (1, "alice"),
            (2, "bob"),
            (3, "carol"),
        ])
        columns = [make_column("id"), make_column("name")]
        result = fetch_sample_rows(execute_fn, columns, "users")
        assert len(result) == 3
        assert result[0]["name"] == "alice"
        assert result[1]["name"] == "bob"
        assert result[2]["name"] == "carol"

    def test_default_limit_is_five(self) -> None:
        captured: dict[str, Any] = {}

        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            captured["sql"] = sql
            captured["params"] = params
            return FakeCursor([])

        columns = [make_column("id")]
        fetch_sample_rows(execute_fn, columns, "users")
        assert captured["params"] == [5]

    def test_custom_limit_passed(self) -> None:
        captured: dict[str, Any] = {}

        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            captured["params"] = params
            return FakeCursor([])

        columns = [make_column("id")]
        fetch_sample_rows(execute_fn, columns, "users", limit=20)
        assert captured["params"] == [20]

    def test_limit_zero(self) -> None:
        captured: dict[str, Any] = {}

        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            captured["params"] = params
            return FakeCursor([])

        columns = [make_column("id")]
        fetch_sample_rows(execute_fn, columns, "users", limit=0)
        assert captured["params"] == [0]

    def test_sql_contains_quoted_identifiers(self) -> None:
        captured: dict[str, Any] = {}

        def execute_fn(sql: str, params: Any = None) -> FakeCursor:
            captured["sql"] = sql
            return FakeCursor([])

        columns = [make_column("id"), make_column("name")]
        fetch_sample_rows(execute_fn, columns, "users", limit=10)
        assert '"id"' in captured["sql"]
        assert '"name"' in captured["sql"]
        assert '"users"' in captured["sql"]
        assert "LIMIT" in captured["sql"]

    def test_dict_keys_match_column_names(self) -> None:
        execute_fn = self._make_execute_fn([(1, "alice", True)])
        columns = [make_column("id"), make_column("name"), make_column("active")]
        result = fetch_sample_rows(execute_fn, columns, "users")
        assert len(result) == 1
        assert set(result[0].keys()) == {"id", "name", "active"}

    def test_empty_columns_list(self) -> None:
        execute_fn = self._make_execute_fn([])
        result = fetch_sample_rows(execute_fn, [], "users")
        assert result == []

    def test_single_column(self) -> None:
        execute_fn = self._make_execute_fn([(1,), (2,), (3,)])
        columns = [make_column("id")]
        result = fetch_sample_rows(execute_fn, columns, "users")
        assert len(result) == 3
        assert result[0] == {"id": 1}

    def test_integration_with_raw_adapter(self, raw_adapter_with_data) -> None:
        result = raw_adapter_with_data.get_sample_rows("users", limit=3)
        assert len(result) == 3
        assert "name" in result[0]
        assert "email" in result[0]


# ---------------------------------------------------------------------------
# batch_insert_rows
# ---------------------------------------------------------------------------


class TestBatchInsertRows:
    """Tests for ``batch_insert_rows``."""

    def test_empty_iterator(self) -> None:
        inserted = batch_insert_rows(iter([]), 5, len)
        assert inserted == 0

    def test_single_batch_smaller_than_batch_size(self) -> None:
        data = iter([{"a": 1}, {"a": 2}, {"a": 3}])
        inserted = batch_insert_rows(data, 5, len)
        assert inserted == 3

    def test_exact_multiple_of_batch_size(self) -> None:
        data = iter([{"a": i} for i in range(10)])
        calls: list[int] = []

        def insert_fn(batch: list[dict[str, Any]]) -> int:
            calls.append(len(batch))
            return len(batch)

        inserted = batch_insert_rows(data, 5, insert_fn)
        assert inserted == 10
        assert calls == [5, 5]

    def test_last_batch_smaller(self) -> None:
        data = iter([{"a": i} for i in range(7)])
        calls: list[int] = []

        def insert_fn(batch: list[dict[str, Any]]) -> int:
            calls.append(len(batch))
            return len(batch)

        inserted = batch_insert_rows(data, 5, insert_fn)
        assert inserted == 7
        assert calls == [5, 2]

    def test_batch_size_one(self) -> None:
        data = iter([{"a": i} for i in range(3)])
        calls: list[int] = []

        def insert_fn(batch: list[dict[str, Any]]) -> int:
            calls.append(len(batch))
            return len(batch)

        inserted = batch_insert_rows(data, 1, insert_fn)
        assert inserted == 3
        assert calls == [1, 1, 1]

    def test_batch_size_equals_data_length(self) -> None:
        data = iter([{"a": i} for i in range(5)])
        calls: list[int] = []

        def insert_fn(batch: list[dict[str, Any]]) -> int:
            calls.append(len(batch))
            return len(batch)

        inserted = batch_insert_rows(data, 5, insert_fn)
        assert inserted == 5
        assert calls == [5]

    def test_insert_fn_return_value_summed(self) -> None:
        """The total is the sum of return values, not the data length."""
        data = iter([{"a": i} for i in range(10)])

        def insert_fn(batch: list[dict[str, Any]]) -> int:
            return 1  # always reports 1 regardless of batch size

        inserted = batch_insert_rows(data, 5, insert_fn)
        assert inserted == 2  # 2 batches x 1

    def test_insert_fn_returning_zero(self) -> None:
        data = iter([{"a": i} for i in range(5)])

        def return_zero(batch: list[dict[str, Any]]) -> int:
            return 0

        inserted = batch_insert_rows(data, 5, return_zero)
        assert inserted == 0

    def test_single_row(self) -> None:
        data = iter([{"a": 1}])
        inserted = batch_insert_rows(data, 10, len)
        assert inserted == 1

    def test_integration_with_raw_adapter(self, raw_adapter) -> None:
        data = iter([{"name": f"u{i}", "email": f"u{i}@t.com"} for i in range(12)])
        inserted = raw_adapter.batch_insert("users", data, batch_size=5)
        assert inserted == 12
        assert raw_adapter.get_row_count("users") == 12


# ---------------------------------------------------------------------------
# apply_bulk_optimize
# ---------------------------------------------------------------------------


class TestApplyBulkOptimize:
    """Tests for ``apply_bulk_optimize``."""

    def test_none_optimizer_is_noop(self) -> None:
        # Should not raise
        apply_bulk_optimize(None)

    def test_none_optimizer_with_expected_rows_is_noop(self) -> None:
        apply_bulk_optimize(None, expected_rows=1000)

    def test_calls_preserve_and_optimize(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_optimize(optimizer)
        assert optimizer.preserve_called is True
        assert optimizer.optimize_arg is None

    def test_calls_optimize_with_expected_rows(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_optimize(optimizer, expected_rows=50000)
        assert optimizer.preserve_called is True
        assert optimizer.optimize_arg == 50000

    def test_preserve_called_before_optimize(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_optimize(optimizer)
        assert optimizer.call_order == ["preserve", "optimize"]

    def test_integration_with_raw_adapter(self, raw_adapter) -> None:
        raw_adapter.optimize_for_bulk_write(1000)
        raw_adapter.restore_settings()


# ---------------------------------------------------------------------------
# apply_bulk_restore
# ---------------------------------------------------------------------------


class TestApplyBulkRestore:
    """Tests for ``apply_bulk_restore``."""

    def test_none_optimizer_is_noop(self) -> None:
        apply_bulk_restore(None)

    def test_calls_restore(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_restore(optimizer)
        assert optimizer.restore_called is True

    def test_restore_only_not_preserve_or_optimize(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_restore(optimizer)
        assert optimizer.call_order == ["restore"]

    def test_optimize_then_restore_lifecycle(self) -> None:
        optimizer = FakeOptimizer()
        apply_bulk_optimize(optimizer, expected_rows=1000)
        apply_bulk_restore(optimizer)
        assert optimizer.call_order == ["preserve", "optimize", "restore"]

    def test_integration_with_raw_adapter(self, raw_adapter) -> None:
        raw_adapter.optimize_for_bulk_write(1000)
        raw_adapter.restore_settings()
