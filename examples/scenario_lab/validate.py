"""只读核验 SQLite 约束和 SQL CHECK 无法表达的跨表业务规则。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from sqlseed._utils.sql_safe import quote_identifier

BUSINESS_CHECKS = {
    "order_subtotal_matches_lines": """
        SELECT o.id FROM orders o LEFT JOIN order_items i ON i.tenant_id=o.tenant_id AND i.order_id=o.id
        GROUP BY o.id HAVING o.subtotal_cents <> COALESCE(SUM(i.line_total_cents),0)""",
    "captured_payments_match_paid_order": """
        SELECT o.id FROM orders o LEFT JOIN payments p
        ON p.tenant_id=o.tenant_id AND p.order_id=o.id AND p.status='captured'
        WHERE o.paid_at IS NOT NULL GROUP BY o.id HAVING o.total_cents <> COALESCE(SUM(p.amount_cents),0)""",
    "refunded_order_balance": """
        SELECT o.id FROM orders o LEFT JOIN returns r ON r.tenant_id=o.tenant_id AND r.order_id=o.id
        LEFT JOIN refunds f ON f.tenant_id=r.tenant_id AND f.return_id=r.id
        GROUP BY o.id HAVING o.refunded_cents <> COALESCE(SUM(f.amount_cents),0)""",
    "refunded_return_balance": """
        SELECT r.id FROM returns r WHERE r.status='refunded' AND
        (SELECT COALESCE(SUM(i.refund_cents),0) FROM return_items i
         WHERE i.tenant_id=r.tenant_id AND i.return_id=r.id)
        <> (SELECT COALESCE(SUM(f.amount_cents),0) FROM refunds f
            WHERE f.tenant_id=r.tenant_id AND f.return_id=r.id)""",
    "refund_payment_belongs_to_return_order": """
        SELECT f.id FROM refunds f JOIN returns r ON r.tenant_id=f.tenant_id AND r.id=f.return_id
        JOIN payments p ON p.tenant_id=f.tenant_id AND p.id=f.payment_id WHERE r.order_id<>p.order_id""",
    "stock_ledger_matches_inventory": """
        SELECT i.tenant_id,i.warehouse_id,i.product_id FROM inventory i LEFT JOIN stock_movements m
        ON m.tenant_id=i.tenant_id AND m.warehouse_id=i.warehouse_id AND m.product_id=i.product_id
        GROUP BY i.tenant_id,i.warehouse_id,i.product_id HAVING i.on_hand <> COALESCE(SUM(m.delta),0)""",
    "shipped_quantity_within_order": """
        SELECT i.id FROM order_items i JOIN shipment_items s
        ON s.tenant_id=i.tenant_id AND s.order_id=i.order_id AND s.line_no=i.line_no
        GROUP BY i.id HAVING SUM(s.quantity)>i.quantity""",
    "returned_quantity_within_order": """
        SELECT i.id FROM order_items i JOIN return_items r
        ON r.tenant_id=i.tenant_id AND r.order_id=i.order_id AND r.line_no=i.line_no
        GROUP BY i.id HAVING SUM(r.quantity)>i.quantity OR SUM(r.refund_cents)>i.line_total_cents""",
    "current_event_belongs_to_shipment": """
        SELECT s.id FROM shipments s JOIN shipment_events e ON e.tenant_id=s.tenant_id AND e.id=s.current_event_id
        WHERE e.shipment_id IS NULL OR e.shipment_id<>s.id""",
    "payment_chronology": """
        SELECT p.id FROM payments p JOIN orders o ON o.tenant_id=p.tenant_id AND o.id=p.order_id
        WHERE p.paid_at<o.ordered_at""",
    "return_after_delivery": """
        SELECT r.id FROM returns r JOIN orders o ON o.tenant_id=r.tenant_id AND o.id=r.order_id
        WHERE o.delivered_at IS NULL OR r.requested_at<o.delivered_at""",
    "audit_email_has_customer": """
        SELECT a.id FROM audit_events a WHERE a.customer_email IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM customers c WHERE c.email=a.customer_email)""",
}


def validate_database(path: Path) -> dict[str, Any]:
    """以只读连接返回物理约束和跨表业务约束报告。"""
    path = path.expanduser().resolve(strict=True)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        row_counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0] for table in tables
        }
        failures = {name: db.execute(sql).fetchall() for name, sql in BUSINESS_CHECKS.items()}
        failures = {name: rows for name, rows in failures.items() if rows}
    return {
        "ok": integrity == ["ok"] and not foreign_keys and not failures and len(tables) == 24,
        "integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "business_violations": failures,
        "business_checks": len(BUSINESS_CHECKS),
        "row_counts": row_counts,
        "total_rows": sum(row_counts.values()),
    }


def main() -> None:
    """打印只读报告，并用退出码表示是否通过。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    report = validate_database(args.database)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
