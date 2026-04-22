from __future__ import annotations

import pytest

from sqlseed.core.result import GenerationResult


class TestGenerationResult:
    def test_basic_result(self) -> None:
        result = GenerationResult(table_name="users", count=100, elapsed=1.0)
        assert result.table_name == "users"
        assert result.count == 100
        assert result.elapsed == pytest.approx(1.0)
        assert result.rows_per_second == pytest.approx(100.0)

    def test_str(self) -> None:
        result = GenerationResult(table_name="users", count=100, elapsed=1.0)
        text = str(result)
        assert "users" in text
        assert "100" in text
        assert "100 rows/s" in text

    def test_zero_elapsed(self) -> None:
        result = GenerationResult(table_name="users", count=100, elapsed=0.0)
        assert result.rows_per_second == pytest.approx(0.0)

    def test_with_errors(self) -> None:
        result = GenerationResult(table_name="users", count=0, elapsed=0.1, errors=["some error"])
        assert len(result.errors) == 1
