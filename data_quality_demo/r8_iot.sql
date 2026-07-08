-- Round 8: IoT Device Management & Telemetry Platform (12 tables)
-- Compatible: PostgreSQL only
-- Exercises: PG-specific types (uuid, JSONB, inet, cidr, macaddr, interval,
--             text[], tsvector, tstzrange), exclusion constraint, expression
--             index, full-text search, ON UPDATE CASCADE, nested AND/OR
-- Patterns: P8b, P8c, P8d, P13, P14, P20, P22b, P25

-- Note: This database requires PostgreSQL 14+ for JSONB, inet, cidr, macaddr,
-- interval, text[], tsvector, tstzrange, EXCLUDE USING gist, and gen_random_uuid().
-- Install btree_gist extension for EXCLUDE on integer columns.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE device_types (
    id SERIAL PRIMARY KEY,
    type_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER,
    specs JSONB,
    is_normal INTEGER NOT NULL DEFAULT 1 CHECK (is_normal IN (0, 1)),
    test_value REAL,
    ref_low REAL,
    ref_high REAL,
    FOREIGN KEY (parent_id) REFERENCES device_types(id) ON UPDATE CASCADE,
    CHECK (is_normal = 0 OR test_value IS NULL OR ref_low IS NULL OR ref_high IS NULL
           OR (test_value >= ref_low AND test_value <= ref_high)),
    CHECK (is_normal = 1 OR test_value IS NULL OR ref_low IS NULL OR ref_high IS NULL
           OR test_value < ref_low OR test_value > ref_high)
);

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type_id INTEGER NOT NULL,
    mac macaddr,
    ip inet,
    config JSONB,
    tags TEXT[] DEFAULT '{}',
    unit_price REAL NOT NULL CHECK (unit_price >= 0.0),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    shipping_cost REAL NOT NULL DEFAULT 0.0 CHECK (shipping_cost >= 0.0),
    total_cost REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'retired', 'faulty')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (type_id) REFERENCES device_types(id) ON UPDATE CASCADE,
    CHECK (total_cost = unit_price * quantity + shipping_cost)
);

CREATE INDEX idx_devices_name_lower ON devices (lower(name));

CREATE TABLE sensors (
    id SERIAL PRIMARY KEY,
    sensor_code TEXT NOT NULL UNIQUE,
    device_id UUID NOT NULL,
    name TEXT NOT NULL,
    calibration REAL NOT NULL DEFAULT 0.0,
    min_threshold REAL NOT NULL DEFAULT 0.0,
    calibration_delta REAL NOT NULL DEFAULT 0.0,
    sensitivity REAL NOT NULL DEFAULT 1.0,
    offset_value REAL NOT NULL DEFAULT 0.0,
    calibration_data JSONB,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error')),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    CHECK (calibration >= min_threshold AND calibration <= 100.0),
    CHECK (offset_value = sensitivity * abs(calibration_delta))
);

CREATE TABLE sensor_readings (
    id BIGSERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL,
    value REAL NOT NULL,
    max_range REAL NOT NULL CHECK (max_range > 0.0),
    raw_value REAL NOT NULL,
    min_raw REAL NOT NULL DEFAULT 0.0,
    payload JSONB,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id) ON DELETE CASCADE,
    CHECK (value > 0.0 AND value < max_range),
    CHECK (raw_value > min_raw AND raw_value < 999999.0)
);

CREATE TABLE firmware_versions (
    id SERIAL PRIMARY KEY,
    version_code TEXT NOT NULL UNIQUE,
    version_from REAL NOT NULL,
    version_to REAL NOT NULL,
    delta REAL NOT NULL DEFAULT 0.0,
    size_mb REAL NOT NULL,
    max_size REAL NOT NULL CHECK (max_size > 0.0),
    compatible_models TEXT[] DEFAULT '{}',
    release_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'released', 'deprecated')),
    CHECK (delta = abs(version_from) * abs(version_to)),
    CHECK (size_mb >= 1.0 AND size_mb <= max_size * 1.5)
);

CREATE TABLE deployment_sessions (
    id SERIAL PRIMARY KEY,
    session_code TEXT NOT NULL UNIQUE,
    device_id UUID NOT NULL,
    firmware_id INTEGER,
    time_range TSTZRANGE NOT NULL,
    duration INTERVAL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'completed', 'failed')),
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (firmware_id) REFERENCES firmware_versions(id),
    EXCLUDE USING gist (device_id WITH =, time_range WITH &&)
);

CREATE TABLE alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_code TEXT NOT NULL UNIQUE,
    device_id UUID NOT NULL,
    sensor_id INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical', 'fatal')),
    context JSONB,
    search_vector TSVECTOR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    FOREIGN KEY (sensor_id) REFERENCES sensors(id),
    CHECK (severity != 'fatal' OR context IS NOT NULL)
);

CREATE INDEX idx_alerts_search ON alerts USING gin(search_vector);

CREATE TABLE maintenance_logs (
    id BIGSERIAL PRIMARY KEY,
    log_code TEXT NOT NULL UNIQUE,
    device_id UUID NOT NULL,
    technician TEXT NOT NULL,
    labor_time INTERVAL,
    cost REAL NOT NULL DEFAULT 0.0 CHECK (cost >= 0.0),
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
    scheduled_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    notes TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    CHECK (status != 'in_progress' OR started_at IS NOT NULL),
    CHECK (status != 'completed' OR completed_at IS NOT NULL),
    CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
    CHECK (
        (status = 'completed' AND cost > 0 AND labor_time IS NOT NULL)
        OR (status = 'scheduled' AND started_at IS NULL AND completed_at IS NULL)
        OR (status = 'in_progress' AND started_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'cancelled')
    )
);

CREATE TABLE networks (
    id SERIAL PRIMARY KEY,
    network_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    subnet CIDR NOT NULL,
    gateway_ip INET,
    vlan_id INTEGER CHECK (vlan_id IS NULL OR (vlan_id >= 1 AND vlan_id <= 4094)),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'reserved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE gateways (
    id SERIAL PRIMARY KEY,
    gateway_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    network_id INTEGER NOT NULL,
    ip INET NOT NULL,
    mac macaddr,
    firmware_version TEXT,
    status TEXT NOT NULL DEFAULT 'online' CHECK (status IN ('online', 'offline', 'maintenance')),
    last_seen_at TIMESTAMPTZ,
    FOREIGN KEY (network_id) REFERENCES networks(id),
    CHECK (status != 'online' OR last_seen_at IS NOT NULL)
);

CREATE TABLE telemetry_events (
    id BIGSERIAL PRIMARY KEY,
    event_code TEXT NOT NULL UNIQUE,
    device_id UUID NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('status', 'error', 'warning', 'config_change', 'reboot')),
    metadata JSONB,
    mime_type TEXT NOT NULL DEFAULT 'application/json',
    payload_size INTEGER NOT NULL DEFAULT 0 CHECK (payload_size >= 0),
    search_vector TSVECTOR,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
);

CREATE INDEX idx_telemetry_search ON telemetry_events USING gin(search_vector);

CREATE TABLE device_groups (
    id SERIAL PRIMARY KEY,
    group_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER,
    member_ids INTEGER[] DEFAULT '{}',
    rules JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES device_groups(id)
);
