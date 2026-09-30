"""Repeatable business schema for real SQLite/HTTP/relationship-graph acceptance.

Run this file with the project Python to create an isolated temporary database
and export the actual workbench schema response. It never opens a user database.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sqlseed_web import workbench
from sqlseed_web.state import UIState

DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE tenants (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE departments (
    id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    parent_id INTEGER REFERENCES departments(id), manager_id INTEGER REFERENCES employees(id), name TEXT);
CREATE TABLE employees (
    id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    department_id INTEGER REFERENCES departments(id), manager_id INTEGER REFERENCES employees(id), full_name TEXT);
CREATE TABLE addresses (
    id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id), city TEXT, street TEXT);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY, billing_address_id INTEGER REFERENCES addresses(id),
    shipping_address_id INTEGER REFERENCES addresses(id), referred_by INTEGER REFERENCES customers(id), name TEXT);
CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES employees(id), name TEXT);
CREATE TABLE warehouses (
    id INTEGER PRIMARY KEY, address_id INTEGER REFERENCES addresses(id),
    manager_id INTEGER REFERENCES employees(id), name TEXT);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES categories(id), name TEXT);
CREATE TABLE products (
    id INTEGER PRIMARY KEY, category_id INTEGER REFERENCES categories(id),
    supplier_id INTEGER REFERENCES suppliers(id), name TEXT);
CREATE TABLE product_variants (
    id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), sku TEXT NOT NULL UNIQUE);
CREATE TABLE warehouse_bins (
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), code TEXT NOT NULL, parent_code TEXT,
    PRIMARY KEY (warehouse_id, code),
    FOREIGN KEY (warehouse_id, parent_code) REFERENCES warehouse_bins(warehouse_id, code));
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY, variant_id INTEGER NOT NULL REFERENCES product_variants(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), bin_code TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (warehouse_id, bin_code) REFERENCES warehouse_bins(warehouse_id, code));
CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    requested_by INTEGER REFERENCES employees(id), approved_by INTEGER REFERENCES employees(id), created_at DATETIME);
CREATE TABLE purchase_items (
    id INTEGER PRIMARY KEY, purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    variant_id INTEGER NOT NULL REFERENCES product_variants(id), quantity INTEGER NOT NULL);
CREATE TABLE receipts (
    id INTEGER PRIMARY KEY, purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    received_by INTEGER REFERENCES employees(id), received_at DATETIME);
CREATE TABLE receipt_items (
    id INTEGER PRIMARY KEY, receipt_id INTEGER NOT NULL REFERENCES receipts(id),
    purchase_item_id INTEGER NOT NULL REFERENCES purchase_items(id), inventory_id INTEGER NOT NULL REFERENCES inventory(id));
CREATE TABLE sales_orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
    billing_address_id INTEGER REFERENCES addresses(id), shipping_address_id INTEGER REFERENCES addresses(id),
    owner_id INTEGER REFERENCES employees(id), total NUMERIC NOT NULL DEFAULT 0);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    variant_id INTEGER NOT NULL REFERENCES product_variants(id), quantity INTEGER NOT NULL);
CREATE TABLE payments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id), amount NUMERIC NOT NULL);
CREATE TABLE carriers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id), carrier_id INTEGER REFERENCES carriers(id), tracking_code TEXT);
CREATE TABLE shipment_items (
    id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
    order_item_id INTEGER NOT NULL REFERENCES order_items(id), inventory_id INTEGER NOT NULL REFERENCES inventory(id));
CREATE TABLE returns (
    id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES sales_orders(id), reason TEXT);
CREATE TABLE return_items (
    id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES returns(id),
    order_item_id INTEGER NOT NULL REFERENCES order_items(id), quantity INTEGER NOT NULL);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES returns(id),
    payment_id INTEGER NOT NULL REFERENCES payments(id), amount NUMERIC NOT NULL);
CREATE TABLE stock_movements (
    id INTEGER PRIMARY KEY, inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    shipment_item_id INTEGER REFERENCES shipment_items(id), return_item_id INTEGER REFERENCES return_items(id),
    quantity INTEGER NOT NULL);
INSERT INTO tenants VALUES (1, 'Fixture tenant');
INSERT INTO departments VALUES (1, 1, NULL, NULL, 'Operations');
INSERT INTO employees VALUES (1, 1, 1, NULL, 'Fixture operator');
UPDATE departments SET manager_id=1 WHERE id=1;
INSERT INTO addresses VALUES (1, 1, 'Fixture city', 'Fixture street');
INSERT INTO customers VALUES (1, 1, 1, NULL, 'Fixture customer');
INSERT INTO suppliers VALUES (1, 1, 'Fixture supplier');
INSERT INTO warehouses VALUES (1, 1, 1, 'Fixture warehouse');
INSERT INTO categories VALUES (1, NULL, 'Fixture category');
INSERT INTO products VALUES (1, 1, 1, 'Fixture product');
INSERT INTO product_variants VALUES (1, 1, 'FIXTURE-001');
INSERT INTO warehouse_bins VALUES (1, 'ROOT', NULL), (1, 'A01', 'ROOT');
INSERT INTO inventory VALUES (1, 1, 1, 'A01', 100);
INSERT INTO purchase_orders VALUES (1, 1, 1, 1, 1, '2026-09-01 10:00:00');
INSERT INTO purchase_items VALUES (1, 1, 1, 100);
INSERT INTO receipts VALUES (1, 1, 1, '2026-09-02 10:00:00');
INSERT INTO receipt_items VALUES (1, 1, 1, 1);
INSERT INTO sales_orders VALUES (1, 1, 1, 1, 1, 50);
INSERT INTO order_items VALUES (1, 1, 1, 2);
INSERT INTO payments VALUES (1, 1, 1, 50);
INSERT INTO carriers VALUES (1, 'Fixture carrier');
INSERT INTO shipments VALUES (1, 1, 1, 1, 'FIXTURE-TRACK-001');
INSERT INTO shipment_items VALUES (1, 1, 1, 1);
INSERT INTO returns VALUES (1, 1, 'Fixture return');
INSERT INTO return_items VALUES (1, 1, 1, 1);
INSERT INTO refunds VALUES (1, 1, 1, 25);
INSERT INTO stock_movements VALUES (1, 1, 1, NULL, -2), (2, 1, NULL, 1, 1);
"""

