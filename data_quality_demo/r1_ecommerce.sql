-- Round 1: E-Commerce + Inventory System (12 tables)
-- Exercises: SKU management, order state machine, inventory deduction,
--             cross-column price constraints, conditional NULL, date ordering

PRAGMA foreign_keys = ON;

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK (sort_order >= 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

CREATE TABLE brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    logo_url TEXT,
    country TEXT NOT NULL CHECK (country IN ('CN', 'US', 'JP', 'KR', 'DE', 'UK', 'OTHER')),
    website TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    brand_id INTEGER,
    region TEXT NOT NULL CHECK (region IN ('north', 'south', 'east', 'west', 'central')),
    address TEXT NOT NULL,
    phone TEXT,
    opened_at DATE NOT NULL,
    closed_at DATE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'renovating')),
    FOREIGN KEY (brand_id) REFERENCES brands(id),
    CHECK (closed_at IS NULL OR closed_at >= opened_at),
    CHECK (phone IS NULL OR LENGTH(phone) >= 10)
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    brand_id INTEGER,
    description TEXT,
    cost_price REAL NOT NULL CHECK (cost_price >= 0.0),
    retail_price REAL NOT NULL CHECK (retail_price >= 0.0),
    weight_kg REAL NOT NULL DEFAULT 0.0 CHECK (weight_kg >= 0.0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'discontinued', 'recalled')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (brand_id) REFERENCES brands(id),
    CHECK (retail_price >= cost_price)
);

CREATE TABLE product_skus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_code TEXT NOT NULL UNIQUE,
    product_id INTEGER NOT NULL,
    variant_name TEXT NOT NULL,
    variant_value TEXT NOT NULL,
    price_adjustment REAL NOT NULL DEFAULT 0.0 CHECK (price_adjustment >= -1000.0 AND price_adjustment <= 1000.0),
    stock_qty INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    low_stock_threshold INTEGER NOT NULL DEFAULT 10 CHECK (low_stock_threshold >= 0),
    barcode TEXT UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    CHECK (low_stock_threshold <= 1000)
);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    gender TEXT CHECK (gender IN ('male', 'female', 'other')),
    birth_date DATE,
    member_level TEXT NOT NULL DEFAULT 'bronze' CHECK (member_level IN ('bronze', 'silver', 'gold', 'platinum')),
    total_spent REAL NOT NULL DEFAULT 0.0 CHECK (total_spent >= 0.0),
    points_balance INTEGER NOT NULL DEFAULT 0 CHECK (points_balance >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'deleted')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (phone IS NULL OR LENGTH(phone) = 11)
);

CREATE TABLE addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    recipient_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    province TEXT NOT NULL,
    city TEXT NOT NULL,
    district TEXT NOT NULL,
    detail TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    CHECK (LENGTH(phone) >= 10)
);

CREATE TABLE carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    sku_id INTEGER NOT NULL,
    store_id INTEGER,
    quantity INTEGER NOT NULL CHECK (quantity > 0 AND quantity <= 999),
    selected INTEGER NOT NULL DEFAULT 1 CHECK (selected IN (0, 1)),
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (sku_id) REFERENCES product_skus(id),
    FOREIGN KEY (store_id) REFERENCES stores(id),
    UNIQUE (customer_id, sku_id)
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    address_id INTEGER,
    store_id INTEGER,
    total_amount REAL NOT NULL CHECK (total_amount >= 0.0),
    discount_amount REAL NOT NULL DEFAULT 0.0 CHECK (discount_amount >= 0.0),
    shipping_fee REAL NOT NULL DEFAULT 0.0 CHECK (shipping_fee >= 0.0),
    pay_amount REAL NOT NULL CHECK (pay_amount >= 0.0),
    coupon_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded')),
    paid_at DATETIME,
    shipped_at DATETIME,
    delivered_at DATETIME,
    cancelled_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (store_id) REFERENCES stores(id),
    CHECK (discount_amount <= total_amount),
    CHECK (pay_amount = total_amount - discount_amount + shipping_fee),
    CHECK (status != 'paid' OR paid_at IS NOT NULL),
    CHECK (status != 'shipped' OR shipped_at IS NOT NULL),
    CHECK (status != 'delivered' OR delivered_at IS NOT NULL),
    CHECK (status != 'cancelled' OR cancelled_at IS NOT NULL),
    CHECK (shipped_at IS NULL OR shipped_at >= paid_at),
    CHECK (delivered_at IS NULL OR delivered_at >= shipped_at)
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    sku_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    unit_price REAL NOT NULL CHECK (unit_price >= 0.0),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    subtotal REAL NOT NULL CHECK (subtotal >= 0.0),
    refunded_qty INTEGER NOT NULL DEFAULT 0 CHECK (refunded_qty >= 0),
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (sku_id) REFERENCES product_skus(id),
    CHECK (subtotal = unit_price * quantity),
    CHECK (refunded_qty <= quantity)
);

CREATE TABLE inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_no TEXT NOT NULL UNIQUE,
    sku_id INTEGER NOT NULL,
    store_id INTEGER,
    movement_type TEXT NOT NULL CHECK (movement_type IN ('inbound', 'outbound', 'transfer_in', 'transfer_out', 'adjustment', 'return')),
    quantity INTEGER NOT NULL,
    reference_type TEXT CHECK (reference_type IN ('order', 'purchase', 'transfer', 'manual')),
    reference_id INTEGER,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    operator TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sku_id) REFERENCES product_skus(id),
    FOREIGN KEY (store_id) REFERENCES stores(id),
    CHECK (movement_type != 'inbound' OR quantity > 0),
    CHECK (movement_type != 'outbound' OR quantity < 0),
    CHECK (movement_type != 'adjustment' OR quantity != 0)
);

CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_no TEXT NOT NULL UNIQUE,
    order_id INTEGER NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0.0),
    method TEXT NOT NULL CHECK (method IN ('alipay', 'wechat', 'card', 'balance', 'cod')),
    transaction_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'success', 'failed', 'refunded')),
    paid_at DATETIME,
    refunded_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    CHECK (status != 'success' OR paid_at IS NOT NULL),
    CHECK (status != 'refunded' OR refunded_at IS NOT NULL),
    CHECK (refunded_at IS NULL OR refunded_at >= paid_at)
);
