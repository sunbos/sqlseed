"""真实业务夹具回归；只写 pytest 的临时目录。"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from examples.scenario_lab.build import build_database
from examples.scenario_lab.validate import validate_database

if TYPE_CHECKING:
    from pathlib import Path


def test_build_is_deterministic_and_refuses_to_replace_existing_files(tmp_path: Path) -> None:
    """同一设计重建相同种子，重复目标不能被覆盖。"""
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    build_database(first)
    build_database(second)
    with sqlite3.connect(first) as left, sqlite3.connect(second) as right:
        assert list(left.iterdump()) == list(right.iterdump())
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        build_database(first)
    assert first.read_bytes() == before
    report = validate_database(first)
    assert report["ok"], report
    assert len(report["row_counts"]) == 24
    assert all(report["row_counts"].values())


def test_database_rejects_cross_tenant_keys_and_invalid_amounts_and_dates(tmp_path: Path) -> None:
    """让真实 SQLite 拒绝非法写入，而非只检查 DDL 文本。"""
    path = tmp_path / "scenario.db"
    build_database(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for statement in [
            "UPDATE orders SET tenant_id=2 WHERE id=1101",
            "UPDATE order_items SET discount_cents=999999 WHERE id=1201",
            "UPDATE orders SET promised_at='2020-01-01' WHERE id=1101",
            "UPDATE inventory SET reserved=on_hand+1 WHERE tenant_id=1",
            "UPDATE orders SET total_cents=1 WHERE id=1101",
        ]:
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(statement)
            db.rollback()
    assert validate_database(path)["ok"]


def test_seed_has_composite_edges_nullable_cycle_generated_and_wide_table(tmp_path: Path) -> None:
    """关键边界出现在实际结构和可查询种子中。"""
    path = tmp_path / "scenario.db"
    build_database(path)
    with sqlite3.connect(path) as db:
        assert len(db.execute('PRAGMA table_xinfo("orders")').fetchall()) >= 25
        assert len(db.execute('PRAGMA table_xinfo("tags")').fetchall()) == 2
        assert any(row[6] in (2, 3) for row in db.execute('PRAGMA table_xinfo("order_items")'))
        assert (
            db.execute(
                "SELECT COUNT(*) FROM shipments s JOIN shipment_events e "
                "ON e.id=s.current_event_id AND e.shipment_id=s.id"
            ).fetchone()[0]
            == 2
        )
        assert db.execute("SELECT COUNT(*) FROM employees WHERE manager_id IS NOT NULL").fetchone()[0] == 2


def test_business_validator_detects_balance_rules_not_enforced_by_row_checks(tmp_path: Path) -> None:
    """合法 FK/CHECK 记录仍可能在订单汇总或业务邮箱关联上不一致。"""
    path = tmp_path / "scenario.db"
    build_database(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE inventory SET on_hand=on_hand+1 WHERE tenant_id=1 AND warehouse_id=1001 AND product_id=1051")
        db.execute("UPDATE audit_events SET customer_email='missing@example.test' WHERE id=1")
    report = validate_database(path)
    assert not report["ok"]
    assert report["foreign_key_violations"] == []
    assert report["integrity"] == ["ok"]
    assert set(report["business_violations"]) == {"stock_ledger_matches_inventory", "audit_email_has_customer"}


def test_baseline_real_generation_and_web_boundaries_use_a_copy(tmp_path: Path) -> None:
    """真实 core 写入 38 行，Web 拒绝压力范围，原夹具保持不变。"""
    pytest.importorskip("sqlseed_web")
    from examples.scenario_lab.verify import verify

    source = build_database(tmp_path / "source.db")
    before = source.read_bytes()
    report = verify(source=source, web=True)
    assert report["ok"], report
    assert report["web"]["baseline_ok"]
    assert not report["web"]["stress_ok"]
    assert {issue["code"] for issue in report["web"]["stress_issues"]} == {"composite_fk_width", "cross_table_cycle"}
    assert sum(report["rows_added"].values()) == 38
    assert report["before"]["total_rows"] == 121
    assert report["after"]["total_rows"] == 159
    assert source.read_bytes() == before
