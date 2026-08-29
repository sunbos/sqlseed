"""Create a feature-complete test SQLite DB for sqlseed-ui validation.

Schema deliberately exercises every core code path:
- AUTOINCREMENT PK, implicit INTEGER PK
- UNIQUE (column + composite PK treated as composite unique)
- Single-column CHECK (enum IN, numeric range, LENGTH)
- Cross-column CHECK (shipped_at >= created_at)
- FK: normal, self-referencing, composite PK with two FKs
- Nullable columns, DEFAULT values, DATE/DATETIME/REAL/TEXT types
- phone LENGTH=11 CHECK → drives zh_CN locale inference (auto_heal._infer_locale)

Seed rows satisfy ALL constraints so enrichment has real distributions.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path("/Users/sunbo/Desktop/sqlseed_demo.db")

SCHEMA = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT,
        phone TEXT CHECK (phone IS NULL OR LENGTH(phone) = 11),
        status TEXT NOT NULL CHECK (status IN ('active','inactive','pending')),
        balance REAL NOT NULL DEFAULT 0 CHECK (balance >= 0),
        signup_date DATE,
        bio TEXT
    )
    """,
    """
    CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        category TEXT CHECK (category IN ('electronics','clothing','food','books')),
        price REAL NOT NULL CHECK (price > 0 AND price <= 100000),
        stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
        is_active BOOLEAN NOT NULL DEFAULT 1,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        order_no TEXT UNIQUE,
        status TEXT CHECK (status IN ('paid','shipped','completed','cancelled')),
        amount REAL CHECK (amount >= 0 AND amount <= 100000),
        created_at DATETIME NOT NULL,
        shipped_at DATETIME,
        CHECK (shipped_at IS NULL OR shipped_at >= created_at)
    )
    """,
    """
    CREATE TABLE order_items (
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL CHECK (quantity >= 1),
        unit_price REAL NOT NULL CHECK (unit_price > 0),
        PRIMARY KEY (order_id, product_id)
    )
    """,
    """
    CREATE TABLE employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        manager_id INTEGER REFERENCES employees(id),
        title TEXT CHECK (title IN ('engineer','manager','director','vp')),
        salary REAL CHECK (salary >= 0),
        hired_at DATE
    )
    """,
]

SEED = {
    "users": [
        ("alice_w", "alice@example.com", "13800138001", "active", 100.50, "2024-01-15", "team lead"),
        ("bob_z", "bob@example.com", "13912345678", "inactive", 0.0, "2024-02-20", None),
        ("carol_l", "carol@example.com", "13666667777", "pending", 42.25, "2024-03-05", "new user"),
        ("dave_q", "dave@example.com", None, "active", 999.99, "2024-04-10", None),
        ("eve_m", "eve@example.com", "13123456789", "active", 12.00, "2024-05-30", "vip"),
    ],
    "products": [
        ("SKU-0001", "Laptop Pro 14", "electronics", 12999.00, 25, 1, "2024-01-01 09:00:00"),
        ("SKU-0002", "T-Shirt Basic", "clothing", 49.90, 500, 1, "2024-01-05 10:30:00"),
        ("SKU-0003", "Coffee Beans 1kg", "food", 128.00, 80, 1, "2024-02-01 08:00:00"),
        ("SKU-0004", "Python Handbook", "books", 89.00, 120, 1, "2024-02-15 14:00:00"),
        ("SKU-0005", "Wireless Mouse", "electronics", 199.00, 0, 0, "2024-03-01 11:00:00"),
        ("SKU-0006", "Jeans Slim", "clothing", 329.00, 60, 1, "2024-03-20 16:20:00"),
        ("SKU-0007", "Green Tea 500g", "food", 68.50, 200, 1, "2024-04-01 09:30:00"),
        ("SKU-0008", "SQL Cookbook", "books", 79.00, 45, 1, "2024-04-10 13:45:00"),
    ],
    "orders": [
        (1, "ORD-2024-001", "paid", 13147.90, "2024-06-01 10:00:00", None),
        (2, "ORD-2024-002", "shipped", 49.90, "2024-06-02 11:00:00", "2024-06-03 09:00:00"),
        (3, "ORD-2024-003", "completed", 196.50, "2024-06-05 14:00:00", "2024-06-06 10:00:00"),
        (1, "ORD-2024-004", "cancelled", 0.0, "2024-06-10 09:00:00", None),
        (4, "ORD-2024-005", "paid", 89.00, "2024-06-15 16:00:00", None),
        (5, "ORD-2024-006", "shipped", 329.00, "2024-06-20 12:00:00", "2024-06-21 08:30:00"),
    ],
    "order_items": [
        (1, 1, 1, 12999.00), (1, 2, 3, 49.90),
        (2, 2, 1, 49.90),
        (3, 7, 2, 68.50), (3, 8, 1, 128.00),
        (4, 4, 1, 89.00),
        (5, 4, 1, 89.00),
        (6, 6, 1, 329.00),
        (6, 5, 0, 0.01),  # placeholder replaced below
        (6, 2, 5, 19.90),
    ],
    "employees": [
        ("Grace Chen", None, "vp", 250000.00, "2015-03-01"),
        ("Li Wei", 1, "director", 180000.00, "2017-06-15"),
        ("Zhang San", 2, "manager", 120000.00, "2019-01-10"),
        ("Wang Fang", 2, "manager", 115000.00, "2019-08-20"),
        ("Liu Yang", 3, "engineer", 85000.00, "2021-04-05"),
        ("Zhao Min", 4, "engineer", 82000.00, "2022-02-14"),
    ],
}


