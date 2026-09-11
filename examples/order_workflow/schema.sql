PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT '2026-01-01 09:00:00'
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents BETWEEN 100 AND 100000),
    stock INTEGER NOT NULL DEFAULT 100 CHECK (stock >= 0),
    is_active BOOLEAN NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    order_no TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'shipped')),
    created_at DATETIME NOT NULL,
    paid_at DATETIME,
    shipped_at DATETIME,
    CHECK (paid_at IS NULL OR paid_at >= created_at),
    CHECK (shipped_at IS NULL OR shipped_at >= paid_at),
    CHECK (
        (status = 'pending' AND paid_at IS NULL AND shipped_at IS NULL)
        OR (status = 'paid' AND paid_at IS NOT NULL AND shipped_at IS NULL)
        OR (status = 'shipped' AND paid_at IS NOT NULL AND shipped_at IS NOT NULL)
    )
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 5),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents BETWEEN 100 AND 100000),
    line_total_cents INTEGER GENERATED ALWAYS AS (quantity * unit_price_cents) STORED,
    placed_at DATETIME NOT NULL,
    UNIQUE (order_id, product_id)
);
