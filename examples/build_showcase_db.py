"""构建复杂 SaaS 电商平台 demo 数据库，用于全面测试 sqlseed 特性覆盖。

覆盖特性清单：
  - 数据类型: INTEGER / TEXT / REAL / NUMERIC / BLOB / BOOLEAN / DATE / DATETIME / UUID / JSON
  - 约束: AUTOINCREMENT PK / DEFAULT / NOT NULL / UNIQUE(单列+复合) / CHECK(范围+IN+LIKE+跨列比较+条件NULL+等式派生)
  - 关联: 单列 FK / 自引用 FK / 复合 FK / 多对多 / SharedPool 隐式关联
  - 派生: derive_from + expression (total_amount / total_price)
  - 配置混合: 零配置智能推断 + 显式列配置

用法:
    .venv/bin/python examples/build_showcase_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlseed import connect

DB_PATH = Path("/tmp/sqlseed_showcase.db")

# ---------------------------------------------------------------------------
# Schema: SaaS 电商平台（15 张表，按 FK 拓扑顺序排列）
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
-- 1. 组织（多租户根表）
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free','pro','enterprise')),
    max_users INTEGER NOT NULL DEFAULT 10 CHECK (max_users >= 1 AND max_users <= 10000),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. 部门（自引用，树形结构）
CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    parent_id INTEGER REFERENCES departments(id),
    name TEXT NOT NULL,
    budget REAL NOT NULL DEFAULT 0 CHECK (budget >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (parent_id IS NULL OR parent_id != id)
);

-- 3. 用户
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    dept_id INTEGER REFERENCES departments(id),
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    password_hash TEXT NOT NULL,
    age INTEGER CHECK (age >= 18 AND age <= 120),
    gender TEXT CHECK (gender IN ('male','female','other')),
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member','viewer')),
    salary REAL CHECK (salary >= 0),
    avatar_url TEXT,
    bio TEXT,
    last_login_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

-- 4. 商品分类（自引用，树形结构）
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES categories(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    is_leaf INTEGER NOT NULL DEFAULT 1 CHECK (is_leaf IN (0,1))
);

-- 5. 商品
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL CHECK (price > 0),
    cost REAL NOT NULL CHECK (cost >= 0 AND cost < price),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    weight REAL CHECK (weight > 0),
    barcode TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','discontinued')),
    rating REAL NOT NULL DEFAULT 0 CHECK (rating >= 0 AND rating <= 5),
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

-- 6. 优惠券
CREATE TABLE coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    discount_type TEXT NOT NULL CHECK (discount_type IN ('percentage','fixed')),
    discount_value REAL NOT NULL CHECK (discount_value > 0),
    min_order_amount REAL NOT NULL DEFAULT 0 CHECK (min_order_amount >= 0),
    max_discount REAL,
    usage_limit INTEGER NOT NULL DEFAULT 1 CHECK (usage_limit >= 1),
    used_count INTEGER NOT NULL DEFAULT 0 CHECK (used_count >= 0 AND used_count <= usage_limit),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    CHECK (ends_at > starts_at),
    CHECK (discount_type = 'fixed' OR discount_value <= 1)
);

-- 7. 订单（核心表，多重跨列约束 + 派生列）
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    coupon_id INTEGER REFERENCES coupons(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','paid','shipped','delivered','cancelled','refunded')),
    subtotal REAL NOT NULL CHECK (subtotal >= 0),
    discount_amount REAL NOT NULL DEFAULT 0 CHECK (discount_amount >= 0 AND discount_amount <= subtotal),
    shipping_fee REAL NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
    total_amount REAL NOT NULL CHECK (total_amount = subtotal - discount_amount + shipping_fee),
    refunded_amount REAL NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0 AND refunded_amount <= total_amount),
    shipping_address TEXT NOT NULL,
    billing_address TEXT,
    notes TEXT,
    placed_at TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at TEXT,
    shipped_at TEXT,
    delivered_at TEXT,
    cancelled_at TEXT,
    CHECK (paid_at IS NULL OR status IN ('paid','shipped','delivered','cancelled','refunded')),
    CHECK (cancelled_at IS NULL OR status = 'cancelled'),
    CHECK (shipped_at IS NULL OR paid_at IS NOT NULL),
    CHECK (delivered_at IS NULL OR shipped_at IS NOT NULL),
    CHECK (billing_address IS NULL OR billing_address != shipping_address)
);

-- 8. 订单明细（复合 UNIQUE + 派生列）
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 1 AND quantity <= 100),
    unit_price REAL NOT NULL CHECK (unit_price > 0),
    total_price REAL NOT NULL CHECK (total_price = unit_price * quantity),
    UNIQUE(order_id, product_id)
);

-- 9. 支付（条件 NULL 约束）
CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    payment_no TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL CHECK (method IN ('credit_card','alipay','wechat','paypal','bank_transfer')),
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL DEFAULT 'CNY' CHECK (currency IN ('CNY','USD','EUR','JPY')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','success','failed','refunded')),
    transaction_id TEXT,
    paid_at TEXT,
    fail_reason TEXT,
    CHECK (status != 'success' OR paid_at IS NOT NULL),
    CHECK (status != 'failed' OR fail_reason IS NOT NULL)
);

-- 10. 物流（时间顺序约束）
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    tracking_no TEXT NOT NULL UNIQUE,
    carrier TEXT NOT NULL CHECK (carrier IN ('sf','yt','zd','jd','ems')),
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','picked','in_transit','delivered','returned')),
    weight REAL CHECK (weight > 0),
    shipped_at TEXT,
    delivered_at TEXT,
    CHECK (delivered_at IS NULL OR shipped_at IS NOT NULL),
    CHECK (status != 'delivered' OR delivered_at IS NOT NULL)
);

-- 11. 评价（条件约束 + JSON）
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    title TEXT,
    content TEXT,
    images TEXT,
    is_anonymous INTEGER NOT NULL DEFAULT 0 CHECK (is_anonymous IN (0,1)),
    reply TEXT,
    replied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (rating >= 4 OR content IS NOT NULL)
);

-- 12. 审计日志（UUID 主键 + JSON）
CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL CHECK (action IN ('create','update','delete','login','logout','export')),
    resource_type TEXT NOT NULL,
    resource_id INTEGER,
    details TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 13. 标签
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#000000',
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0)
);

-- 14. 商品-标签（多对多，复合主键）
CREATE TABLE product_tags (
    product_id INTEGER NOT NULL REFERENCES products(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (product_id, tag_id)
);

-- 15. 团队成员（复合 UNIQUE）
CREATE TABLE team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner','admin','member')),
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(org_id, user_id)
);
"""

