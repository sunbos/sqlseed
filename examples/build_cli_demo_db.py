"""创建 CLI 演示用空数据库（仅 schema，无数据）。

业务场景：小型电商平台，5 张表，覆盖 FK / 自引用 / 枚举 / 跨列 CHECK / 派生列。
用法:
    .venv/bin/python examples/build_cli_demo_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "cli_demo.db"

SCHEMA_SQL = """
-- 1. 客户
CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    phone TEXT,
    age INTEGER CHECK (age >= 18 AND age <= 120),
    vip_level TEXT NOT NULL DEFAULT 'normal' CHECK (vip_level IN ('normal','silver','gold','platinum')),
    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. 商品分类（自引用树）
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES categories(id),
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- 3. 商品
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price REAL NOT NULL CHECK (price > 0),
    cost REAL NOT NULL CHECK (cost >= 0 AND cost < price),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','discontinued'))
);

-- 4. 订单（跨列 CHECK + 派生列候选）
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','shipped','completed','cancelled')),
    subtotal REAL NOT NULL CHECK (subtotal >= 0),
    discount REAL NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount <= subtotal),
    total REAL NOT NULL CHECK (total = subtotal - discount),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at TEXT,
    CHECK (paid_at IS NULL OR status != 'pending')
);

-- 5. 订单明细（复合 UNIQUE + 派生列候选）
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    line_total REAL NOT NULL CHECK (line_total = unit_price * quantity),
    UNIQUE(order_id, product_id)
);
"""


def main() -> None:
    """重建 CLI 演示用空库（幂等：已存在则先删除）。"""
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    print(f"已创建空库: {DB_PATH}")


if __name__ == "__main__":
    main()
