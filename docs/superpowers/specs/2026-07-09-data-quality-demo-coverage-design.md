# Data Quality Demo Coverage Optimization Design

**Date:** 2026-07-09
**Status:** Approved (pending spec review)
**Branch:** `feat/contract-driven-self-healing`

## Goal

Optimize the 7 test databases in `data_quality_demo/` to achieve comprehensive
coverage of:

1. **v4 contract-driven self-healing: all 36+ CHECK constraint patterns**
2. **Database logical structures and business field types (breadth coverage)**
3. **Multi-database compatibility (SQLite + PostgreSQL)**

Strategy: **fix existing + targeted enhancement** (not redesign from scratch).

## Context

The `data_quality_demo/` folder contains 7 SQL files (R1-R7, 84 tables total)
used to test the sqlseed data generation toolkit and its v4 contract-driven
self-healing architecture. Recent rounds (R5-R7) converged to 12/12 tables each,
but a coverage audit revealed significant gaps in pattern coverage, logical
structures, field types, and PostgreSQL compatibility.

## Section 1: Coverage Audit

### 1.1 Pattern Coverage (36+ patterns)

**Covered (16 patterns):** Pattern 1, 2, 3, 5, 6, 8, 8e, 10, 11, 18, 28, 29,
36, plus single-column patterns (IN, LENGTH, range, BETWEEN, IS NULL OR).

Notable existing coverage:
- Pattern 2 (`col >= other_col`): R1 `retail_price >= cost_price`
- Pattern 10 (`col = col1 + col2`): R6 deposits `maturity_amount = principal + expected_interest`

**Missing (20+ patterns):** Pattern 4, 7, 8a, 8b, 8c, 8d, 9, 12, 13, 14, 15,
19, 20, 21, 22, 22b, 23, 24, 25, 26, 27, 30, 31, 32, 33, 34, 35.

### 1.2 Logical Structure Gaps

**Missing:** composite FK, generated columns, CASE WHEN CHECK, date arithmetic
CHECK, COALESCE CHECK, string function CHECK (SUBSTR/UPPER/LOWER), partial
unique indexes, ON DELETE SET NULL, ON UPDATE CASCADE, nested AND/OR (3+ levels),
exclusion constraints, expression indexes.

### 1.3 Business Field Type Gaps

**Missing:** UUID, latitude/longitude, VIN, ISBN, color code, IBAN, slug, MAC
address, passport number, SSN, MIME type, JSON/JSONB, inet/cidr, interval,
array, tsvector.

### 1.4 PostgreSQL Compatibility Issues

| Database | Issue | Impact |
|----------|-------|--------|
| R4 | 2 subquery CHECKs (`SELECT ... FROM plans`) | PG rejects subqueries in CHECK |
| R4 | `FOREIGN KEY (id) REFERENCES plans(id)` (self-ref on PK) | Pointless |
| R4 | Comment says "12 tables", actually 13 | Doc mismatch |
| R5 | `orders` references `coupons(id)` before `coupons` is defined | PG FK creation fails |
| R6 | `DATE(paid_at) >= due_date - DATE('30 days')` | SQLite-only date math |
| All | `PRAGMA foreign_keys = ON` | SQLite-only |
| All | `AUTOINCREMENT` | SQLite-only (PG uses SERIAL/IDENTITY) |

## Section 2: Bug Fixes & PG Compatibility (Layer 1 + Layer 2)

### 2.1 Bug Fixes

**R5 forward reference:**
- Move `coupons` table definition before `orders` table.

**R4 fixes:**
- Remove `FOREIGN KEY (id) REFERENCES plans(id)` from plans table (self-ref on
  PK is pointless).
- Fix comment from "12 tables" to "13 tables".
- Remove 2 subquery CHECKs from subscriptions:
  - `CHECK (seat_amount = seat_count * (SELECT ...) OR seat_amount = 0.0)` — remove.
  - `CHECK (billing_cycle != 'yearly' OR base_amount >= (SELECT ...))` — remove.
  - Keep `CHECK (total_amount = (base_amount + seat_amount) * (1.0 - discount_rate))`
    (pure arithmetic, no subquery, already present).

### 2.2 PG Compatibility

**Principle:** R1-R7 use only SQLite + PostgreSQL compatible syntax. R8 is
PG-specific.

