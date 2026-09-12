"""构建独立业务夹具；已有目标文件绝不覆盖，不调用数据生成或网络。"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from sqlseed._utils.sql_safe import quote_identifier

HERE = Path(__file__).resolve().parent
DEFAULT_TARGET = Path.home() / "Desktop" / "sqlseed_scenario_lab.db"


def insert(db: sqlite3.Connection, table: str, **values: Any) -> None:
    """使用引用后的标识符和绑定参数插入一条固定种子。"""
    columns = ",".join(quote_identifier(column) for column in values)
    placeholders = ",".join("?" for _ in values)
    db.execute(f"INSERT INTO {quote_identifier(table)} ({columns}) VALUES ({placeholders})", tuple(values.values()))


def _seed_tenant_people(db: sqlite3.Connection, tenant: int, city: str) -> None:
    base = tenant * 1000
    insert(db, "tenants", id=tenant, code=f"T{tenant:02}", name=f"{city}测试商户")
    for number in (1, 2):
        insert(
            db,
            "warehouses",
            id=base + number,
            tenant_id=tenant,
            code=f"WH-{number}",
            name=f"{city}{'中心' if number == 1 else '备用'}仓",
            city=city,
            capacity=10000,
        )
    for number in (1, 2):
        insert(
            db,
            "employees",
            id=base + 10 + number,
            tenant_id=tenant,
            manager_id=None if number == 1 else base + 11,
            email=f"staff{number}@tenant{tenant}.example.test",
            name=f"员工{tenant}-{number}",
            role="manager" if number == 1 else "operator",
        )
    _seed_tenant_customers(db, tenant, city)


def _seed_tenant_customers(db: sqlite3.Connection, tenant: int, city: str) -> None:
    """Insert tenant customers with their two consistent shipping addresses."""
    base = tenant * 1000
    for number in (1, 2, 3):
        customer = base + 20 + number
        insert(
            db,
            "customers",
            id=customer,
            tenant_id=tenant,
            email=f"customer{number}@tenant{tenant}.example.test",
            name=f"客户{tenant}-{number}",
            phone=f"1380000{tenant:02}{number:02}",
            tier="vip" if number == 1 else "standard",
        )
        for offset in (0, 1):
            insert(
                db,
                "addresses",
                id=base + 29 + number * 2 + offset,
                tenant_id=tenant,
                customer_id=customer,
                recipient=f"客户{tenant}-{number}",
                province="浙江" if tenant == 1 else "四川",
                city=city,
                street=f"测试路{number * 10 + offset}号",
                postal_code="310000" if tenant == 1 else "610000",
                is_default=1 - offset,
            )


def _seed_tenant_catalog(db: sqlite3.Connection, tenant: int) -> None:
    base = tenant * 1000
    for number in (1, 2):
        insert(
            db,
            "suppliers",
            id=base + 40 + number,
            tenant_id=tenant,
            code=f"SUP-{number}",
            name=f"供应商{tenant}-{number}",
        )
    for number, (name, price, cost) in enumerate(
        [("便携支架", 1000, 400), ("桌面收纳", 1500, 650), ("办公灯具", 2000, 1000)], 1
    ):
        product = base + 50 + number
        insert(
            db,
            "products",
            id=product,
            tenant_id=tenant,
            sku=f"SKU-{number:03}",
            name=name,
            price_cents=price,
            cost_cents=cost,
            weight_grams=200 * number,
        )
        insert(
            db,
            "supplier_products",
            tenant_id=tenant,
            supplier_id=base + 41,
            product_id=product,
            supplier_sku=f"V-{tenant}-{number}",
            unit_cost_cents=cost,
        )
        insert(db, "product_tags", tenant_id=tenant, product_id=product, tag_id=number)
        for warehouse, on_hand in ((base + 1, 19 if number < 3 else 20), (base + 2, 5)):
            insert(db, "inventory", tenant_id=tenant, warehouse_id=warehouse, product_id=product, on_hand=on_hand)


def _seed_tenant_order(db: sqlite3.Connection, tenant: int, city: str) -> int:
    base = tenant * 1000
    order = base + 101
    insert(
        db,
        "orders",
        id=order,
        tenant_id=tenant,
        customer_id=base + 21,
        shipping_address_id=base + 31,
        billing_address_id=base + 32,
        owner_id=base + 12,
        order_no="ORD-2026-0001",
        status="delivered",
        ordered_at="2026-01-03 09:00:00",
        promised_at="2026-01-07 18:00:00",
        paid_at="2026-01-03 09:05:00",
        shipped_at="2026-01-04 10:00:00",
        delivered_at="2026-01-06 15:00:00",
        subtotal_cents=3400,
        discount_cents=200,
        shipping_cents=100,
        tax_cents=300,
        refunded_cents=900,
        contact_email=f"customer1@tenant{tenant}.example.test",
        delivery_note="工作日送达",
        invoice_title=f"商户{tenant}订单",
        metadata='{"campaign":"winter"}',
    )
    for number, quantity, price, discount in ((1, 2, 1000, 100), (2, 1, 1500, 0)):
        insert(
            db,
            "order_items",
            id=base + 200 + number,
            tenant_id=tenant,
            order_id=order,
            line_no=number,
            product_id=base + 50 + number,
            quantity=quantity,
            unit_price_cents=price,
            discount_cents=discount,
        )
    insert(
        db,
        "payments",
        id=base + 301,
        tenant_id=tenant,
        order_id=order,
        payment_no="PAY-0001",
        method="card",
        amount_cents=3600,
        paid_at="2026-01-03 09:05:00",
    )
    shipment = base + 401
    insert(
        db,
        "shipments",
        id=shipment,
        tenant_id=tenant,
        order_id=order,
        warehouse_id=base + 1,
        tracking_no=f"TRACK-{tenant}-0001",
        carrier="测试物流",
        status="delivered",
        dispatched_at="2026-01-04 10:00:00",
        delivered_at="2026-01-06 15:00:00",
    )
    for number, event_type, timestamp in (
        (1, "created", "2026-01-03 10:00:00"),
        (2, "picked_up", "2026-01-04 10:00:00"),
        (3, "delivered", "2026-01-06 15:00:00"),
    ):
        insert(
            db,
            "shipment_events",
            id=base + 500 + number,
            tenant_id=tenant,
            shipment_id=shipment,
            event_type=event_type,
            occurred_at=timestamp,
            location=city,
        )
    db.execute("UPDATE shipments SET current_event_id=? WHERE id=?", (base + 503, shipment))
    for line, quantity in ((1, 2), (2, 1)):
        insert(
            db,
            "shipment_items",
            tenant_id=tenant,
            shipment_id=shipment,
            order_id=order,
            line_no=line,
            quantity=quantity,
        )
    return order


def _seed_tenant_purchasing(db: sqlite3.Connection, tenant: int) -> None:
    base = tenant * 1000
    purchase = base + 601
    insert(
        db,
        "purchase_orders",
        id=purchase,
        tenant_id=tenant,
        supplier_id=base + 41,
        warehouse_id=base + 1,
        purchase_no="PO-2026-0001",
        status="received",
        ordered_at="2026-01-01",
        expected_at="2026-01-03",
        received_at="2026-01-02",
    )
    for number, cost in ((1, 400), (2, 650), (3, 1000)):
        product = base + 50 + number
        insert(
            db,
            "purchase_order_items",
            id=base + 700 + number,
            tenant_id=tenant,
            purchase_order_id=purchase,
            product_id=product,
            quantity=20,
            unit_cost_cents=cost,
            received_quantity=20,
        )
        insert(
            db,
            "stock_movements",
            tenant_id=tenant,
            warehouse_id=base + 1,
            product_id=product,
            movement_type="receipt",
            delta=20,
            occurred_at="2026-01-02 12:00:00",
            purchase_item_id=base + 700 + number,
        )
        insert(
            db,
            "stock_movements",
            tenant_id=tenant,
            warehouse_id=base + 2,
            product_id=product,
            movement_type="adjustment",
            delta=5,
            occurred_at="2026-01-02 12:00:00",
        )
    for line, quantity in ((1, 2), (2, 1)):
        insert(
            db,
            "stock_movements",
            tenant_id=tenant,
            warehouse_id=base + 1,
            product_id=base + 50 + line,
            movement_type="sale",
            delta=-quantity,
            occurred_at="2026-01-04 10:00:00",
            order_item_id=base + 200 + line,
        )


def _seed_tenant_return(db: sqlite3.Connection, tenant: int, order: int) -> None:
    base = tenant * 1000
    insert(
        db,
        "returns",
        id=base + 901,
        tenant_id=tenant,
        order_id=order,
        return_no="RMA-0001",
        status="refunded",
        requested_at="2026-01-07 10:00:00",
        received_at="2026-01-08 10:00:00",
        reason="七天无理由退货",
    )
    insert(
        db,
        "return_items",
        tenant_id=tenant,
        return_id=base + 901,
        order_id=order,
        line_no=1,
        quantity=1,
        refund_cents=900,
    )
    insert(
        db,
        "refunds",
        id=base + 951,
        tenant_id=tenant,
        return_id=base + 901,
        payment_id=base + 301,
        refund_no="REF-0001",
        amount_cents=900,
        refunded_at="2026-01-08 12:00:00",
    )
    insert(
        db,
        "stock_movements",
        tenant_id=tenant,
        warehouse_id=base + 1,
        product_id=base + 51,
        movement_type="return",
        delta=1,
        occurred_at="2026-01-08 10:00:00",
        order_item_id=base + 201,
    )
    for event in ("order.created", "order.refunded"):
        insert(
            db,
            "audit_events",
            event_type=event,
            customer_email=f"customer1@tenant{tenant}.example.test",
            message=f"{event}: T{tenant}/ORD-2026-0001",
        )


def seed_database(db: sqlite3.Connection) -> None:
    """显式固定 ID、时间和业务链；可空循环先插入 NULL，再回填指针。"""
    for number, name in enumerate(["轻量", "办公", "热销"], 1):
        insert(db, "tags", id=number, name=name)
    for tenant, city in ((1, "杭州"), (2, "成都")):
        _seed_tenant_people(db, tenant, city)
        _seed_tenant_catalog(db, tenant)
        order = _seed_tenant_order(db, tenant, city)
        _seed_tenant_purchasing(db, tenant)
        _seed_tenant_return(db, tenant, order)


def build_database(target: Path) -> Path:
    """先在同目录临时文件构建，通过验证后以排他方式发布。"""
    target = target.expanduser().absolute()
    if target.exists():
        raise FileExistsError(f"目标已存在，未覆盖：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".building", dir=target.parent)
    os.close(descriptor)
    temporary = Path(filename)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
            seed_database(db)
            db.commit()
        if __package__:
            from .validate import validate_database
        else:
            from validate import validate_database

        report = validate_database(temporary)
        if not report["ok"]:
            raise ValueError(f"夹具验证失败：{report}")
        # hard-link publication cannot replace an existing target, even if a
        # competing process creates one after the first existence check.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def available_target(target: Path) -> Path:
    """选择未占用的新名称，不覆盖已有文件。"""
    candidate = target
    suffix = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
        suffix += 1
    return candidate


def main() -> None:
    """从命令行创建一份新的夹具。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET, help="目标存在时默认拒绝覆盖")
    parser.add_argument("--next-available", action="store_true", help="目标存在时另取 _2、_3 等新文件名")
    args = parser.parse_args()
    path = build_database(available_target(args.output) if args.next_available else args.output)
    print(json.dumps({"database": str(path), "tables": 24}, ensure_ascii=False))


if __name__ == "__main__":
    main()