# ---------------------------------------------------------------------------
# 各表填充配置：count + 对复杂列的显式配置
# 派生列用 derive_from + expression；其余交给 sqlseed 智能推断
# ---------------------------------------------------------------------------
TABLE_PLANS: list[dict] = [
    # 1. 组织：枚举 plan + 范围 max_users + 业务编码
    {
        "table": "organizations",
        "count": 8,
        "columns": {
            "code": {"generator": "pattern", "params": {"pattern": "ORG-\\d{4}"}},
            "plan": {"generator": "choice", "params": {"choices": ["free", "pro", "enterprise"]}},
            "max_users": {"generator": "integer", "params": {"min_value": 1, "max_value": 10000}},
        },
    },
    # 2. 部门：自引用 + budget 范围
    {
        "table": "departments",
        "count": 25,
        "columns": {
            "budget": {"generator": "float", "params": {"min_value": 0, "max_value": 1000000}},
        },
    },
    # 3. 用户：age 范围 + gender/role 枚举 + 手机号 pattern
    {
        "table": "users",
        "count": 200,
        "columns": {
            "age": {"generator": "integer", "params": {"min_value": 18, "max_value": 120}},
            "gender": {"generator": "choice", "params": {"choices": ["male", "female", "other"]}, "null_ratio": 0.1},
            "role": {"generator": "choice", "params": {"choices": ["admin", "member", "viewer"]}},
            "salary": {"generator": "float", "params": {"min_value": 3000, "max_value": 80000}},
            "phone": {"generator": "pattern", "params": {"pattern": "1[3-9]\\d{9}"}},
        },
    },
    # 4. 分类：slug pattern
    {
        "table": "categories",
        "count": 30,
        "columns": {
            "slug": {"generator": "pattern", "params": {"pattern": "[a-z]{4,10}"}},
            "sort_order": {"generator": "integer", "params": {"min_value": 0, "max_value": 999}},
        },
    },
    # 5. 商品：cost 派生(<price) + status 枚举 + rating 范围 + sku/barcode pattern
    {
        "table": "products",
        "count": 500,
        "columns": {
            "sku": {"generator": "pattern", "params": {"pattern": "SKU-\\d{6}"}},
            "price": {"generator": "float", "params": {"min_value": 1, "max_value": 10000}},
            "cost": {"derive_from": ["price"], "expression": "row['price'] * 0.5"},
            "stock": {"generator": "integer", "params": {"min_value": 0, "max_value": 9999}},
            "weight": {"generator": "float", "params": {"min_value": 0.1, "max_value": 100}},
            "barcode": {"generator": "pattern", "params": {"pattern": "\\d{13}"}, "null_ratio": 0.2},
            "status": {"generator": "choice", "params": {"choices": ["active", "inactive", "discontinued"]}},
            "rating": {"generator": "float", "params": {"min_value": 0, "max_value": 5, "precision": 1}},
        },
    },
    # 6. 优惠券：枚举 + 跨列时间顺序(starts<ends) + discount_value 范围
    {
        "table": "coupons",
        "count": 40,
        "columns": {
            "code": {"generator": "pattern", "params": {"pattern": "SAVE-\\d{4}"}},
            "discount_type": {"generator": "choice", "params": {"choices": ["percentage", "fixed"]}},
            "discount_value": {"generator": "float", "params": {"min_value": 0.01, "max_value": 1.0}},
            "min_order_amount": {"generator": "float", "params": {"min_value": 0, "max_value": 500}},
            "max_discount": {"generator": "float", "params": {"min_value": 0, "max_value": 100}, "null_ratio": 0.5},
            "usage_limit": {"generator": "integer", "params": {"min_value": 1, "max_value": 1000}},
            "used_count": {"generator": "integer", "params": {"min_value": 0, "max_value": 0}},
            "starts_at": {"generator": "date", "params": {"start_year": 2023, "end_year": 2024}},
            "ends_at": {"generator": "date", "params": {"start_year": 2025, "end_year": 2026}},
        },
    },
    # 7. 订单：派生 total_amount + discount 派生(<subtotal) + status=pending(时间戳全NULL)
    {
        "table": "orders",
        "count": 800,
        "columns": {
            "order_no": {"generator": "pattern", "params": {"pattern": "ORD-\\d{8}"}},
            "status": {"generator": "choice", "params": {"choices": ["pending"]}},
            "subtotal": {"generator": "float", "params": {"min_value": 10, "max_value": 10000}},
            "discount_amount": {"derive_from": ["subtotal"], "expression": "row['subtotal'] * 0.1"},
            "shipping_fee": {"generator": "float", "params": {"min_value": 0, "max_value": 30}},
            "total_amount": {
                "derive_from": ["subtotal", "discount_amount", "shipping_fee"],
                "expression": "row['subtotal'] - row['discount_amount'] + row['shipping_fee']",
            },
            "refunded_amount": {"generator": "integer", "params": {"min_value": 0, "max_value": 0}},
            "shipping_address": {"generator": "address"},
            "billing_address": {"generator": "address", "null_ratio": 0.4},
            "notes": {"generator": "sentence", "null_ratio": 0.7},
            "paid_at": {"generator": "datetime", "null_ratio": 1.0},
            "shipped_at": {"generator": "datetime", "null_ratio": 1.0},
            "delivered_at": {"generator": "datetime", "null_ratio": 1.0},
            "cancelled_at": {"generator": "datetime", "null_ratio": 1.0},
        },
    },
    # 8. 订单明细：派生 total_price + 复合 UNIQUE(order_id, product_id)
    {
        "table": "order_items",
        "count": 2000,
        "columns": {
            "quantity": {"generator": "integer", "params": {"min_value": 1, "max_value": 50}},
            "unit_price": {"generator": "float", "params": {"min_value": 1, "max_value": 2000}},
            "total_price": {
                "derive_from": ["unit_price", "quantity"],
                "expression": "row['unit_price'] * row['quantity']",
            },
        },
    },
    # 9. 支付：枚举 + status=pending(时间戳/原因全NULL)
    {
        "table": "payments",
        "count": 900,
        "columns": {
            "payment_no": {"generator": "pattern", "params": {"pattern": "PAY-\\d{8}"}},
            "method": {
                "generator": "choice",
                "params": {"choices": ["credit_card", "alipay", "wechat", "paypal", "bank_transfer"]},
            },
            "currency": {"generator": "choice", "params": {"choices": ["CNY", "USD", "EUR", "JPY"]}},
            "status": {"generator": "choice", "params": {"choices": ["pending"]}},
            "amount": {"generator": "float", "params": {"min_value": 1, "max_value": 10000}},
            "transaction_id": {"generator": "uuid", "null_ratio": 0.2},
            "paid_at": {"generator": "datetime", "null_ratio": 1.0},
            "fail_reason": {"generator": "sentence", "null_ratio": 1.0},
        },
    },
    # 10. 物流：枚举 + status=created(时间戳全NULL)
    {
        "table": "shipments",
        "count": 700,
        "columns": {
            "tracking_no": {"generator": "pattern", "params": {"pattern": "SF\\d{12}"}},
            "carrier": {"generator": "choice", "params": {"choices": ["sf", "yt", "zd", "jd", "ems"]}},
            "status": {"generator": "choice", "params": {"choices": ["created"]}},
            "weight": {"generator": "float", "params": {"min_value": 0.1, "max_value": 50}},
            "shipped_at": {"generator": "datetime", "null_ratio": 1.0},
            "delivered_at": {"generator": "datetime", "null_ratio": 1.0},
        },
    },
    # 11. 评价：rating 枚举 + content 始终非空(满足 rating<4→content NOT NULL)
    {
        "table": "reviews",
        "count": 600,
        "columns": {
            "rating": {"generator": "choice", "params": {"choices": [1, 2, 3, 4, 5]}},
            "title": {"generator": "sentence", "null_ratio": 0.3},
            "content": {"generator": "text"},
            "images": {"generator": "uuid", "null_ratio": 0.6},
            "reply": {"generator": "sentence", "null_ratio": 0.7},
            "replied_at": {"generator": "datetime", "null_ratio": 0.7},
        },
    },
    # 12. 审计日志：UUID 主键 + action 枚举
    {
        "table": "audit_logs",
        "count": 1500,
        "columns": {
            "id": {"generator": "uuid"},
            "action": {
                "generator": "choice",
                "params": {"choices": ["create", "update", "delete", "login", "logout", "export"]},
            },
            "details": {"generator": "uuid", "null_ratio": 0.4},
            "ip_address": {"generator": "ipv4"},
            "user_agent": {"generator": "text", "null_ratio": 0.1},
            "resource_id": {"generator": "integer", "params": {"min_value": 1, "max_value": 10000}, "null_ratio": 0.2},
        },
    },
    {
        "table": "tags",
        "count": 60,
        "columns": {
            "color": {"generator": "pattern", "params": {"pattern": "#[0-9a-f]{6}"}},
        },
    },
    # 14. 商品-标签：复合主键(product_id, tag_id)
    {"table": "product_tags", "count": 200},
    # 15. 团队成员：role 枚举 + 复合 UNIQUE(org_id, user_id)
    {
        "table": "team_members",
        "count": 150,
        "columns": {
            "role": {"generator": "choice", "params": {"choices": ["owner", "admin", "member"]}},
        },
    },
]