def build() -> sqlite3.Connection:
    DB.unlink(missing_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in SCHEMA:
        conn.execute(ddl)
    conn.executemany("INSERT INTO users (username,email,phone,status,balance,signup_date,bio) VALUES (?,?,?,?,?,?,?)", SEED["users"])
    conn.executemany("INSERT INTO products (sku,name,category,price,stock,is_active,created_at) VALUES (?,?,?,?,?,?,?)", SEED["products"])
    conn.executemany("INSERT INTO orders (user_id,order_no,status,amount,created_at,shipped_at) VALUES (?,?,?,?,?,?)", SEED["orders"])
    # order_items: fix the placeholder row to satisfy CHECK (quantity>=1, price>0)
    items = [row if row[0] != 6 or row[2] != 0 else (6, 5, 2, 99.50) for row in SEED["order_items"]]
    conn.executemany("INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (?,?,?,?)", items)
    conn.executemany("INSERT INTO employees (name,manager_id,title,salary,hired_at) VALUES (?,?,?,?,?)", SEED["employees"])
    conn.commit()
    return conn


def must_fail(conn: sqlite3.Connection, sql: str, params: tuple) -> bool:
    try:
        conn.execute(sql, params)
        conn.rollback()
        return False
    except sqlite3.IntegrityError:
        return True


def validate(conn: sqlite3.Connection) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    results.append(("integrity_check", integrity == "ok", f"result={integrity}"))

    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    results.append(("foreign_key_check (seed)", len(fk) == 0, f"violations={len(fk)}"))

    checks = [
        ("CHECK enum rejected", "INSERT INTO users (username,email,status) VALUES ('x','x@x.com','bogus')", ()),
        ("CHECK range rejected (price<=0)", "INSERT INTO products (sku,name,price) VALUES ('S-x','x',-1)", ()),
        ("CHECK range rejected (price>max)", "INSERT INTO products (sku,name,price) VALUES ('S-y','y',100001)", ()),
        ("CHECK length rejected (phone!=11)", "INSERT INTO users (username,phone,status) VALUES ('z','12345','active')", ()),
        ("UNIQUE rejected (username)", "INSERT INTO users (username,status) VALUES ('alice_w','active')", ()),
        ("UNIQUE rejected (sku)", "INSERT INTO products (sku,name,price) VALUES ('SKU-0001','dup',1)", ()),
        ("FK rejected (bad user_id)", "INSERT INTO orders (user_id,created_at) VALUES (99999,'2024-01-01 00:00:00')", ()),
        ("FK rejected (self-ref bad)", "UPDATE employees SET manager_id = 999 WHERE id = 5", ()),
        ("Cross-column CHECK rejected", "INSERT INTO orders (user_id,created_at,shipped_at) VALUES (1,'2024-06-01 10:00:00','2024-05-01 10:00:00')", ()),
        ("Composite PK rejected (dup)", "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (1,1,2,9.9)", ()),
        ("CHECK quantity rejected", "INSERT INTO order_items (order_id,product_id,quantity,unit_price) VALUES (1,3,0,9.9)", ()),
    ]
    for label, sql, params in checks:
        results.append((label, must_fail(conn, sql, params), "rejected as expected" if True else ""))

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("users", "products", "orders", "order_items", "employees")}
    results.append(("seed row counts", counts == {"users": 5, "products": 8, "orders": 6, "order_items": 10, "employees": 6}, str(counts)))
    return results


def main() -> int:
    conn = build()
    results = validate(conn)
    conn.close()
    print(f"DB: {DB} ({DB.stat().st_size} bytes)")
    failed = 0
    for label, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {label:36s} {detail}")
    print(f"\n{'ALL CHECKS PASSED' if failed == 0 else f'{failed} CHECKS FAILED'} — {DB}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