SUGGESTED_TABLES = ["sales_orders", "order_items", "payments", "shipments", "shipment_items"]


def create_database(path: Path) -> None:
    """Create only a new fixture file; never overwrite an existing database."""
    if path.exists():
        raise FileExistsError(path)
    with ExitStack() as cleanup:
        connection = cleanup.enter_context(closing(sqlite3.connect(path)))
        cleanup.enter_context(connection)
        connection.executescript(DDL)
        if violations := connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(f"Fixture has invalid foreign keys: {violations}")


def export_schema(path: Path) -> dict[str, Any]:
    """Exercise the real HTTP schema route with an isolated registry, no server."""
    registry = UIState()
    connection = registry.add_connection(str(path), provider="base", locale="zh_CN")
    app = FastAPI()
    app.include_router(workbench.router)
    try:
        with patch.object(workbench, "state", registry), TestClient(app) as client:
            response = client.get(f"/api/workbench/connections/{connection.conn_id}/schema")
            response.raise_for_status()
            return response.json()
    finally:
        registry.close_connection(connection.conn_id)


def export_checks(path: Path, schema: dict[str, Any], cases: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Read-only plans, including a blocked descendant outside the real SCC."""
    registry = UIState()
    connection = registry.add_connection(str(path), provider="base", locale="zh_CN")
    app = FastAPI()
    app.include_router(workbench.router)
    cases = cases or {
        "fulfillment": SUGGESTED_TABLES,
        "cycles": ["departments", "employees", "suppliers"],
        "composite": ["inventory"],
    }
    results: dict[str, Any] = {}
    try:
        with patch.object(workbench, "state", registry), TestClient(app) as client:
            for name, selected in cases.items():
                response = client.post(
                    "/api/workbench/check",
                    json={
                        "conn_id": connection.conn_id,
                        "schema_hash": schema["schema_hash"],
                        "document": {
                            "provider": "base",
                            "locale": "zh_CN",
                            "tables": [{"name": table, "count": 3, "columns": []} for table in selected],
                        },
                    },
                )
                response.raise_for_status()
                result = response.json()
                results[name] = {
                    "selected": selected,
                    **{key: result[key] for key in ("ok", "issues", "order", "sources")},
                }
        return results
    finally:
        registry.close_connection(connection.conn_id)


def graph_snapshot(schema: dict[str, Any], checks: dict[str, Any]) -> dict[str, Any]:
    """Small API-derived fixture; omit connection identity and generator catalog."""
    return {
        "nodes": schema["nodes"],
        "edges": schema["edges"],
        "tables": [
            {
                "name": table["name"],
                "row_count": table["row_count"],
                "columns": [{"name": column["name"], "type": column["type"]} for column in table["columns"]],
            }
            for table in schema["tables"]
        ],
        "checks": checks,
    }


def main() -> None:
    directory = Path(tempfile.mkdtemp(prefix="sqlseed-complex-graph-"))
    database = directory / "commerce_operations.sqlite3"
    create_database(database)
    schema = export_schema(database)
    output = directory / "schema.json"
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = export_checks(database, schema)
    (directory / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "database": str(database),
                "schema": str(output),
                "tables": len(schema["tables"]),
                "edges": len(schema["edges"]),
                "suggested_tables": SUGGESTED_TABLES,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
