-- Round 3: Logistics & Supply Chain (12 tables)
-- Exercises: Warehouse hierarchy, shipment state machine, package weight/volume,
--             multi-leg routing, delivery attempts, conditional NULL, date ordering

PRAGMA foreign_keys = ON;

CREATE TABLE regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER,
    level INTEGER NOT NULL CHECK (level IN (1, 2, 3, 4)),
    postal_prefix TEXT,
    FOREIGN KEY (parent_id) REFERENCES regions(id),
    CHECK (level = 1 OR parent_id IS NOT NULL)
);

CREATE TABLE warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wh_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    region_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    capacity_cbm REAL NOT NULL CHECK (capacity_cbm > 0.0),
    used_cbm REAL NOT NULL DEFAULT 0.0 CHECK (used_cbm >= 0.0),
    temperature_min REAL CHECK (temperature_min IS NULL OR temperature_min >= -30.0),
    temperature_max REAL CHECK (temperature_max IS NULL OR temperature_max <= 40.0),
    manager_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'closed')),
    opened_at DATE NOT NULL,
    FOREIGN KEY (region_id) REFERENCES regions(id),
    CHECK (used_cbm <= capacity_cbm),
    CHECK (temperature_min IS NULL OR temperature_max IS NULL OR temperature_max > temperature_min),
    CHECK (LENGTH(phone) >= 7)
);

CREATE TABLE carriers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carrier_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    service_type TEXT NOT NULL CHECK (service_type IN ('express', 'standard', 'economy', 'freight', 'same_day')),
    coverage TEXT NOT NULL CHECK (coverage IN ('domestic', 'international', 'regional')),
    base_rate REAL NOT NULL CHECK (base_rate >= 0.0),
    rate_per_kg REAL NOT NULL CHECK (rate_per_kg >= 0.0),
    insurance_available INTEGER NOT NULL DEFAULT 1 CHECK (insurance_available IN (0, 1)),
    max_weight_kg REAL NOT NULL CHECK (max_weight_kg > 0.0),
    contract_start DATE NOT NULL,
    contract_end DATE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'terminated')),
    CHECK (contract_end IS NULL OR contract_end >= contract_start)
);

CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_no TEXT NOT NULL UNIQUE,
    carrier_id INTEGER NOT NULL,
    vehicle_type TEXT NOT NULL CHECK (vehicle_type IN ('van', 'truck', 'semi', 'container', 'bike', 'drone')),
    capacity_weight_kg REAL NOT NULL CHECK (capacity_weight_kg > 0.0),
    capacity_volume_cbm REAL NOT NULL CHECK (capacity_volume_cbm > 0.0),
    fuel_type TEXT NOT NULL CHECK (fuel_type IN ('gasoline', 'diesel', 'electric', 'hybrid', 'hydrogen')),
    purchase_date DATE NOT NULL,
    last_inspection DATE,
    next_inspection DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'in_transit', 'maintenance', 'retired')),
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    CHECK (next_inspection > purchase_date),
    CHECK (last_inspection IS NULL OR last_inspection <= next_inspection)
);

CREATE TABLE drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    carrier_id INTEGER NOT NULL,
    license_no TEXT NOT NULL UNIQUE,
    license_type TEXT NOT NULL CHECK (license_type IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')),
    phone TEXT NOT NULL,
    hire_date DATE NOT NULL,
    license_expiry DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_leave', 'terminated')),
    rating REAL NOT NULL DEFAULT 5.0 CHECK (rating >= 0.0 AND rating <= 5.0),
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    CHECK (license_expiry > hire_date),
    CHECK (LENGTH(phone) >= 7)
);