| Item | Change |
|------|--------|
| `PRAGMA foreign_keys = ON` | Remove from all 7 files (PG enables FK by default; SQLite sets via connection) |
| `AUTOINCREMENT` | Keep `INTEGER PRIMARY KEY AUTOINCREMENT` in SQL files; add comment `-- PG: use GENERATED ALWAYS AS IDENTITY` |
| R6 `DATE('30 days')` arithmetic | Simplify to `paid_at IS NULL OR DATE(paid_at) >= due_date` (remove 30-day offset, simplify semantics) |
| R4 subquery CHECKs | Remove (see 2.1) |

**File header:** Each R1-R7 file gets `-- Compatible: SQLite + PostgreSQL`.

## Section 3: Pattern Gap Filling (Layer 3)

Each database receives 2-3 missing patterns in natural business positions.

### R1 E-Commerce (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P4 (computed col + NULL escape) | order_items | `line_total IS NULL OR line_total = unit_price * quantity` | `line_total REAL` |
| P22 (percentage upper bound) | orders | `shipping_fee <= total_amount * 0.3` | — |
| P26 (conditional enum) | products | `is_featured = 0 OR status IN ('active', 'discontinued')` | `is_featured INTEGER DEFAULT 0` |

### R2 Hospital (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P19 (reverse sum) | billing | `insurance_covered + patient_paid = total_price` (change `<=` to `=`) | — |
| P21 (average) | medical_records | `avg_bp = (blood_pressure_high + blood_pressure_low) / 2` | `avg_bp REAL` |
| P30 (conditional NULL) | prescriptions | `status != 'cancelled' OR dispensed_at IS NULL` | — |

### R3 Logistics (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P8a (lower literal + upper column) | packages | `actual_weight >= 0.1 AND actual_weight <= declared_weight` | `actual_weight REAL`, `declared_weight REAL` |
| P9 (standalone strict upper) | shipments | `estimated_delivery < guaranteed_delivery` | `estimated_delivery DATE`, `guaranteed_delivery DATE` |
| P15 (standalone abs) | shipments | `weight_diff = abs(total_weight_kg - billed_weight_kg)` | `weight_diff REAL`, `billed_weight_kg REAL` |

### R4 SaaS (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P24 (conditional comparison) | users | `status = 'deleted' OR last_login_at >= activated_at` | — |
| P31 (conditional equality) | subscriptions | `status != 'trialing' OR discount_rate = 0.0` | — |
| P34 (conditional upper bound) | subscriptions | `status != 'suspended' OR seat_count < 1000` | — |

Note: P34 uses a literal upper bound (1000) instead of cross-table reference
to `organizations.max_users`, because CHECK constraints cannot reference
other tables in standard SQL (SQLite allows it but PostgreSQL rejects it).
The literal 1000 is a reasonable upper bound for seat count.

### R5 Education (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P23 (multi-column threshold) | courses | `is_free = 1 OR price < 100 OR original_price < 200` | `is_free INTEGER DEFAULT 0` |
| P27 (N-way conditional range, single bound) | enrollments | `status = 'active' AND progress_percent >= 0 OR status = 'completed' AND progress_percent >= 100 OR status = 'dropped' AND progress_percent < 100` | — |
| P35 (conditional NULL with IN set) | enrollments | `status IN ('dropped', 'refunded') OR completed_at IS NULL` | — |

Note: P27 coexists with the existing Pattern 18 CHECK
(`status != 'completed' OR progress_percent = 100`). Both are compatible
because `progress_percent >= 100` in P27 is equivalent to `= 100` given
the column's range constraint (`progress_percent >= 0 AND <= 100`).

### R6 Banking (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P7 (arithmetic comparison) | loans | `total_payable >= principal * interest_rate` | — |
| P12 (abs first operand) | transactions | `fee_amount = abs(transfer_amount) * fee_rate` | `fee_amount REAL`, `transfer_amount REAL`, `fee_rate REAL` |
| P32 (conditional value/NULL) | accounts | `(status = 'frozen' AND freeze_amount > 0) OR (status IN ('active', 'closed') AND freeze_amount IS NULL)` | `freeze_amount REAL` |

### R7 Insurance (3 patterns)

