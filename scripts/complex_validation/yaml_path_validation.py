"""YAML config-path validation: derive_from expressions + cross-table associations.

Builds a small shop schema, fills it via sqlseed.fill_from_config with a
hand-written YAML, then independently verifies:
  Y1 derive_from  : order_items.line_total == round(quantity * unit_price, 2)
  Y2 association  : products.region_code values all come from the users pool
  Y3 FK integrity : PRAGMA foreign_key_check is clean
  Y4 YAML clamps  : CHECK constraints satisfied (quantity > 0, price > 0)

Exit code 0 iff all checks pass.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent / "dbs"
DB_PATH = DB_DIR / "shop_yaml.db"
YAML_PATH = DB_DIR / "shop.yaml"

DDL = [
    """CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        email TEXT NOT NULL,
        region_code TEXT NOT NULL
    )""",
    """CREATE TABLE products (
        product_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        price NUMERIC NOT NULL CHECK (price > 0),
        region_code TEXT NOT NULL
    )""",
    """CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(user_id),
        created_at DATETIME NOT NULL
    )""",
    """CREATE TABLE order_items (
        item_id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(order_id),
        product_id INTEGER NOT NULL REFERENCES products(product_id),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        unit_price NUMERIC NOT NULL CHECK (unit_price > 0),
        line_total NUMERIC NOT NULL
    )""",
]

YAML = f"""\
db_path: {DB_PATH}
seed: 42
tables:
  - name: users
    count: 50
    columns:
      - name: email
        generator: email
      - name: region_code
        generator: choice
        params:
          choices: ["CN-East", "CN-North", "CN-South", "EU-West", "US-East"]
  - name: products
    count: 30
    columns:
      - name: name
        generator: word
      - name: price
        generator: float
        params:
          min_value: 1.0
          max_value: 500.0
  - name: orders
    count: 100
  - name: order_items
    count: 200
    columns:
      - name: quantity
        generator: integer
        params:
          min_value: 1
          max_value: 5
      - name: unit_price
        generator: float
        params:
          min_value: 1.0
          max_value: 500.0
      - name: line_total
        derive_from: [quantity, unit_price]
        expression: "round(row['quantity'] * row['unit_price'], 2)"
associations:
  - column_name: region_code
    source_table: users
    target_tables: [products]
"""


def main() -> int:
    import sqlseed

    DB_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    for stmt in DDL:
        con.execute(stmt)
    con.commit()
    con.close()
    YAML_PATH.write_text(YAML, encoding="utf-8")

    results = sqlseed.fill_from_config(str(YAML_PATH))
    fill_ok = all(len(r.errors) == 0 for r in results)
    print(f"fill_from_config: {len(results)} tables, errors={sum(len(r.errors) for r in results)}")

    con = sqlite3.connect(DB_PATH)
    checks: list[tuple[str, bool, str]] = []

    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ["users", "products", "orders", "order_items"]}
    checks.append(("Y0-rows+fill", fill_ok and counts == {"users": 50, "products": 30, "orders": 100, "order_items": 200}, str(counts)))

    bad = con.execute(
        "SELECT COUNT(*) FROM order_items WHERE ABS(line_total - round(quantity * unit_price, 2)) > 1e-9"
    ).fetchone()[0]
    checks.append(("Y1-derive_from", bad == 0, f"line_total mismatches={bad}"))

    orphans_pool = con.execute(
        "SELECT COUNT(*) FROM products WHERE region_code NOT IN (SELECT DISTINCT region_code FROM users)"
    ).fetchone()[0]
    checks.append(("Y2-association", orphans_pool == 0, f"region_code outside shared pool={orphans_pool}"))

    orphans = con.execute("PRAGMA foreign_key_check").fetchall()
    checks.append(("Y3-fk", len(orphans) == 0, f"orphans={len(orphans)}"))

    bad_ck = con.execute("SELECT COUNT(*) FROM order_items WHERE NOT (quantity > 0 AND unit_price > 0)").fetchone()[0]
    bad_ck += con.execute("SELECT COUNT(*) FROM products WHERE NOT (price > 0)").fetchone()[0]
    checks.append(("Y4-check", bad_ck == 0, f"CHECK violations={bad_ck}"))

    con.close()
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<16} {detail}")
    all_ok = all(ok for _, ok, _ in checks)
    print(f"YAML path: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
