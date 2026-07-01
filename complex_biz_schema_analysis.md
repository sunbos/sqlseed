# complex_biz.db 数据库结构与业务逻辑分析

**分析日期:** 2026-07-01
**数据库:** complex_biz.db (SQLite)
**数据状态:** 已清空(0 行)

---

## 一、数据库总览

| 指标 | 数量 |
|------|------|
| 表 (Table) | 8 |
| 列 (Column) | 49 |
| 外键 (Foreign Key) | 8 |
| CHECK 约束 | 14 |
| 索引 (Index, 含自动) | 7 |
| GENERATED 列 | 1 |
| UNIQUE 列 | 7 |
| 触发器 (Trigger) | 0 |
| 视图 (View) | 0 |

**业务领域:** 电商平台 — 包含商户、商品分类、商品、用户、订单、订单明细、销售记录。

---

## 二、实体关系图 (ERD)

```
                    ┌─────────────┐
                    │  categories │  商品类目
                    │  (4 cols)   │  无外键, 拓扑根节点
                    └──────┬──────┘
                           │ 1:N
                    ┌──────▼──────┐
          ┌─────────┤    items    │  商品单品 (SKU)
          │         │  (6 cols)   │  FK: category_id → categories.id
          │         └──────┬──────┘
          │                │ 1:N
          │         ┌──────▼──────┐
          │         │   sales     │  销售记录
          │         │  (5 cols)   │  FK: item_id → items.id
          │         └─────────────┘
          │
┌─────────┴───────┐
│    merchants     │  商户
│    (5 cols)      │  无外键, 拓扑根节点
└──┬───────────┬──┘
   │ 1:N       │ 1:N
┌──▼──────┐  ┌─▼──────────┐
│ users   │  │  products   │  商品
│(7 cols) │  │  (8 cols)   │  FK: merchant_id → merchants.id
└──┬──────┘  └──────┬──────┘
   │ 1:N            │ 1:N
   │         ┌──────▼──────────────┐
   │         │    order_items       │  订单明细
┌──▼──────┐  │    (8 cols)          │  FK: order_id → orders.id
│ orders  ├──┤                      │  FK: product_id → products.id
│(6 cols) │  │  GENERATED: item_total│
└─────────┘  └──────────────────────┘
```

### 外键关系总表

| 子表 | 外键列 | 父表 | 父表列 | ON DELETE | 说明 |
|------|--------|------|--------|-----------|------|
| items | category_id | categories | id | CASCADE | 商品归属类目 |
| users | merchant_id | merchants | id | CASCADE | 用户归属商户 |
| orders | user_id | users | id | CASCADE | 订单归属用户 |
| orders | merchant_id | merchants | id | CASCADE | 订单关联商户 |
| products | merchant_id | merchants | id | CASCADE | 商品归属商户 |
| order_items | order_id | orders | id | CASCADE | 明细归属订单 |
| order_items | product_id | products | id | CASCADE | 明细关联商品 |
| sales | item_id | items | id | CASCADE | 销售关联单品 |

**注意:** 所有外键均为 `ON DELETE CASCADE` — 删除父行时自动删除子行。生成数据时必须按拓扑顺序填充(父表先于子表)。

---

## 三、拓扑填充顺序

基于外键依赖的拓扑排序结果:

```
① categories   (无依赖)
② merchants   (无依赖)
③ items       (← categories)
④ users       (← merchants)
⑤ products    (← merchants)
⑥ orders      (← users, merchants)
⑦ order_items (← orders, products)
⑧ sales       (← items)
```

**并行机会:** categories 和 merchants 可并行填充;items/users/products 在各自父表完成后可并行。

---

## 四、逐表详细分析

### 4.1 categories — 商品类目