| Pattern | Table | CHECK Constraint | New Columns |
|---------|-------|-----------------|-------------|
| P8a (lower literal + upper column) | claims | `claim_amount >= 0.01 AND claim_amount <= max_coverage` | `max_coverage REAL NOT NULL` |
| P33 (conditional arithmetic by type) | claims | `(claim_type IN ('medical', 'accident') AND approved_amount = claim_amount - deductible_applied) OR (claim_type IN ('property_damage', 'theft') AND approved_amount = claim_amount - deductible_applied * 0.5)` | — |
| P35 (conditional NULL with IN set) | claims | `status IN ('filed', 'reviewed') OR approved_amount IS NULL` | — |

Note: `max_coverage` is a denormalized copy of `policies.coverage_amount`,
populated at insert time. This avoids cross-table references in CHECK
constraints (not portable to PostgreSQL).

### R8 IoT (8 patterns)

| Pattern | Table | CHECK Constraint |
|---------|-------|-----------------|
| P8b (lower column + upper literal) | sensors | `calibration >= min_threshold AND calibration <= 100.0` |
| P8c (exclusive lower literal + exclusive upper column) | sensor_readings | `value > 0.0 AND value < max_range` |
| P8d (exclusive lower column + exclusive upper literal) | sensor_readings | `raw_value > min_raw AND raw_value < 999999.0` |
| P13 (abs second operand) | sensors | `offset_value = sensitivity * abs(calibration_delta)` |
| P14 (abs both operands) | firmware_versions | `delta = abs(version_from) * abs(version_to)` |
| P20 (range membership) | device_types | `is_normal = 0 OR test_value < ref_low OR test_value > ref_high` |
| P22b (compound range with multiplier) | firmware_versions | `size_mb >= 1.0 AND size_mb <= max_size * 1.5` |
| P25 (multiplication + addition chain) | devices | `total_cost = unit_price * quantity + shipping_cost` |

### Pattern Coverage Summary After Enhancement

All 36+ patterns (including sub-patterns 8a-8e, 22b) are covered.

## Section 4: Structure & Field Type Gap Filling (Layer 4 + Layer 5)

### 4.1 Logical Structures

| Structure | Database | Implementation | Compatibility |
|-----------|----------|----------------|---------------|
| Composite FK | R3 | routes: `UNIQUE(origin_wh_id, dest_wh_id)`; shipments: `FOREIGN KEY (origin_wh_id, dest_wh_id) REFERENCES routes(origin_wh_id, dest_wh_id)` | SQLite+PG |
| Generated column | R3 | packages: `volume_cbm GENERATED ALWAYS AS (length_cm * width_cm * height_cm / 1000000.0) STORED`; remove old CHECK | SQLite 3.31+ + PG 12+ |
| CASE WHEN CHECK | R6 | accounts: `CHECK (CASE WHEN account_type = 'credit' THEN balance >= -overdraft_limit ELSE balance >= 0 END)` | SQLite+PG |
| Date arithmetic CHECK | R6 | loans: `CHECK (maturity_date - disbursed_at >= 30)` (day difference, both DBs) | SQLite+PG |
| COALESCE CHECK | R2 | patients: `CHECK (COALESCE(emergency_phone, phone) IS NOT NULL)` | SQLite+PG |
| String function CHECK | R1 | brands: `CHECK (UPPER(country) = country)` | SQLite+PG |
| String function CHECK | R4 | users: `CHECK (LOWER(email) = email)` | SQLite+PG |
| Partial unique index | R5 | `CREATE UNIQUE INDEX idx_enroll_active ON enrollments(student_id, course_id) WHERE status = 'active'` | SQLite+PG |
| ON DELETE SET NULL | R1 | products: `FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE SET NULL` | SQLite+PG |
| ON DELETE SET NULL | R6 | transactions: `FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE SET NULL` | SQLite+PG |
| ON UPDATE CASCADE | R8 | R8 devices → device_types FK | PG |
| Nested AND/OR (3+ levels) | R8 | Complex business rule in maintenance_logs | SQLite+PG |
| Exclusion constraint | R8 | deployment_sessions: `EXCLUDE USING gist (device_id WITH =, time_range WITH &&)` | PG |
| Expression index | R8 | `CREATE INDEX idx_devices_name_lower ON devices (lower(name))` | PG |
| Full-text search index | R8 | `CREATE INDEX idx_telemetry_search ON telemetry_events USING gin(search_vector)` | PG |

