from __future__ import annotations

import time

import pytest
from sqlseed_ai.auto_heal.time_budget import TimeBudgetController


def test_initial_budget_allocated():
    ctrl = TimeBudgetController(total_seconds=300.0, table_count=10)
    assert ctrl.per_table_budget() == pytest.approx(30.0)


def test_zero_tables_returns_total():
    ctrl = TimeBudgetController(total_seconds=300.0, table_count=0)
    assert ctrl.per_table_budget() == 300.0


def test_time_remaining_decreases():
    ctrl = TimeBudgetController(total_seconds=1.0, table_count=1)
    time.sleep(0.05)
    assert ctrl.time_remaining() < 1.0
    assert ctrl.time_remaining() > 0.0


def test_is_expired_after_timeout():
    ctrl = TimeBudgetController(total_seconds=0.01, table_count=1)
    time.sleep(0.05)
    assert ctrl.is_expired() is True


def test_extend_budget():
    """Budget can be extended mid-run (e.g., for retries)."""
    ctrl = TimeBudgetController(total_seconds=1.0, table_count=1)
    ctrl.extend(60.0)
    assert ctrl.per_table_budget() > 30.0  # roughly (61.0 / 1)