**DDL:**
```sql
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_code TEXT UNIQUE NOT NULL,
    category_name TEXT NOT NULL,
    description TEXT
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK | GENERATED |
|----|------|------|----|------|--------|--------|-------|----|-----------|
| id | INTEGER | ✓* | ✓ | ✓ | — | — | — | — | — |
| category_code | TEXT | ✗ | — | — | ✓ | — | — | — | — |
| category_name | TEXT | ✗ | — | — | — | — | — | — | — |
| description | TEXT | ✓ | — | — | — | — | — | — | — |

> *SQLite 中 `PRIMARY KEY INTEGER` 列隐式为 NOT NULL,但 `PRAGMA table_info` 报告 notnull=0(这是 SQLite 的已知行为)。

**索引:**
| 名称 | 列 | UNIQUE | 来源 |
|------|----|--------|------|
| sqlite_autoindex_categories_1 | category_code | ✓ | u (UNIQUE 自动索引) |

**业务语义:** 商品类目字典表。`category_code` 是业务唯一编码(如 CAT-0001),`category_name` 是可读名称,`description` 是可选描述。该表是 `items` 的父表。

**生成要点:**
- `id`: 跳过(AUTOINCREMENT PK,数据库自动填充)
- `category_code`: 使用 `template` 生成器,前缀 `CAT-`,需 `constraints.unique=true`
- `category_name`: 应使用 `word` 生成器(可读单词,非随机字符串)
- `description`: 使用 `text` 或 `sentence`,可为 NULL

---

### 4.2 items — 商品单品 (SKU)

**DDL:**
```sql
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    item_code TEXT UNIQUE NOT NULL,
    item_name TEXT NOT NULL,
    price REAL CHECK(price > 0),
    stock_count INTEGER CHECK(stock_count >= 0)
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK |
|----|------|------|----|------|--------|--------|-------|----|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — |
| category_id | INTEGER | ✗ | — | — | — | — | — | → categories.id |
| item_code | TEXT | ✗ | — | — | ✓ | — | — | — |
| item_name | TEXT | ✗ | — | — | — | — | — | — |
| price | REAL | ✓ | — | — | — | — | `price > 0` | — |
| stock_count | INTEGER | ✓ | — | — | — | — | `stock_count >= 0` | — |

**CHECK 约束(2 条,均为单列):**
| 表达式 | 涉及列 | 类型 |
|--------|--------|------|
| `price > 0` | price | 单列,正值约束 |
| `stock_count >= 0` | stock_count | 单列,非负约束 |

**索引:** sqlite_autoindex_items_1 (item_code, UNIQUE)

**业务语义:** 商品的 SKU 维度表。每个 item 隶属一个 category,有唯一编码 `item_code`(如 ITEM-0001)和名称 `item_name`。`price` 是基础定价,`stock_count` 是库存数量。该表是 `sales` 的父表。

**生成要点:**
- `id`: 跳过(AUTOINCREMENT)
- `category_id`: FK,需从 categories 已生成的 id 中随机选取
- `item_code`: `template`,前缀 `ITEM-`,`constraints.unique=true`
- `item_name`: `word`(非 `string`,否则产生乱码)
- `price`: `float(min_value=0.01, max_value=500, precision=2)`
- `stock_count`: `integer(min_value=0, max_value=10000)`

---

### 4.3 merchants — 商户