**Note on generated columns:** sqlseed's data generator must skip generated
columns during data generation (they are auto-computed by the database). This
tests the generator's ability to handle generated columns correctly.

### 4.2 Business Field Types

| Field Type | Database | Column | Generator | Compatibility |
|-----------|----------|--------|-----------|---------------|
| UUID | R4 | tenants.tenant_uuid | uuid (TEXT storage) | SQLite+PG |
| Latitude | R3 | warehouses.latitude | latitude (REAL) | SQLite+PG |
| Longitude | R3 | warehouses.longitude | longitude (REAL) | SQLite+PG |
| VIN | R3 | vehicles.vin | vin (TEXT, 17 chars) | SQLite+PG |
| ISBN | R5 | courses.isbn | isbn (TEXT) | SQLite+PG |
| Color code | R1 | product_skus.color_code | hex_color (TEXT, #RRGGBB) | SQLite+PG |
| IBAN | R6 | accounts.iban | iban (TEXT) | SQLite+PG |
| Slug | R5 | courses.slug | slug (TEXT, kebab-case) | SQLite+PG |
| Passport | R6 | customers.passport_no | passport (TEXT, nullable) | SQLite+PG |
| SSN | R6 | customers.ssn | ssn (TEXT, nullable) | SQLite+PG |
| JSON metadata | R4 | organizations.metadata | json (TEXT storing JSON) | SQLite+PG |
| MAC address | R8 | devices.mac | mac_address (PG: macaddr type) | PG |
| MIME type | R8 | telemetry_events.mime_type | mime_type (TEXT) | PG |
| JSONB | R8 | device_types.specs, devices.config | jsonb (PG native) | PG |
| inet/cidr | R8 | networks.subnet (cidr), gateways.ip (inet) | inet/cidr (PG native) | PG |
| interval | R8 | maintenance_logs.labor_time, deployment_sessions.duration | interval (PG native) | PG |
| Array | R8 | devices.tags (text[]), device_groups.member_ids (integer[]) | array (PG native) | PG |
| tsvector | R8 | telemetry_events.search_vector | tsvector (PG native) | PG |
| uuid (native) | R8 | devices.id (uuid DEFAULT gen_random_uuid()) | uuid (PG native) | PG |

## Section 5: R8 PostgreSQL-Specific Database (Layer 6)

### Domain: IoT Device Management & Telemetry Platform

Natural fit for all PG-specific types: JSONB (sensor configs), arrays (tags),
inet/cidr (networks), interval (uptime/duration), uuid (device IDs), tsvector
(full-text search), macaddr (MAC addresses).

### Tables (12 tables)

1. **device_types** — type hierarchy, JSONB specs, Pattern 20
2. **devices** — uuid PK, macaddr, inet ip, JSONB config, text[] tags,
   expression index, Pattern 25, ON UPDATE CASCADE
3. **sensors** — device sub-component, JSONB calibration, Pattern 13, Pattern 8b
4. **sensor_readings** — time-series data, JSONB payload, Pattern 8c, Pattern 8d
5. **firmware_versions** — version management, text[] compatible_models,
   Pattern 14, Pattern 22b
6. **deployment_sessions** — time ranges with EXCLUDE constraint, interval duration
7. **alerts** — alert management, JSONB context, tsvector search_vector
8. **maintenance_logs** — maintenance records, interval labor_time, nested AND/OR
9. **networks** — network configuration, cidr subnet
10. **gateways** — network gateways, inet ip, macaddr
11. **telemetry_events** — events with tsvector, JSONB metadata, MIME type
12. **device_groups** — grouping with array member_ids, JSONB rules

### R8 Coverage Summary

- **PG types (9):** uuid, JSONB, inet, cidr, macaddr, interval, text[], tsvector, tstzrange
- **PG structures (3):** exclusion constraint, expression index, full-text search index
- **Remaining patterns (8):** P8b, P8c, P8d, P13, P14, P20, P22b, P25
- **Remaining fields (2+):** MAC address, MIME type
- **Other structures:** ON UPDATE CASCADE, nested AND/OR (3+ levels)

### R8 Testing

R8 uses PG-specific types, only tested in PostgreSQL environment. Test scripts
use `@pytest.mark.postgresql` and skip when Docker/PG unavailable.

## Section 6: Summary & Validation Plan

### 6.1 Change Summary (Per Database)

| DB | Bug Fix | PG Compat | New Patterns | New Structures | New Fields |
|----|---------|-----------|-------------|----------------|------------|
| R1 | — | Remove PRAGMA | P4, P22, P26 | String func CHECK, ON DELETE SET NULL | Color code |
| R2 | — | Remove PRAGMA | P19, P21, P30 | COALESCE CHECK | — |
| R3 | — | Remove PRAGMA | P8a, P9, P15 | Composite FK, Generated column | Lat/lng, VIN |
| R4 | Remove subquery CHECK, plans self-ref, fix comment | Remove PRAGMA | P24, P31, P34 | String func CHECK | UUID, JSON metadata |
| R5 | Move coupons before orders | Remove PRAGMA | P23, P27, P35 | Partial unique index | ISBN, Slug |
| R6 | Simplify date arithmetic | Remove PRAGMA, fix DATE() | P7, P12, P32 | CASE WHEN CHECK, Date arithmetic CHECK | IBAN, Passport, SSN |
| R7 | — | Remove PRAGMA | P8a, P33, P35 | — | — |
| R8 | — | PG only | P8b, P8c, P8d, P13, P14, P20, P22b, P25 | Exclusion, Expression index, FTS, ON UPDATE CASCADE, Nested AND/OR | MAC, MIME, JSONB, inet, cidr, interval, array, tsvector, uuid |

### 6.2 Post-Enhancement Coverage

**36+ patterns:** All covered (including sub-patterns 8a-8e, 22b)

**Logical structures (18 total):** Self-ref FK, Circular FK, State machine,
Conditional NULL, Cross-column arithmetic, Date ordering, Compound UNIQUE,
Multi-column CHECK (existing 8) + Composite FK, Generated column, CASE WHEN
CHECK, Date arithmetic CHECK, COALESCE CHECK, String function CHECK, Partial
unique index, ON DELETE SET NULL, ON UPDATE CASCADE, Exclusion constraint,
Expression index, Full-text search (new 10)

**Field types (27+ total):** email, phone, URL, date/datetime, id_card,
address, money, quantity, enum, barcode, license_no, postal, IP-LIKE (existing
13) + UUID, lat/lng, VIN, ISBN, color, IBAN, slug, MAC, passport, SSN, MIME,
JSON/JSONB, inet/cidr, interval, array, tsvector (new 14+)

### 6.3 Validation Plan

Each database must pass 4 validation levels:

1. **Schema validation:** SQLite + PostgreSQL (R8 PG only) can create all
   tables without syntax errors.
2. **Pattern recognition:** Each new CHECK constraint is correctly identified
   by `_infer_cross_column_config()` or `_parse_single_column_check()`. Verify
   via revalidation script (no LLM rerun needed for deterministic patterns).
3. **Fill validation:** `sqlseed fill` successfully fills all tables with 0
   FK/CHECK violations.
4. **Regression:** Existing Round 5-7 constraints remain unchanged (only
   additions, no modifications to existing CHECKs except R2 billing `<=` to
   `=` and R6 date arithmetic simplification).

### 6.4 Implementation Order

1. **Phase 1 — Bug fixes:** R5 forward reference, R4 subquery CHECK / self-ref / comment
2. **Phase 2 — PG compatibility:** Remove PRAGMA from all 7, simplify R6 date arithmetic
3. **Phase 3 — R1-R7 pattern gaps:** Add 2-3 missing patterns per database
4. **Phase 4 — R1-R7 structure gaps:** Composite FK, generated columns, CASE CHECK, partial indexes, etc.
5. **Phase 5 — R1-R7 field type gaps:** UUID, lat/lng, VIN, ISBN, etc.
6. **Phase 6 — R8 new database:** IoT domain, 12 tables, PG-specific types and structures
7. **Phase 7 — Full validation:** Schema + pattern recognition + fill + regression

## Constraints

- All changes on `feat/contract-driven-self-healing` branch (no merge to main
  until validated).
- Existing CHECK constraints in R1-R7 are preserved (only R2 billing `<=` to
  `=` and R6 date arithmetic are modified; all others are additions).
- R8 is PG-only; all other databases must work on both SQLite and PostgreSQL.
- No LLM rerun needed for pattern recognition validation (use revalidation
  script on generated YAML).
- Follow Loop Engineering methodology: observe → fix → revalidate → verify.