CREATE TABLE routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_code TEXT NOT NULL UNIQUE,
    origin_wh_id INTEGER NOT NULL,
    dest_wh_id INTEGER NOT NULL,
    carrier_id INTEGER NOT NULL,
    distance_km REAL NOT NULL CHECK (distance_km > 0.0),
    estimated_hours REAL NOT NULL CHECK (estimated_hours > 0.0),
    toll_fee REAL NOT NULL DEFAULT 0.0 CHECK (toll_fee >= 0.0),
    transport_mode TEXT NOT NULL CHECK (transport_mode IN ('road', 'rail', 'air', 'sea', 'multimodal')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (origin_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (dest_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    CHECK (origin_wh_id != dest_wh_id),
    CHECK (estimated_hours <= distance_km * 0.5 + 24.0)
);

CREATE TABLE shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_no TEXT NOT NULL UNIQUE,
    origin_wh_id INTEGER NOT NULL,
    dest_wh_id INTEGER NOT NULL,
    carrier_id INTEGER NOT NULL,
    route_id INTEGER,
    vehicle_id INTEGER,
    driver_id INTEGER,
    sender_name TEXT NOT NULL,
    sender_phone TEXT NOT NULL,
    sender_address TEXT NOT NULL,
    receiver_name TEXT NOT NULL,
    receiver_phone TEXT NOT NULL,
    receiver_address TEXT NOT NULL,
    total_weight_kg REAL NOT NULL CHECK (total_weight_kg > 0.0),
    total_volume_cbm REAL NOT NULL CHECK (total_volume_cbm > 0.0),
    declared_value REAL NOT NULL DEFAULT 0.0 CHECK (declared_value >= 0.0),
    freight_cost REAL NOT NULL CHECK (freight_cost >= 0.0),
    insurance_fee REAL NOT NULL DEFAULT 0.0 CHECK (insurance_fee >= 0.0),
    cod_amount REAL NOT NULL DEFAULT 0.0 CHECK (cod_amount >= 0.0),
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'picked_up', 'in_transit', 'arrived', 'out_for_delivery', 'delivered', 'returned', 'lost')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    picked_up_at DATETIME,
    delivered_at DATETIME,
    FOREIGN KEY (origin_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (dest_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    FOREIGN KEY (route_id) REFERENCES routes(id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY (driver_id) REFERENCES drivers(id),
    CHECK (origin_wh_id != dest_wh_id),
    CHECK (status != 'picked_up' OR picked_up_at IS NOT NULL),
    CHECK (status != 'delivered' OR delivered_at IS NOT NULL),
    CHECK (delivered_at IS NULL OR delivered_at >= picked_up_at)
);

CREATE TABLE packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_no TEXT NOT NULL UNIQUE,
    shipment_id INTEGER NOT NULL,
    seq_no INTEGER NOT NULL CHECK (seq_no > 0),
    weight_kg REAL NOT NULL CHECK (weight_kg > 0.0),
    length_cm REAL NOT NULL CHECK (length_cm > 0.0),
    width_cm REAL NOT NULL CHECK (width_cm > 0.0),
    height_cm REAL NOT NULL CHECK (height_cm > 0.0),
    volume_cbm REAL NOT NULL,
    description TEXT,
    is_fragile INTEGER NOT NULL DEFAULT 0 CHECK (is_fragile IN (0, 1)),
    requires_cold_chain INTEGER NOT NULL DEFAULT 0 CHECK (requires_cold_chain IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'packed', 'loaded', 'in_transit', 'delivered', 'damaged', 'lost')),
    FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
    CHECK (volume_cbm = length_cm * width_cm * height_cm / 1000000.0),
    CHECK (weight_kg <= 1000.0)
);

CREATE TABLE tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_no TEXT NOT NULL UNIQUE,
    tracking_no TEXT NOT NULL,
    shipment_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('created', 'picked_up', 'arrived_at_wh', 'departed_wh', 'in_transit', 'out_for_delivery', 'delivered', 'exception', 'returned')),
    location TEXT NOT NULL,
    description TEXT,
    event_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    operator TEXT NOT NULL,
    FOREIGN KEY (tracking_no) REFERENCES packages(tracking_no),
    FOREIGN KEY (shipment_id) REFERENCES shipments(id),
    CHECK (event_type != 'delivered' OR description IS NOT NULL)
);

CREATE TABLE delivery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_no TEXT NOT NULL UNIQUE,
    shipment_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    attempt_date DATE NOT NULL,
    attempt_time TEXT NOT NULL CHECK (attempt_time LIKE '__:__'),
    result TEXT NOT NULL CHECK (result IN ('success', 'failed', 'partial', 'rescheduled')),
    failure_reason TEXT CHECK (failure_reason IN ('recipient_absent', 'wrong_address', 'refused', 'damaged', 'weather', 'other')),
    signature_path TEXT,
    photo_path TEXT,
    notes TEXT,
    FOREIGN KEY (shipment_id) REFERENCES shipments(id),
    FOREIGN KEY (driver_id) REFERENCES drivers(id),
    CHECK (result != 'failed' OR failure_reason IS NOT NULL),
    CHECK (result != 'success' OR signature_path IS NOT NULL)
);

CREATE TABLE transfer_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transfer_no TEXT NOT NULL UNIQUE,
    from_wh_id INTEGER NOT NULL,
    to_wh_id INTEGER NOT NULL,
    product_sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_value REAL NOT NULL CHECK (unit_value >= 0.0),
    total_value REAL NOT NULL CHECK (total_value >= 0.0),
    carrier_id INTEGER,
    shipment_id INTEGER,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'shipped', 'received', 'cancelled')),
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at DATETIME,
    shipped_at DATETIME,
    received_at DATETIME,
    FOREIGN KEY (from_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (to_wh_id) REFERENCES warehouses(id),
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    FOREIGN KEY (shipment_id) REFERENCES shipments(id),
    CHECK (from_wh_id != to_wh_id),
    CHECK (total_value = unit_value * quantity),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'shipped' OR shipped_at IS NOT NULL),
    CHECK (status != 'received' OR received_at IS NOT NULL),
    CHECK (shipped_at IS NULL OR shipped_at >= approved_at),
    CHECK (received_at IS NULL OR received_at >= shipped_at)
);

CREATE TABLE freight_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    carrier_id INTEGER NOT NULL,
    shipment_id INTEGER NOT NULL,
    base_charge REAL NOT NULL CHECK (base_charge >= 0.0),
    weight_charge REAL NOT NULL CHECK (weight_charge >= 0.0),
    distance_charge REAL NOT NULL CHECK (distance_charge >= 0.0),
    fuel_surcharge REAL NOT NULL DEFAULT 0.0 CHECK (fuel_surcharge >= 0.0),
    insurance_charge REAL NOT NULL DEFAULT 0.0 CHECK (insurance_charge >= 0.0),
    tax REAL NOT NULL DEFAULT 0.0 CHECK (tax >= 0.0),
    total_amount REAL NOT NULL CHECK (total_amount >= 0.0),
    paid_amount REAL NOT NULL DEFAULT 0.0 CHECK (paid_amount >= 0.0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'overdue', 'disputed', 'cancelled')),
    issued_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_date DATE NOT NULL,
    paid_at DATETIME,
    FOREIGN KEY (carrier_id) REFERENCES carriers(id),
    FOREIGN KEY (shipment_id) REFERENCES shipments(id),
    CHECK (total_amount = base_charge + weight_charge + distance_charge + fuel_surcharge + insurance_charge + tax),
    CHECK (paid_amount <= total_amount),
    CHECK (status != 'paid' OR paid_at IS NOT NULL),
    CHECK (paid_at IS NULL OR paid_at >= issued_at),
    CHECK (due_date >= DATE(issued_at))
);