**DDL:**
```sql
CREATE TABLE merchants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_code TEXT UNIQUE NOT NULL,
    merchant_name TEXT NOT NULL,
    status TEXT CHECK(status IN ('active', 'suspended', 'closed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK |
|----|------|------|----|------|--------|--------|-------|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — |
| merchant_code | TEXT | ✗ | — | — | ✓ | — | — |
| merchant_name | TEXT | ✗ | — | — | — | — | — |
| status | TEXT | ✓ | — | — | — | — | `status IN ('active','suspended','closed')` |
| created_at | TIMESTAMP | ✓ | — | — | — | CURRENT_TIMESTAMP | — |

**CHECK 约束(1 条,枚举型):**
| 表达式 | 涉及列 | 类型 |
|--------|--------|------|
| `status IN ('active','suspended','closed')` | status | 枚举约束 |

**索引:** sqlite_autoindex_merchants_1 (merchant_code, UNIQUE)

**业务语义:** 商户主数据表。`status` 是商户状态枚举(活跃/暂停/关闭)。`created_at` 有数据库默认值,生成时可跳过。该表是 `users`、`products`、`orders` 的父表。

**生成要点:**
- `id`: 跳过(AUTOINCREMENT)
- `merchant_code`: `template`,前缀 `MER-`,`constraints.unique=true`
- `merchant_name`: `company`(非 `text`/`word`,生成公司名)
- `status`: `weighted_choice`,推荐权重 active:60 / suspended:25 / closed:15
- `created_at`: 跳过(DEFAULT CURRENT_TIMESTAMP)

---

### 4.4 users — 用户

**DDL:**
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT CHECK(length(phone) >= 10),
    role TEXT CHECK(role IN ('admin', 'manager', 'staff')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK |
|----|------|------|----|------|--------|--------|-------|----|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — |
| merchant_id | INTEGER | ✗ | — | — | — | — | — | → merchants.id |
| username | TEXT | ✗ | — | — | ✓ | — | — | — |
| email | TEXT | ✗ | — | — | ✓ | — | — | — |
| phone | TEXT | ✓ | — | — | — | — | `length(phone) >= 10` | — |
| role | TEXT | ✓ | — | — | — | — | `role IN ('admin','manager','staff')` | — |
| created_at | TIMESTAMP | ✓ | — | — | — | CURRENT_TIMESTAMP | — | — |

**CHECK 约束(2 条):**
| 表达式 | 涉及列 | 类型 |
|--------|--------|------|
| `length(phone) >= 10` | phone | 函数约束(长度校验) |
| `role IN ('admin','manager','staff')` | role | 枚举约束 |

**索引:**
| 名称 | 列 | UNIQUE |
|------|----|--------|
| sqlite_autoindex_users_1 | username | ✓ |
| sqlite_autoindex_users_2 | email | ✓ |

> **注意:** `username` 和 `email` 都是列级 `UNIQUE NOT NULL`,SQLite 自动创建两个独立索引。SQLAlchemy 的 `get_indexes()` 不返回这些自动索引,需要用 PRAGMA `index_list` 检测。

**业务语义:** 平台用户表。每个用户隶属一个商户。`username` 和 `email` 均需唯一。`phone` 有长度校验(≥10 位)。`role` 是角色枚举。

**生成要点:**
- `id`: 跳过
- `merchant_id`: FK,从 merchants 已有 id 随机选取
- `username`: `template`,前缀 `USER-`,`constraints.unique=true`
- `email`: `email`,`constraints.unique=true`(必须标记,否则 INSERT 会违反 UNIQUE)
- `phone`: `pattern(regex=...)` 或 `string(min_length=10)`,确保长度 ≥ 10
- `role`: `weighted_choice`,推荐 admin:10 / manager:30 / staff:60
- `created_at`: 跳过(DEFAULT)

---

### 4.5 orders — 订单

**DDL:**
```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    order_status TEXT CHECK(order_status IN ('pending', 'paid', 'shipped', 'completed', 'refunded')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK |
|----|------|------|----|------|--------|--------|-------|----|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — |
| order_no | TEXT | ✗ | — | — | ✓ | — | — | — |
| user_id | INTEGER | ✗ | — | — | — | — | — | → users.id |
| merchant_id | INTEGER | ✗ | — | — | — | — | — | → merchants.id |
| order_status | TEXT | ✓ | — | — | — | — | `order_status IN (...)` | — |
| created_at | TIMESTAMP | ✓ | — | — | — | CURRENT_TIMESTAMP | — | — |

**CHECK 约束(1 条,枚举型):**
| 表达式 | 涉及列 | 类型 |
|--------|--------|------|
| `order_status IN ('pending','paid','shipped','completed','refunded')` | order_status | 枚举约束 |

**索引:** sqlite_autoindex_orders_1 (order_no, UNIQUE)

**业务语义:** 订单主表。每笔订单关联一个用户和一个商户。`order_no` 是唯一订单编号。`order_status` 是订单状态流转枚举(待付款/已付款/已发货/已完成/已退款)。

**生成要点:**
- `id`: 跳过
- `order_no`: `template`,前缀 `ORD-`,`constraints.unique=true`
- `user_id`: FK → users.id
- `merchant_id`: FK → merchants.id
- `order_status`: `weighted_choice`,推荐 pending:30 / paid:30 / shipped:20 / completed:15 / refunded:5
- `created_at`: 跳过

---

### 4.6 products — 商品

**DDL:**
```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    sku TEXT UNIQUE NOT NULL,
    product_name TEXT NOT NULL,
    cost_price REAL CHECK(cost_price > 0),
    sale_price REAL CHECK(sale_price >= cost_price),
    stock INTEGER CHECK(stock >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK |
|----|------|------|----|------|--------|--------|-------|----|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — |
| merchant_id | INTEGER | ✗ | — | — | — | — | — | → merchants.id |
| sku | TEXT | ✗ | — | — | ✓ | — | — | — |
| product_name | TEXT | ✗ | — | — | — | — | — | — |
| cost_price | REAL | ✓ | — | — | — | — | `cost_price > 0` | — |
| sale_price | REAL | ✓ | — | — | — | — | `sale_price >= cost_price` | — |
| stock | INTEGER | ✓ | — | — | — | — | `stock >= 0` | — |
| created_at | TIMESTAMP | ✓ | — | — | — | CURRENT_TIMESTAMP | — | — |

**CHECK 约束(3 条,含 1 条跨列约束):**
| 表达式 | 涉及列 | 类型 | 风险 |
|--------|--------|------|------|
| `cost_price > 0` | cost_price | 单列正值 | 低 |
| `sale_price >= cost_price` | sale_price, cost_price | **跨列约束** | **中** — 独立生成时可能违反 |
| `stock >= 0` | stock | 单列非负 | 低 |

**索引:** sqlite_autoindex_products_1 (sku, UNIQUE)

**业务语义:** 商品主数据。每个商品隶属一个商户,有唯一 SKU。`cost_price` 是进货成本,`sale_price` 是售价(必须 ≥ 成本),`stock` 是库存量。

**关键跨列依赖:** `sale_price >= cost_price` — 售价必须不低于成本价。独立随机生成时若 `sale_price < cost_price` 则违反 CHECK。**应使用 `derive_from` 让 `sale_price` 基于成本价推导**(如 `round(value * 1.2, 2)` 表示 20% 加价)。

**生成要点:**
- `id`: 跳过
- `merchant_id`: FK → merchants.id
- `sku`: `template`,前缀 `PROD-`,`constraints.unique=true`
- `product_name`: `word`(非 `string`)
- `cost_price`: `float(min_value=0.01, max_value=1000, precision=2)`
- `sale_price`: `derive_from: [cost_price], expression: round(value * 1.2, 2)` — **必须派生**
- `stock`: `integer(min_value=0, max_value=9999)` — 必须有 max_value
- `created_at`: 跳过

---

### 4.7 order_items — 订单明细 (最复杂)

**DDL:**
```sql
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INTEGER CHECK(quantity > 0 AND quantity <= 5),
    price_per_unit REAL CHECK(price_per_unit > 0),
    discount REAL DEFAULT 0.00 CHECK(discount >= 0 AND discount <= price_per_unit),
    item_total REAL GENERATED ALWAYS AS (ROUND(quantity * (price_per_unit - discount), 2)) STORED,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK | GENERATED |
|----|------|------|----|------|--------|--------|-------|----|-----------|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — | — |
| order_id | INTEGER | ✗ | — | — | — | — | — | → orders.id | — |
| product_id | INTEGER | ✗ | — | — | — | — | — | → products.id | — |
| quantity | INTEGER | ✓ | — | — | — | — | `quantity > 0 AND quantity <= 5` | — | — |
| price_per_unit | REAL | ✓ | — | — | — | — | `price_per_unit > 0` | — | — |
| discount | REAL | ✓ | — | — | — | 0.00 | `discount >= 0 AND discount <= price_per_unit` | — | — |
| item_total | REAL | ✓ | — | — | — | — | — | — | **STORED** |
| created_at | TIMESTAMP | ✓ | — | — | — | CURRENT_TIMESTAMP | — | — | — |

**CHECK 约束(3 条,含 1 条跨列约束):**
| 表达式 | 涉及列 | 类型 | 风险 |
|--------|--------|------|------|
| `quantity > 0 AND quantity <= 5` | quantity | 单列范围 | 低 |
| `price_per_unit > 0` | price_per_unit | 单列正值 | 低 |
| `discount >= 0 AND discount <= price_per_unit` | discount, price_per_unit | **跨列约束** | **高** — discount 受 price_per_unit 上界约束 |

**GENERATED 列(1 个):**
| 列 | 表达式 | 类型 |
|----|--------|------|
| item_total | `ROUND(quantity * (price_per_unit - discount), 2)` | STORED |

> **关键:** `item_total` 是 GENERATED STORED 列 — 数据库自动计算,**INSERT 时不能包含此列**。否则报错 `cannot INSERT into generated column`。

**业务语义:** 订单明细行。每行关联一笔订单和一个商品。`quantity` 限购 1-5 件。`price_per_unit` 是下单时单价。`discount` 是折扣金额(0 到 price_per_unit 之间)。`item_total` 由数据库自动计算为 `数量 × (单价 - 折扣)`。

**关键跨列依赖:** `discount <= price_per_unit` — 折扣不能超过单价。独立随机生成 `discount` 为 `float(0, 1)` 时,若 `price_per_unit < discount`(如单价 0.5 元,折扣 0.8 元)则违反 CHECK。**应使用 `derive_from` 让 `discount` 基于 `price_per_unit` 推导**(如 `round(random_float(0, value), 2)` 确保折扣在 [0, 单价] 范围内)。

**生成要点:**
- `id`: 跳过
- `order_id`: FK → orders.id
- `product_id`: FK → products.id
- `quantity`: `integer(min_value=1, max_value=5)`
- `price_per_unit`: `float(min_value=0.01, max_value=1000, precision=2)`
- `discount`: `derive_from: [price_per_unit], expression: round(random_float(0, value), 2)` — **必须派生**
- `item_total`: **跳过**(GENERATED,数据库自动计算)
- `created_at`: 跳过

---

### 4.8 sales — 销售记录

**DDL:**
```sql
CREATE TABLE sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    customer_email TEXT NOT NULL,
    quantity_sold INTEGER CHECK(quantity_sold > 0),
    unit_price REAL CHECK(unit_price > 0)
)
```

| 列 | 类型 | 可空 | PK | 自增 | UNIQUE | 默认值 | CHECK | FK |
|----|------|------|----|------|--------|--------|-------|----|
| id | INTEGER | ✓ | ✓ | ✓ | — | — | — | — |
| item_id | INTEGER | ✗ | — | — | — | — | — | → items.id |
| customer_email | TEXT | ✗ | — | — | — | — | — | — |
| quantity_sold | INTEGER | ✓ | — | — | — | — | `quantity_sold > 0` | — |
| unit_price | REAL | ✓ | — | — | — | — | `unit_price > 0` | — |

**CHECK 约束(2 条,均为单列):**
| 表达式 | 涉及列 | 类型 |
|--------|--------|------|
| `quantity_sold > 0` | quantity_sold | 单列正值 |
| `unit_price > 0` | unit_price | 单列正值 |

**业务语义:** 销售记录表。记录每个 item 的售出事件,包含买家邮箱、数量和成交单价。该表没有 `created_at` 列。

**生成要点:**
- `id`: 跳过
- `item_id`: FK → items.id
- `customer_email`: `email`
- `quantity_sold`: `integer(min_value=1, max_value=100)`
- `unit_price`: `float(min_value=0.01, max_value=500, precision=2)`

---

## 五、CHECK 约束汇总与风险分析

### 5.1 全部 14 条 CHECK 约束

| # | 表 | 表达式 | 涉及列 | 类型 | 风险 |
|---|---|--------|--------|------|------|
| 1 | items | `price > 0` | price | 单列正值 | 低 |
| 2 | items | `stock_count >= 0` | stock_count | 单列非负 | 低 |
| 3 | merchants | `status IN ('active','suspended','closed')` | status | 枚举 | 低 |
| 4 | users | `length(phone) >= 10` | phone | 函数约束 | 低 |
| 5 | users | `role IN ('admin','manager','staff')` | role | 枚举 | 低 |
| 6 | orders | `order_status IN ('pending','paid','shipped','completed','refunded')` | order_status | 枚举 | 低 |
| 7 | products | `cost_price > 0` | cost_price | 单列正值 | 低 |
| 8 | products | `sale_price >= cost_price` | sale_price, cost_price | **跨列** | **中** |
| 9 | products | `stock >= 0` | stock | 单列非负 | 低 |
| 10 | order_items | `quantity > 0 AND quantity <= 5` | quantity | 单列范围 | 低 |
| 11 | order_items | `price_per_unit > 0` | price_per_unit | 单列正值 | 低 |
| 12 | order_items | `discount >= 0 AND discount <= price_per_unit` | discount, price_per_unit | **跨列** | **高** |
| 13 | sales | `quantity_sold > 0` | quantity_sold | 单列正值 | 低 |
| 14 | sales | `unit_price > 0` | unit_price | 单列正值 | 低 |

### 5.2 风险分级

**高风险(2 条跨列约束):**

| 约束 | 问题 | 解决方案 |
|------|------|---------|
| `sale_price >= cost_price` | 独立随机生成时,`sale_price` 可能 < `cost_price` | `sale_price` 使用 `derive_from: [cost_price], expression: round(value * 1.2, 2)` |
| `discount >= 0 AND discount <= price_per_unit` | 独立随机 `discount` 可能 > `price_per_unit` | `discount` 使用 `derive_from: [price_per_unit], expression: round(random_float(0, value), 2)` |

> **核心原则:** 凡是 CHECK 约束涉及 2 个或更多列的(跨列约束),不能独立随机生成这些列,必须用 `derive_from` 建立列间依赖关系,确保取值始终满足约束。

---

## 六、GENERATED 列汇总

| 表 | 列 | 表达式 | 类型 | 生成时处理 |
|----|----|--------|------|-----------|
| order_items | item_total | `ROUND(quantity * (price_per_unit - discount), 2)` | STORED | **跳过,不 INSERT** |

> **注意:** GENERATED 列由数据库自动计算,生成配置中不能包含此列,否则 INSERT 会报错 `cannot INSERT into generated column`。

---

## 七、UNIQUE 列汇总

| 表 | 列 | 约束来源 | 索引名 | 生成器推荐 |
|----|----|---------|--------|-----------|
| categories | category_code | 列级 UNIQUE | sqlite_autoindex_categories_1 | `template` (CAT-0001) |
| items | item_code | 列级 UNIQUE | sqlite_autoindex_items_1 | `template` (ITEM-0001) |
| merchants | merchant_code | 列级 UNIQUE | sqlite_autoindex_merchants_1 | `template` (MER-0001) |
| orders | order_no | 列级 UNIQUE | sqlite_autoindex_orders_1 | `template` (ORD-0001) |
| products | sku | 列级 UNIQUE | sqlite_autoindex_products_1 | `template` (PROD-0001) |
| users | username | 列级 UNIQUE | sqlite_autoindex_users_1 | `template` (USER-0001) |
| users | email | 列级 UNIQUE | sqlite_autoindex_users_2 | `email` + `constraints.unique=true` |

> **注意:** 所有 UNIQUE 列均通过列级 `UNIQUE` 关键字声明,SQLite 自动创建 `sqlite_autoindex_*` 索引。SQLAlchemy 的 `inspector.get_indexes()` 不返回这些自动索引,需要用 PRAGMA `index_list` 检测。

---

## 八、枚举列汇总

| 表 | 列 | 合法值 | 推荐生成器 | 推荐权重 |
|----|----|--------|-----------|---------|
| merchants | status | active, suspended, closed | `weighted_choice` | 60/25/15 |
| users | role | admin, manager, staff | `weighted_choice` | 10/30/60 |
| orders | order_status | pending, paid, shipped, completed, refunded | `weighted_choice` | 30/30/20/15/5 |

> **注意:** 枚举列应使用 `weighted_choice`(非 `choice`),以模拟真实业务分布。`choice` 是均匀随机,不符合业务场景(如退款比例通常很低)。

---

## 九、默认值列汇总(生成时跳过)

| 表 | 列 | 默认值 | 处理方式 |
|----|----|--------|---------|
| merchants | created_at | CURRENT_TIMESTAMP | 跳过,DB 自动填充 |
| orders | created_at | CURRENT_TIMESTAMP | 跳过 |
| products | created_at | CURRENT_TIMESTAMP | 跳过 |
| order_items | created_at | CURRENT_TIMESTAMP | 跳过 |
| order_items | discount | 0.00 | **不可跳过** — 虽然 DEFAULT 0,但需要随机折扣 |

> **注意:** `order_items.discount` 虽然有 `DEFAULT 0.00`,但业务上需要随机折扣(0 到 price_per_unit 之间),因此不能跳过,必须用 `derive_from` 生成。

---

## 十、数据生成策略建议

### 10.1 列分类与处理方式

| 分类 | 列数 | 处理方式 | 示例 |
|------|------|---------|------|
| AUTOINCREMENT PK | 8 | 跳过 | 所有表的 `id` |
| FK | 8 | 从父表随机选取 | `category_id`, `merchant_id`, `order_id` 等 |
| DEFAULT 列(跳过) | 4 | 跳过,DB 填充 | `created_at` |
| GENERATED 列 | 1 | 跳过,DB 计算 | `item_total` |
| UNIQUE 编码 | 6 | `template` + sequence | `category_code`, `sku` 等 |
| 枚举列 | 3 | `weighted_choice` | `status`, `role`, `order_status` |
| 跨列派生列 | 2 | `derive_from` + expression | `sale_price`, `discount` |
| 普通生成列 | 17 | 独立生成器 | `price`, `email`, `phone` 等 |

### 10.2 生成器选择建议(按列名语义)

| 列名模式 | 推荐生成器 | 原因 |
|---------|-----------|------|
| `*_code`, `*_no`, `sku` | `template` | 唯一业务编码,需序列号 |
| `*_name` (非人名) | `word` | 可读单词,非乱码 |
| `merchant_name`, `company_name` | `company` | 公司名 |
| `*_email` | `email` | 合法邮箱格式 |
| `*_phone` | `pattern` 或 `string` | 满足长度约束 |
| `*_status`, `role` | `weighted_choice` | 枚举,非均匀分布 |
| `*_price`, `*_amount` | `float` + precision=2 | 货币精度 |
| `*_count`, `quantity` | `integer` + 合理范围 | 数量 |
| `description` | `text` 或 `sentence` | 描述文本 |

---

## 十一、综合风险评估

| 风险点 | 影响范围 | 严重性 | 原因 |
|--------|---------|--------|------|
| `sale_price >= cost_price` 跨列约束 | products | 中 | 独立生成可能违反 |
| `discount <= price_per_unit` 跨列约束 | order_items | 高 | 独立生成高概率违反(单价小时) |
| `item_total` GENERATED 列 | order_items | 高 | INSERT 包含此列会报错 |
| `email` 列级 UNIQUE | users | 中 | 不标记 unique 会违反唯一约束 |
| SQLAlchemy 漏检列级 UNIQUE | 全部 | 中 | `get_indexes()` 不返回自动索引 |
| `discount` 有 DEFAULT 但不能跳过 | order_items | 低 | 需随机折扣,DEFAULT 仅兜底 |

---

## 十二、结论

complex_biz.db 是一个典型的电商业务数据库,包含 8 张表、8 条外键关系、14 条 CHECK 约束、1 个 GENERATED 列、7 个 UNIQUE 列。

**核心业务逻辑:**
1. **类目-单品层级:** categories → items(类目下有多个 SKU)
2. **商户-商品-用户三角:** merchants 是核心实体,products 和 users 都隶属商户,orders 关联两者
3. **订单-明细结构:** orders(主表) → order_items(明细行),明细行含跨列约束(discount ≤ price_per_unit)和 GENERATED 列(item_total)
4. **销售记录:** sales 独立记录 item 的售出事件

**数据生成关键点:**
- 2 个跨列 CHECK 约束必须用 `derive_from` 解决
- 1 个 GENERATED 列必须跳过
- 7 个 UNIQUE 列必须标记 `constraints.unique=true` 并使用 `template` 或带唯一的生成器
- 3 个枚举列应使用 `weighted_choice` 模拟真实分布
- 4 个 DEFAULT 列可跳过
- 所有外键需按拓扑顺序填充