def build_schema(db_path: Path) -> None:
    """创建数据库并执行 schema。"""
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    print(f"[schema] 已创建 {db_path}")


def fill_data(db_path: Path) -> None:
    """按拓扑顺序填充各表。"""
    with connect(str(db_path), provider="mimesis", locale="en") as orch:
        for plan in TABLE_PLANS:
            table = plan["table"]
            count = plan["count"]
            columns = plan.get("columns")
            try:
                result = orch.fill_table(table_name=table, count=count, columns=columns, seed=42)
                err_n = len(result.errors) if result.errors else 0
                print(
                    f"[fill] {table:<16} → {result.count} 行 (err={err_n}) "
                    f"{result.elapsed:.2f}s {result.rows_per_second:.0f} rows/s"
                )
                if result.errors:
                    for e in result.errors[:3]:
                        print(f"         ! {e}")
            except Exception as exc:
                print(f"[fill] {table:<16} → 失败: {type(exc).__name__}: {exc}")


def verify(db_path: Path) -> None:
    """验证生成数据的合理性：行数/约束/FK完整性/派生列/枚举/范围。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    print("\n" + "=" * 70)
    print("数据合理性验证报告")
    print("=" * 70)

    # ---- 1. 行数统计 ----
    print("\n[1] 行数统计")
    tables = [
        "organizations",
        "departments",
        "users",
        "categories",
        "products",
        "coupons",
        "orders",
        "order_items",
        "payments",
        "shipments",
        "reviews",
        "audit_logs",
        "tags",
        "product_tags",
        "team_members",
    ]
    total = 0
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        total += n
        print(f"    {t:<16} {n:>6}")
    print(f"    {'TOTAL':<16} {total:>6}")

    # ---- 2. FK 完整性 ----
    print("\n[2] 外键完整性（PRAGMA foreign_key_check）")
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        for v in fk_violations[:10]:
            print(f"    违反: 表={v[0]} rowid={v[1]} 父表={v[2]} fkid={v[3]}")
        print(f"    共 {len(fk_violations)} 处违反")
    else:
        print("    ✅ 无外键违反")

    # ---- 3. 派生列正确性 ----
    print("\n[3] 派生列正确性")
    # orders.total_amount = subtotal - discount_amount + shipping_fee
    bad_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE ABS(total_amount - (subtotal - discount_amount + shipping_fee)) > 0.001"
    ).fetchone()[0]
    print(f"    orders.total_amount 计算错误: {bad_orders} 行")
    # order_items.total_price = unit_price * quantity
    bad_items = conn.execute(
        "SELECT COUNT(*) FROM order_items WHERE ABS(total_price - unit_price * quantity) > 0.001"
    ).fetchone()[0]
    print(f"    order_items.total_price 计算错误: {bad_items} 行")

    # ---- 4. 跨列约束抽查 ----
    print("\n[4] 跨列约束抽查")
    checks = [
        ("products.cost < price", "SELECT COUNT(*) FROM products WHERE cost >= price"),
        ("orders.discount_amount <= subtotal", "SELECT COUNT(*) FROM orders WHERE discount_amount > subtotal"),
        ("orders.refunded_amount <= total_amount", "SELECT COUNT(*) FROM orders WHERE refunded_amount > total_amount"),
        ("coupons.ends_at > starts_at", "SELECT COUNT(*) FROM coupons WHERE ends_at <= starts_at"),
        ("departments.parent_id != id", "SELECT COUNT(*) FROM departments WHERE parent_id = id"),
    ]
    for name, sql in checks:
        n = conn.execute(sql).fetchone()[0]
        print(f"    {name:<40} 违反: {n} 行")

    # ---- 5. 条件 NULL 约束抽查 ----
    print("\n[5] 条件 NULL 约束抽查")
    cond_checks = [
        (
            "orders.cancelled_at IS NULL OR status='cancelled'",
            "SELECT COUNT(*) FROM orders WHERE cancelled_at IS NOT NULL AND status != 'cancelled'",
        ),
        (
            "orders.shipped_at IS NULL OR paid_at IS NOT NULL",
            "SELECT COUNT(*) FROM orders WHERE shipped_at IS NOT NULL AND paid_at IS NULL",
        ),
        (
            "payments.success → paid_at NOT NULL",
            "SELECT COUNT(*) FROM payments WHERE status='success' AND paid_at IS NULL",
        ),
        (
            "payments.failed → fail_reason NOT NULL",
            "SELECT COUNT(*) FROM payments WHERE status='failed' AND fail_reason IS NULL",
        ),
        (
            "shipments.delivered → delivered_at NOT NULL",
            "SELECT COUNT(*) FROM shipments WHERE status='delivered' AND delivered_at IS NULL",
        ),
        ("reviews.rating<4 → content NOT NULL", "SELECT COUNT(*) FROM reviews WHERE rating < 4 AND content IS NULL"),
    ]
    for name, sql in cond_checks:
        n = conn.execute(sql).fetchone()[0]
        print(f"    {name:<45} 违反: {n} 行")

    # ---- 6. 枚举值合法性 ----
    print("\n[6] 枚举值合法性")
    enum_checks = [
        ("organizations.plan", "SELECT DISTINCT plan FROM organizations"),
        ("users.role", "SELECT DISTINCT role FROM users"),
        ("users.gender", "SELECT DISTINCT gender FROM users"),
        ("products.status", "SELECT DISTINCT status FROM products"),
        ("orders.status", "SELECT DISTINCT status FROM orders"),
        ("payments.method", "SELECT DISTINCT method FROM payments"),
        ("payments.currency", "SELECT DISTINCT currency FROM payments"),
        ("coupons.discount_type", "SELECT DISTINCT discount_type FROM coupons"),
        ("audit_logs.action", "SELECT DISTINCT action FROM audit_logs"),
        ("team_members.role", "SELECT DISTINCT role FROM team_members"),
    ]
    for name, sql in enum_checks:
        vals = [r[0] for r in conn.execute(sql).fetchall()]
        print(f"    {name:<28} {vals}")

    # ---- 7. 范围约束抽查 ----
    print("\n[7] 范围约束抽查")
    range_checks = [
        ("users.age ∈ [18,120]", "SELECT MIN(age), MAX(age) FROM users"),
        ("products.price > 0", "SELECT MIN(price), MAX(price) FROM products"),
        ("products.rating ∈ [0,5]", "SELECT MIN(rating), MAX(rating) FROM products"),
        ("organizations.max_users ∈ [1,10000]", "SELECT MIN(max_users), MAX(max_users) FROM organizations"),
        ("reviews.rating ∈ [1,5]", "SELECT MIN(rating), MAX(rating) FROM reviews"),
        ("order_items.quantity ∈ [1,100]", "SELECT MIN(quantity), MAX(quantity) FROM order_items"),
    ]
    for name, sql in range_checks:
        mn, mx = conn.execute(sql).fetchone()
        print(f"    {name:<40} min={mn} max={mx}")

    # ---- 8. UNIQUE 抽查 ----
    print("\n[8] UNIQUE 约束抽查（重复数应为 0）")
    uniq_checks = [
        ("organizations.code", "SELECT code, COUNT(*) c FROM organizations GROUP BY code HAVING c>1"),
        ("users.email", "SELECT email, COUNT(*) c FROM users GROUP BY email HAVING c>1"),
        ("users.username", "SELECT username, COUNT(*) c FROM users GROUP BY username HAVING c>1"),
        ("products.sku", "SELECT sku, COUNT(*) c FROM products GROUP BY sku HAVING c>1"),
        ("orders.order_no", "SELECT order_no, COUNT(*) c FROM orders GROUP BY order_no HAVING c>1"),
        (
            "order_items(order_id,product_id)",
            "SELECT order_id, product_id, COUNT(*) c FROM order_items GROUP BY order_id, product_id HAVING c>1",
        ),
        (
            "team_members(org_id,user_id)",
            "SELECT org_id, user_id, COUNT(*) c FROM team_members GROUP BY org_id, user_id HAVING c>1",
        ),
    ]
    for name, sql in uniq_checks:
        dups = len(conn.execute(sql).fetchall())
        print(f"    {name:<35} 重复组数: {dups}")

    # ---- 9. NULL 比例抽查 ----
    print("\n[9] NULL 比例抽查（应 > 0，验证 null_ratio 生效）")
    null_checks = [
        ("users.phone", "SELECT COUNT(*) FROM users"),
        ("orders.notes", "SELECT COUNT(*) FROM orders WHERE notes IS NOT NULL"),
        ("orders.billing_address", "SELECT COUNT(*) FROM orders WHERE billing_address IS NOT NULL"),
        ("payments.fail_reason", "SELECT COUNT(*) FROM payments WHERE fail_reason IS NOT NULL"),
        ("audit_logs.details", "SELECT COUNT(*) FROM audit_logs WHERE details IS NOT NULL"),
    ]
    for name, sql in null_checks:
        n = conn.execute(sql).fetchone()[0]
        print(f"    {name:<30} 非空数: {n}")

    # ---- 10. UUID 主键格式 ----
    print("\n[10] UUID 主键格式（audit_logs.id）")
    bad_uuid = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE id NOT GLOB '[0-9a-f-]*' OR length(id) != 36"
    ).fetchone()[0]
    print(f"     非法 UUID 格式: {bad_uuid} 行")

    # ---- 11. 自引用合理性 ----
    print("\n[11] 自引用 FK 合理性")
    dept_self = conn.execute("SELECT COUNT(*) FROM departments WHERE parent_id IS NOT NULL").fetchone()[0]
    cat_self = conn.execute("SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL").fetchone()[0]
    print(f"     departments 有父节点: {dept_self} 行")
    print(f"     categories 有父节点: {cat_self} 行")

    conn.close()
    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)


def main() -> None:
    """构建 schema → 填充数据 → 验证约束合规性。"""
    build_schema(DB_PATH)
    fill_data(DB_PATH)
    verify(DB_PATH)


if __name__ == "__main__":
    main()
