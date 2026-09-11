-- 24 张业务表。固定时间默认值使夹具可重复；金额统一使用整数分。
PRAGMA foreign_keys = ON;
CREATE TABLE tenants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT '2026-01-01 00:00:00'
);
CREATE TABLE warehouses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  city TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK(capacity >= 0),
  enabled BOOLEAN NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,code)
);
CREATE TABLE employees (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  manager_id INTEGER,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'operator' CHECK(role IN ('manager','operator')),
  joined_at DATE NOT NULL DEFAULT '2026-01-01',
  UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,manager_id) REFERENCES employees(tenant_id,id),
  CHECK(manager_id IS NULL OR manager_id <> id)
);
CREATE TABLE customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  phone TEXT,
  tier TEXT NOT NULL DEFAULT 'standard' CHECK(tier IN ('standard','vip')),
  credit_limit_cents INTEGER NOT NULL DEFAULT 0 CHECK(credit_limit_cents >= 0),
  created_at DATETIME NOT NULL DEFAULT '2026-01-01 00:00:00',
  UNIQUE(tenant_id,id)
);
CREATE TABLE addresses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  recipient TEXT NOT NULL,
  province TEXT NOT NULL,
  city TEXT NOT NULL,
  street TEXT NOT NULL,
  postal_code TEXT,
  is_default BOOLEAN NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,customer_id,id),
  FOREIGN KEY(tenant_id,customer_id) REFERENCES customers(tenant_id,id)
);
CREATE TABLE suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'CNY' CHECK(currency IN ('CNY','USD','EUR')),
  payment_days INTEGER NOT NULL DEFAULT 30 CHECK(payment_days BETWEEN 0 AND 180),
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,code)
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id),
  sku TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'accessory' CHECK(category IN ('accessory','home','office')),
  price_cents INTEGER NOT NULL CHECK(price_cents > 0),
  cost_cents INTEGER NOT NULL CHECK(cost_cents >= 0 AND cost_cents <= price_cents),
  weight_grams INTEGER NOT NULL CHECK(weight_grams > 0),
  active BOOLEAN NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at DATETIME NOT NULL DEFAULT '2026-01-01 00:00:00',
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,sku)
);
CREATE TABLE supplier_products (
  tenant_id INTEGER NOT NULL,
  supplier_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  supplier_sku TEXT NOT NULL,
  unit_cost_cents INTEGER NOT NULL CHECK(unit_cost_cents > 0),
  lead_days INTEGER NOT NULL DEFAULT 3 CHECK(lead_days >= 0),
  PRIMARY KEY(tenant_id,supplier_id,product_id),
  FOREIGN KEY(tenant_id,supplier_id) REFERENCES suppliers(tenant_id,id),
  FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id)
);
CREATE TABLE inventory (
  tenant_id INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  on_hand INTEGER NOT NULL CHECK(on_hand >= 0),
  reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved >= 0 AND reserved <= on_hand),
  available INTEGER GENERATED ALWAYS AS (on_hand-reserved) STORED,
  reorder_point INTEGER NOT NULL DEFAULT 10 CHECK(reorder_point >= 0),
  PRIMARY KEY(tenant_id,warehouse_id,product_id),
  FOREIGN KEY(tenant_id,warehouse_id) REFERENCES warehouses(tenant_id,id),
  FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id)
);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  customer_id INTEGER NOT NULL,
  shipping_address_id INTEGER NOT NULL,
  billing_address_id INTEGER,
  owner_id INTEGER,
  order_no TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'web' CHECK(channel IN ('web','store','partner')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','paid','shipped','delivered','cancelled','refunded')),
  currency TEXT NOT NULL DEFAULT 'CNY' CHECK(currency IN ('CNY','USD','EUR')),
  ordered_at DATETIME NOT NULL,
  promised_at DATETIME NOT NULL,
  paid_at DATETIME,
  shipped_at DATETIME,
  delivered_at DATETIME,
  cancelled_at DATETIME,
  subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
  discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents >= 0 AND discount_cents <= subtotal_cents),
  shipping_cents INTEGER NOT NULL DEFAULT 0 CHECK(shipping_cents >= 0),
  tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(tax_cents >= 0),
  total_cents INTEGER GENERATED ALWAYS AS (subtotal_cents-discount_cents+shipping_cents+tax_cents) STORED,
  refunded_cents INTEGER NOT NULL DEFAULT 0 CHECK(refunded_cents >= 0 AND refunded_cents <= total_cents),
  priority INTEGER NOT NULL DEFAULT 0 CHECK(priority BETWEEN 0 AND 5),
  gift_message TEXT,
  delivery_note TEXT,
  invoice_title TEXT,
  tax_number TEXT,
  contact_email TEXT,
  contact_phone TEXT,
  external_reference TEXT,
  internal_note TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_no),
  FOREIGN KEY(tenant_id,customer_id) REFERENCES customers(tenant_id,id),
  FOREIGN KEY(tenant_id,customer_id,shipping_address_id) REFERENCES addresses(tenant_id,customer_id,id),
  FOREIGN KEY(tenant_id,customer_id,billing_address_id) REFERENCES addresses(tenant_id,customer_id,id),
  FOREIGN KEY(tenant_id,owner_id) REFERENCES employees(tenant_id,id),
  CHECK(promised_at >= ordered_at),
  CHECK(paid_at IS NULL OR paid_at >= ordered_at),
  CHECK(shipped_at IS NULL OR (paid_at IS NOT NULL AND shipped_at >= paid_at)),
  CHECK(delivered_at IS NULL OR (shipped_at IS NOT NULL AND delivered_at >= shipped_at)),
  CHECK(cancelled_at IS NULL OR cancelled_at >= ordered_at)
);
CREATE TABLE order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  line_no INTEGER NOT NULL CHECK(line_no > 0),
  product_id INTEGER NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents > 0),
  discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents >= 0 AND discount_cents <= quantity*unit_price_cents),
  line_total_cents INTEGER GENERATED ALWAYS AS (quantity*unit_price_cents-discount_cents) STORED,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_id,line_no),
  FOREIGN KEY(tenant_id,order_id) REFERENCES orders(tenant_id,id),
  FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id)
);
CREATE TABLE payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  payment_no TEXT NOT NULL,
  method TEXT NOT NULL CHECK(method IN ('card','wallet','bank')),
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  status TEXT NOT NULL DEFAULT 'captured' CHECK(status IN ('captured','void')),
  paid_at DATETIME NOT NULL,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,payment_no),
  FOREIGN KEY(tenant_id,order_id) REFERENCES orders(tenant_id,id)
);
CREATE TABLE shipments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  current_event_id INTEGER,
  tracking_no TEXT NOT NULL,
  carrier TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created','in_transit','delivered')),
  dispatched_at DATETIME,
  delivered_at DATETIME,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_id,id), UNIQUE(tenant_id,tracking_no),
  FOREIGN KEY(tenant_id,order_id) REFERENCES orders(tenant_id,id),
  FOREIGN KEY(tenant_id,warehouse_id) REFERENCES warehouses(tenant_id,id),
  FOREIGN KEY(tenant_id,current_event_id) REFERENCES shipment_events(tenant_id,id),
  CHECK(delivered_at IS NULL OR (dispatched_at IS NOT NULL AND delivered_at >= dispatched_at))
);
CREATE TABLE shipment_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  shipment_id INTEGER,
  event_type TEXT NOT NULL CHECK(event_type IN ('created','picked_up','delivered')),
  occurred_at DATETIME NOT NULL,
  location TEXT,
  UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES shipments(tenant_id,id)
);
CREATE TABLE shipment_items (
  tenant_id INTEGER NOT NULL,
  shipment_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  line_no INTEGER NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  PRIMARY KEY(tenant_id,shipment_id,line_no),
  FOREIGN KEY(tenant_id,order_id,shipment_id) REFERENCES shipments(tenant_id,order_id,id),
  FOREIGN KEY(tenant_id,order_id,line_no) REFERENCES order_items(tenant_id,order_id,line_no)
);
CREATE TABLE purchase_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  supplier_id INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  purchase_no TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ordered' CHECK(status IN ('ordered','received','cancelled')),
  ordered_at DATE NOT NULL,
  expected_at DATE NOT NULL,
  received_at DATE,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,purchase_no),
  FOREIGN KEY(tenant_id,supplier_id) REFERENCES suppliers(tenant_id,id),
  FOREIGN KEY(tenant_id,warehouse_id) REFERENCES warehouses(tenant_id,id),
  CHECK(expected_at >= ordered_at),
  CHECK(received_at IS NULL OR received_at >= ordered_at)
);
CREATE TABLE purchase_order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  purchase_order_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  unit_cost_cents INTEGER NOT NULL CHECK(unit_cost_cents > 0),
  received_quantity INTEGER NOT NULL DEFAULT 0 CHECK(received_quantity >= 0 AND received_quantity <= quantity),
  total_cost_cents INTEGER GENERATED ALWAYS AS (quantity*unit_cost_cents) STORED,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,purchase_order_id,product_id),
  FOREIGN KEY(tenant_id,purchase_order_id) REFERENCES purchase_orders(tenant_id,id),
  FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id)
);
CREATE TABLE stock_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  warehouse_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  movement_type TEXT NOT NULL CHECK(movement_type IN ('receipt','sale','return','adjustment')),
  delta INTEGER NOT NULL CHECK(delta <> 0),
  occurred_at DATETIME NOT NULL,
  purchase_item_id INTEGER,
  order_item_id INTEGER,
  FOREIGN KEY(tenant_id,warehouse_id,product_id) REFERENCES inventory(tenant_id,warehouse_id,product_id),
  FOREIGN KEY(tenant_id,purchase_item_id) REFERENCES purchase_order_items(tenant_id,id),
  FOREIGN KEY(tenant_id,order_item_id) REFERENCES order_items(tenant_id,id),
  CHECK((movement_type='receipt' AND delta > 0 AND purchase_item_id IS NOT NULL AND order_item_id IS NULL)
     OR (movement_type='sale' AND delta < 0 AND order_item_id IS NOT NULL AND purchase_item_id IS NULL)
     OR (movement_type='return' AND delta > 0 AND order_item_id IS NOT NULL AND purchase_item_id IS NULL)
     OR movement_type='adjustment')
);
CREATE TABLE returns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  return_no TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'requested' CHECK(status IN ('requested','received','refunded')),
  requested_at DATETIME NOT NULL,
  received_at DATETIME,
  reason TEXT NOT NULL,
  UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_id,id), UNIQUE(tenant_id,return_no),
  FOREIGN KEY(tenant_id,order_id) REFERENCES orders(tenant_id,id),
  CHECK(received_at IS NULL OR received_at >= requested_at)
);
CREATE TABLE return_items (
  tenant_id INTEGER NOT NULL,
  return_id INTEGER NOT NULL,
  order_id INTEGER NOT NULL,
  line_no INTEGER NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  refund_cents INTEGER NOT NULL CHECK(refund_cents >= 0),
  PRIMARY KEY(tenant_id,return_id,line_no),
  FOREIGN KEY(tenant_id,order_id,return_id) REFERENCES returns(tenant_id,order_id,id),
  FOREIGN KEY(tenant_id,order_id,line_no) REFERENCES order_items(tenant_id,order_id,line_no)
);
CREATE TABLE refunds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL,
  return_id INTEGER NOT NULL,
  payment_id INTEGER NOT NULL,
  refund_no TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  refunded_at DATETIME NOT NULL,
  UNIQUE(tenant_id,refund_no),
  FOREIGN KEY(tenant_id,return_id) REFERENCES returns(tenant_id,id),
  FOREIGN KEY(tenant_id,payment_id) REFERENCES payments(tenant_id,id)
);
CREATE TABLE tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE product_tags (
  tenant_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL REFERENCES tags(id),
  PRIMARY KEY(tenant_id,product_id,tag_id),
  FOREIGN KEY(tenant_id,product_id) REFERENCES products(tenant_id,id)
);
-- 跨租户控制台日志。customer_email 只有业务关联，无物理外键。
CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL CHECK(event_type IN ('order.created','order.refunded','customer.preview')),
  customer_email TEXT,
  message TEXT NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT '2026-01-01 00:00:00',
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_orders_customer ON orders(tenant_id,customer_id,ordered_at);
CREATE INDEX idx_events_shipment ON shipment_events(tenant_id,shipment_id,occurred_at);
CREATE INDEX idx_stock_product ON stock_movements(tenant_id,warehouse_id,product_id);
