# Data Quality Demo Coverage Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize 7 test databases (R1-R7) for comprehensive coverage of 36+ CHECK patterns, logical structures, field types, and SQLite+PostgreSQL compatibility; add R8 IoT database for PG-specific types.

**Architecture:** Layered enhancement — bug fixes first, then PG compatibility, then pattern/structure/field gap filling across existing databases, then new R8 PG-specific database, then full validation.

**Tech Stack:** SQL (SQLite + PostgreSQL compatible), Python (sqlseed test validation), pytest.

**Spec:** `docs/superpowers/specs/2026-07-09-data-quality-demo-coverage-design.md`

**Branch:** `feat/contract-driven-self-healing`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `data_quality_demo/r1_ecommerce.sql` | Modify | Bug fix (none), PG compat, P4/P22/P26, string CHECK, ON DELETE SET NULL, color_code |
| `data_quality_demo/r2_hospital.sql` | Modify | PG compat, P19/P21/P30, COALESCE CHECK |
| `data_quality_demo/r3_logistics.sql` | Modify | PG compat, P8a/P9/P15, composite FK, generated column, lat/lng, VIN |
| `data_quality_demo/r4_saas.sql` | Modify | Bug fix (subquery CHECK, self-ref, comment), PG compat, P24/P31/P34, string CHECK, UUID, JSON |
| `data_quality_demo/r5_education.sql` | Modify | Bug fix (forward ref), PG compat, P23/P27/P35, partial unique index, ISBN, slug |
| `data_quality_demo/r6_banking.sql` | Modify | Bug fix (date arithmetic), PG compat, P7/P12/P32, CASE CHECK, date arithmetic CHECK, IBAN, passport, SSN |
| `data_quality_demo/r7_insurance.sql` | Modify | PG compat, P8a/P33/P35, max_coverage column |
| `data_quality_demo/r8_iot.sql` | Create | New PG-specific IoT database (12 tables) |

---

## Task 1: R5 Forward Reference Bug Fix

**Files:**
- Modify: `data_quality_demo/r5_education.sql`

**Problem:** `orders` table (line 95) has `FOREIGN KEY (coupon_id) REFERENCES coupons(id)` but `coupons` table is defined at line 115, after `orders`. PostgreSQL requires referenced tables to exist first.

- [ ] **Step 1: Read current file structure**

Read `data_quality_demo/r5_education.sql` and note the table order. The `coupons` table (currently after `orders`) must be moved before `orders`.

- [ ] **Step 2: Move coupons table before orders**

Cut the entire `coupons` table definition (from `CREATE TABLE coupons (` to the closing `);`) and paste it immediately before the `CREATE TABLE orders (` statement.

- [ ] **Step 3: Verify table order**

The order should now be: users → categories → courses → lessons → enrollments → lesson_progress → **coupons** → orders → payments → reviews → certificates → instructor_profiles.

- [ ] **Step 4: Test SQLite build**

```bash
cd c:\Users\14435\Desktop\sqlseed
python -c "import sqlite3; conn=sqlite3.connect(':memory::'); conn.executescript(open('data_quality_demo/r5_education.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 5: Commit**

```bash
git add data_quality_demo/r5_education.sql
git commit -m "fix: move coupons table before orders in R5 to fix FK forward reference"
```

---

## Task 2: R4 Bug Fixes

**Files:**
- Modify: `data_quality_demo/r4_saas.sql`

- [ ] **Step 1: Fix comment table count**

Change line 1 from:
```sql
-- Round 4: SaaS Multi-Tenant Platform (12 tables)
```
to:
```sql
-- Round 4: SaaS Multi-Tenant Platform (13 tables)
```

- [ ] **Step 2: Remove plans self-referencing FK**

In the `plans` table, remove this line:
```sql
    FOREIGN KEY (id) REFERENCES plans(id),
```

- [ ] **Step 3: Remove first subquery CHECK from subscriptions**

In the `subscriptions` table, remove this CHECK constraint:
```sql
    CHECK (seat_amount = seat_count * (SELECT seat_price_monthly FROM plans WHERE id = plan_id) OR seat_amount = 0.0),
```

- [ ] **Step 4: Remove second subquery CHECK from subscriptions**

In the `subscriptions` table, remove this CHECK constraint:
```sql
    CHECK (billing_cycle != 'yearly' OR base_amount >= (SELECT base_price_yearly FROM plans WHERE id = plan_id))
```

- [ ] **Step 5: Verify the remaining CHECK constraints in subscriptions**

The subscriptions table should still have these CHECKs (all pure arithmetic, no subqueries):
```sql
    CHECK (current_period_end > current_period_start),
    CHECK (total_amount = (base_amount + seat_amount) * (1.0 - discount_rate)),
    CHECK (status != 'canceled' OR canceled_at IS NOT NULL),
    CHECK (status != 'expired' OR ended_at IS NOT NULL),
    CHECK (canceled_at IS NULL OR canceled_at >= started_at),
    CHECK (ended_at IS NULL OR ended_at >= current_period_end),
```

- [ ] **Step 6: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r4_saas.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 13 tables`

- [ ] **Step 7: Commit**

```bash
git add data_quality_demo/r4_saas.sql
git commit -m "fix: remove subquery CHECKs and plans self-ref FK in R4, fix table count"
```

---

## Task 3: PG Compatibility for All 7 Databases

**Files:**
- Modify: `data_quality_demo/r1_ecommerce.sql`
- Modify: `data_quality_demo/r2_hospital.sql`
- Modify: `data_quality_demo/r3_logistics.sql`
- Modify: `data_quality_demo/r4_saas.sql`
- Modify: `data_quality_demo/r5_education.sql`
- Modify: `data_quality_demo/r6_banking.sql`
- Modify: `data_quality_demo/r7_insurance.sql`

- [ ] **Step 1: Add compatibility header and remove PRAGMA from R1**

Replace the first lines of `r1_ecommerce.sql`:
```sql
-- Round 1: E-Commerce + Inventory System (12 tables)
-- Exercises: SKU management, order state machine, inventory deduction,
--             cross-column price constraints, conditional NULL, date ordering

PRAGMA foreign_keys = ON;
```
with:
```sql
-- Round 1: E-Commerce + Inventory System (12 tables)
-- Compatible: SQLite + PostgreSQL
-- Exercises: SKU management, order state machine, inventory deduction,
--             cross-column price constraints, conditional NULL, date ordering
-- Note: SQLite enables FK via PRAGMA foreign_keys=ON at connection time.
--       PostgreSQL enables FK by default. AUTOINCREMENT is SQLite syntax;
--       PG equivalent: GENERATED ALWAYS AS IDENTITY.
```

- [ ] **Step 2: Repeat for R2-R7**

Apply the same pattern to each of `r2_hospital.sql` through `r7_insurance.sql`:
1. Add `-- Compatible: SQLite + PostgreSQL` line after the first comment line.
2. Remove the `PRAGMA foreign_keys = ON;` line.
3. Add the same `-- Note:` block about FK and AUTOINCREMENT.

- [ ] **Step 3: Fix R6 date arithmetic**

In `r6_banking.sql`, find this CHECK in the `loan_payments` table:
```sql
    CHECK (paid_at IS NULL OR DATE(paid_at) >= due_date - DATE('30 days')),
```
Replace with:
```sql
    CHECK (paid_at IS NULL OR DATE(paid_at) >= due_date),
```

- [ ] **Step 4: Test all 7 databases build in SQLite**

```bash
python -c "
import sqlite3
for i in range(1, 8):
    f = f'data_quality_demo/r{i}_' + ['ecommerce','hospital','logistics','saas','education','banking','insurance'][i-1] + '.sql'
    conn = sqlite3.connect(':memory:')
    conn.executescript(open(f).read())
    n = len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall())
    print(f'R{i}: OK ({n} tables)')
    conn.close()
"
```

Expected: All 7 databases print OK with correct table counts (R1-R7: 12,12,12,13,12,12,12).

- [ ] **Step 5: Commit**

```bash
git add data_quality_demo/r1_ecommerce.sql data_quality_demo/r2_hospital.sql data_quality_demo/r3_logistics.sql data_quality_demo/r4_saas.sql data_quality_demo/r5_education.sql data_quality_demo/r6_banking.sql data_quality_demo/r7_insurance.sql
git commit -m "fix: remove PRAGMA and add PG compatibility headers to all 7 databases"
```

---

## Task 4: R1 E-Commerce Enhancement

**Files:**
- Modify: `data_quality_demo/r1_ecommerce.sql`

- [ ] **Step 1: Add Pattern 4 to order_items (line_total column)**

In the `order_items` table, add `line_total REAL` column after `subtotal`:
```sql
    subtotal REAL NOT NULL CHECK (subtotal >= 0.0),
    line_total REAL,
```
And add CHECK after the existing `subtotal = unit_price * quantity` CHECK:
```sql
    CHECK (line_total IS NULL OR line_total = unit_price * quantity),
```

- [ ] **Step 2: Add Pattern 22 to orders (shipping cap)**

In the `orders` table, add this CHECK after the existing `discount_amount <= total_amount` CHECK:
```sql
    CHECK (shipping_fee <= total_amount * 0.3),
```

- [ ] **Step 3: Add Pattern 26 to products (conditional enum)**

In the `products` table, add `is_featured` column after `status`:
```sql
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'discontinued', 'recalled')),
    is_featured INTEGER NOT NULL DEFAULT 0 CHECK (is_featured IN (0, 1)),
```
And add CHECK:
```sql
    CHECK (is_featured = 0 OR status IN ('active', 'discontinued')),
```

- [ ] **Step 4: Add string function CHECK to brands**

In the `brands` table, add after the `country IN (...)` CHECK:
```sql
    CHECK (UPPER(country) = country),
```

- [ ] **Step 5: Change products.brand_id FK to ON DELETE SET NULL**

Find:
```sql
    FOREIGN KEY (brand_id) REFERENCES brands(id),
```
Replace with:
```sql
    FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE SET NULL,
```

- [ ] **Step 6: Add color_code to product_skus**

In the `product_skus` table, add after `barcode`:
```sql
    barcode TEXT UNIQUE,
    color_code TEXT CHECK (color_code IS NULL OR (color_code LIKE '#______' AND LENGTH(color_code) = 7)),
```

- [ ] **Step 7: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r1_ecommerce.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 8: Commit**

```bash
git add data_quality_demo/r1_ecommerce.sql
git commit -m "feat: add P4/P22/P26, string CHECK, ON DELETE SET NULL, color_code to R1"
```

---

## Task 5: R2 Hospital Enhancement

**Files:**
- Modify: `data_quality_demo/r2_hospital.sql`

- [ ] **Step 1: Add Pattern 19 to billing (change <= to =)**

Find in `billing` table:
```sql
    CHECK (insurance_covered + patient_paid <= total_price),
```
Replace with:
```sql
    CHECK (insurance_covered + patient_paid = total_price),
```

- [ ] **Step 2: Add Pattern 21 to medical_records (avg_bp column)**

In `medical_records`, add `avg_bp REAL` after `blood_pressure_low`:
```sql
    blood_pressure_low INTEGER CHECK (blood_pressure_low IS NULL OR (blood_pressure_low >= 40 AND blood_pressure_low <= 150)),
    avg_bp REAL,
```
And add CHECK after the `blood_pressure_low < blood_pressure_high` CHECK:
```sql
    CHECK (avg_bp IS NULL OR avg_bp = (blood_pressure_high + blood_pressure_low) / 2.0),
```

- [ ] **Step 3: Add Pattern 30 to prescriptions (conditional NULL)**

In `prescriptions`, add CHECK after the existing `dispensed_at >= prescribed_at` CHECK:
```sql
    CHECK (status != 'cancelled' OR dispensed_at IS NULL),
```

- [ ] **Step 4: Add COALESCE CHECK to patients**

In `patients`, add after the `emergency_phone` CHECK:
```sql
    CHECK (COALESCE(emergency_phone, phone) IS NOT NULL),
```

- [ ] **Step 5: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r2_hospital.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 6: Commit**

```bash
git add data_quality_demo/r2_hospital.sql
git commit -m "feat: add P19/P21/P30, COALESCE CHECK to R2"
```

---

## Task 6: R3 Logistics Enhancement

**Files:**
- Modify: `data_quality_demo/r3_logistics.sql`

- [ ] **Step 1: Add Pattern 8a to packages (actual_weight, declared_weight)**

In `packages`, add after `weight_kg`:
```sql
    weight_kg REAL NOT NULL CHECK (weight_kg > 0.0),
    actual_weight REAL NOT NULL CHECK (actual_weight >= 0.1),
    declared_weight REAL NOT NULL CHECK (declared_weight >= 0.1),
```
And add CHECK:
```sql
    CHECK (actual_weight >= 0.1 AND actual_weight <= declared_weight),
```

- [ ] **Step 2: Add Pattern 9 and Pattern 15 to shipments**

In `shipments`, add after `delivered_at`:
```sql
    delivered_at DATETIME,
    estimated_delivery DATE,
    guaranteed_delivery DATE,
    billed_weight_kg REAL NOT NULL DEFAULT 0.0 CHECK (billed_weight_kg >= 0.0),
    weight_diff REAL NOT NULL DEFAULT 0.0,
```
And add CHECKs:
```sql
    CHECK (estimated_delivery IS NULL OR guaranteed_delivery IS NULL OR estimated_delivery < guaranteed_delivery),
    CHECK (weight_diff = abs(total_weight_kg - billed_weight_kg)),
```

- [ ] **Step 3: Add composite FK (routes UNIQUE + shipments composite FK)**

In `routes`, add after the existing CHECK constraints:
```sql
    UNIQUE (origin_wh_id, dest_wh_id)
```
(Add as a table-level constraint, not column-level.)

In `shipments`, add after the existing single-column FKs:
```sql
    FOREIGN KEY (origin_wh_id, dest_wh_id) REFERENCES routes(origin_wh_id, dest_wh_id),
```

- [ ] **Step 4: Convert packages.volume_cbm to generated column**

Find in `packages`:
```sql
    volume_cbm REAL NOT NULL,
```
Replace with:
```sql
    volume_cbm REAL GENERATED ALWAYS AS (length_cm * width_cm * height_cm / 1000000.0) STORED,
```

Find and remove this CHECK from `packages`:
```sql
    CHECK (volume_cbm = length_cm * width_cm * height_cm / 1000000.0),
```

- [ ] **Step 5: Add lat/lng to warehouses**

In `warehouses`, add after `address`:
```sql
    address TEXT NOT NULL,
    latitude REAL CHECK (latitude IS NULL OR (latitude >= -90.0 AND latitude <= 90.0)),
    longitude REAL CHECK (longitude IS NULL OR (longitude >= -180.0 AND longitude <= 180.0)),
```

- [ ] **Step 6: Add VIN to vehicles**

In `vehicles`, add after `plate_no`:
```sql
    plate_no TEXT NOT NULL UNIQUE,
    vin TEXT CHECK (vin IS NULL OR LENGTH(vin) = 17),
```

- [ ] **Step 7: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r3_logistics.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 8: Commit**

```bash
git add data_quality_demo/r3_logistics.sql
git commit -m "feat: add P8a/P9/P15, composite FK, generated column, lat/lng, VIN to R3"
```

---

## Task 7: R4 SaaS Enhancement

**Files:**
- Modify: `data_quality_demo/r4_saas.sql`

- [ ] **Step 1: Add Pattern 24 to users (conditional comparison)**

In `users`, add CHECK after the existing `password_changed_at` CHECK:
```sql
    CHECK (status = 'deleted' OR last_login_at IS NULL OR last_login_at >= activated_at),
```

- [ ] **Step 2: Add Pattern 31 to subscriptions (conditional equality)**

In `subscriptions`, add CHECK:
```sql
    CHECK (status != 'trialing' OR discount_rate = 0.0),
```

- [ ] **Step 3: Add Pattern 34 to subscriptions (conditional upper bound)**

In `subscriptions`, add CHECK:
```sql
    CHECK (status != 'suspended' OR seat_count < 1000),
```

- [ ] **Step 4: Add string function CHECK to users**

In `users`, add after the `phone` CHECK:
```sql
    CHECK (LOWER(email) = email),
```

- [ ] **Step 5: Add UUID to tenants**

In `tenants`, add after `tenant_code`:
```sql
    tenant_code TEXT NOT NULL UNIQUE,
    tenant_uuid TEXT NOT NULL UNIQUE CHECK (LENGTH(tenant_uuid) = 36),
```

- [ ] **Step 6: Add JSON metadata to organizations**

In `organizations`, add after `timezone`:
```sql
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    metadata TEXT,
```

- [ ] **Step 7: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r4_saas.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 13 tables`

- [ ] **Step 8: Commit**

```bash
git add data_quality_demo/r4_saas.sql
git commit -m "feat: add P24/P31/P34, string CHECK, UUID, JSON metadata to R4"
```

---

## Task 8: R5 Education Enhancement

**Files:**
- Modify: `data_quality_demo/r5_education.sql`

- [ ] **Step 1: Add Pattern 23 to courses (multi-column threshold)**

In `courses`, add `is_free` column after `status`:
```sql
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    is_free INTEGER NOT NULL DEFAULT 0 CHECK (is_free IN (0, 1)),
```
And add CHECK:
```sql
    CHECK (is_free = 1 OR price < 100 OR original_price IS NULL OR original_price < 200),
```

- [ ] **Step 2: Add Pattern 27 to enrollments (N-way conditional range)**

In `enrollments`, add CHECK:
```sql
    CHECK (status = 'active' AND progress_percent >= 0
           OR status = 'completed' AND progress_percent >= 100
           OR status = 'dropped' AND progress_percent < 100),
```

- [ ] **Step 3: Add Pattern 35 to enrollments (conditional NULL with IN set)**

In `enrollments`, add CHECK:
```sql
    CHECK (status IN ('dropped', 'refunded') OR completed_at IS NULL),
```

- [ ] **Step 4: Add partial unique index**

After all CREATE TABLE statements, add:
```sql
CREATE UNIQUE INDEX idx_enroll_active ON enrollments(student_id, course_id) WHERE status = 'active';
```

- [ ] **Step 5: Add ISBN and slug to courses**

In `courses`, add after `description`:
```sql
    description TEXT,
    isbn TEXT CHECK (isbn IS NULL OR LENGTH(isbn) >= 10),
    slug TEXT NOT NULL UNIQUE CHECK (slug LIKE '%-%'),
```

- [ ] **Step 6: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r5_education.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 7: Commit**

```bash
git add data_quality_demo/r5_education.sql
git commit -m "feat: add P23/P27/P35, partial unique index, ISBN, slug to R5"
```

---

## Task 9: R6 Banking Enhancement

**Files:**
- Modify: `data_quality_demo/r6_banking.sql`

- [ ] **Step 1: Add Pattern 7 to loans (arithmetic comparison)**

In `loans`, add CHECK:
```sql
    CHECK (total_payable >= principal * interest_rate),
```

- [ ] **Step 2: Add Pattern 12 to transactions (abs first operand)**

In `transactions`, add columns after `amount`:
```sql
    amount REAL NOT NULL CHECK (amount > 0.0),
    transfer_amount REAL NOT NULL DEFAULT 0.0,
    fee_rate REAL NOT NULL DEFAULT 0.0 CHECK (fee_rate >= 0.0),
    fee_amount REAL NOT NULL DEFAULT 0.0 CHECK (fee_amount >= 0.0),
```
And add CHECK:
```sql
    CHECK (fee_amount = abs(transfer_amount) * fee_rate),
```

- [ ] **Step 3: Add Pattern 32 to accounts (conditional value/NULL)**

In `accounts`, add `freeze_amount` column after `overdraft_limit`:
```sql
    overdraft_limit REAL NOT NULL DEFAULT 0.0 CHECK (overdraft_limit >= 0.0),
    freeze_amount REAL,
```
And add CHECK:
```sql
    CHECK ((status = 'frozen' AND freeze_amount > 0)
           OR (status IN ('active', 'closed') AND freeze_amount IS NULL)),
```

- [ ] **Step 4: Add CASE WHEN CHECK to accounts**

Add CHECK to `accounts`:
```sql
    CHECK (CASE WHEN account_type = 'credit' THEN balance >= -overdraft_limit ELSE balance >= 0 END),
```

- [ ] **Step 5: Add date arithmetic CHECK to loans**

Add CHECK to `loans`:
```sql
    CHECK (maturity_date - disbursed_at >= 30),
```

- [ ] **Step 6: Change transactions.card_id FK to ON DELETE SET NULL**

Find:
```sql
    FOREIGN KEY (card_id) REFERENCES cards(id),
```
Replace with:
```sql
    FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE SET NULL,
```

- [ ] **Step 7: Add IBAN, passport, SSN to respective tables**

In `accounts`, add after `account_no`:
```sql
    account_no TEXT NOT NULL UNIQUE,
    iban TEXT CHECK (iban IS NULL OR LENGTH(iban) >= 15),
```

In `customers`, add after `id_card_no`:
```sql
    id_card_no TEXT NOT NULL UNIQUE,
    passport_no TEXT,
    ssn TEXT,
```

- [ ] **Step 8: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r6_banking.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 9: Commit**

```bash
git add data_quality_demo/r6_banking.sql
git commit -m "feat: add P7/P12/P32, CASE CHECK, date arithmetic, IBAN, passport, SSN to R6"
```

---

## Task 10: R7 Insurance Enhancement

**Files:**
- Modify: `data_quality_demo/r7_insurance.sql`

- [ ] **Step 1: Add max_coverage column to claims**

In `claims`, add after `claim_amount`:
```sql
    claim_amount REAL NOT NULL CHECK (claim_amount >= 0.01),
    max_coverage REAL NOT NULL,
```

- [ ] **Step 2: Add Pattern 8a to claims**

Add CHECK to `claims`:
```sql
    CHECK (claim_amount >= 0.01 AND claim_amount <= max_coverage),
```

- [ ] **Step 3: Add Pattern 33 to claims (conditional arithmetic by type)**

Add CHECK to `claims`:
```sql
    CHECK (
        (claim_type IN ('medical', 'accident') AND approved_amount IS NULL OR approved_amount = claim_amount - deductible_applied)
        OR (claim_type IN ('property_damage', 'theft') AND approved_amount IS NULL OR approved_amount = claim_amount - deductible_applied * 0.5)
    ),
```

- [ ] **Step 4: Add Pattern 35 to claims (conditional NULL with IN set)**

Add CHECK to `claims`:
```sql
    CHECK (status IN ('filed', 'reviewed') OR approved_amount IS NULL),
```

- [ ] **Step 5: Test SQLite build**

```bash
python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('data_quality_demo/r7_insurance.sql').read()); print('OK:', len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()), 'tables')"
```

Expected: `OK: 12 tables`

- [ ] **Step 6: Commit**

```bash
git add data_quality_demo/r7_insurance.sql
git commit -m "feat: add P8a/P33/P35, max_coverage column to R7"
```

---

## Task 11: Create R8 IoT Database (PG-Specific)

**Files:**
- Create: `data_quality_demo/r8_iot.sql`

- [ ] **Step 1: Write R8 IoT database SQL file**

Create `data_quality_demo/r8_iot.sql` with 12 tables covering all PG-specific types and remaining patterns. The complete SQL is provided below — write it in one step.

```sql
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
```

- [ ] **Step 2: Commit**

```bash
git add data_quality_demo/r8_iot.sql
git commit -m "feat: add R8 IoT database with PG-specific types and patterns P8b/P8c/P8d/P13/P14/P20/P22b/P25"
```

---

## Task 12: Full SQLite Validation for R1-R7

**Files:**
- No file modifications — validation only

- [ ] **Step 1: Build all 7 databases in SQLite and verify table counts**

```bash
python -c "
import sqlite3
expected = {'r1_ecommerce': 12, 'r2_hospital': 12, 'r3_logistics': 12, 'r4_saas': 13, 'r5_education': 12, 'r6_banking': 12, 'r7_insurance': 12}
for name, count in expected.items():
    f = f'data_quality_demo/{name}.sql'
    conn = sqlite3.connect(':memory:')
    conn.executescript(open(f).read())
    actual = len(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall())
    status = 'OK' if actual == count else 'FAIL'
    print(f'{name}: {status} (expected {count}, got {actual})')
    conn.close()
"
```

Expected: All 7 print OK.

- [ ] **Step 2: Verify CHECK constraints count per database**

```bash
python -c "
import sqlite3
for name in ['r1_ecommerce', 'r2_hospital', 'r3_logistics', 'r4_saas', 'r5_education', 'r6_banking', 'r7_insurance']:
    f = f'data_quality_demo/{name}.sql'
    conn = sqlite3.connect(':memory:')
    conn.executescript(open(f).read())
    sql = open(f).read()
    check_count = sql.count('CHECK (') + sql.count('CHECK(')
    print(f'{name}: {check_count} CHECK constraints')
    conn.close()
"
```

Verify each database has more CHECK constraints than before the enhancement.

---

## Task 13: Pattern Recognition Validation

**Files:**
- No file modifications — validation only

- [ ] **Step 1: Run ai-analyze on each database and verify pattern recognition**

For each database R1-R7, run the v4 auto-heal orchestrator and verify that the new CHECK constraints are correctly recognized:

```bash
# For each database, create a SQLite DB and run ai-analyze
python -c "
import sqlite3
# Build R1
conn = sqlite3.connect('/tmp/r1_test.db')
conn.executescript(open('data_quality_demo/r1_ecommerce.sql').read())
conn.close()
"
sqlseed ai-analyze /tmp/r1_test.db --output /tmp/r1_config.yaml
# Check the YAML for correct pattern recognition
```

- [ ] **Step 2: Verify each new pattern is recognized**

Check the generated YAML configs for each database:
- R1: line_total should have derive_from (P4), shipping_fee should have max_value from P22
- R2: avg_bp should have derive_from (P21), billing should have P19 reverse sum
- R3: actual_weight should have P8a, weight_diff should have abs (P15)
- R4: users should have P24, subscriptions should have P31/P34
- R5: courses should have P23, enrollments should have P27/P35
- R6: loans should have P7, transactions should have P12, accounts should have P32
- R7: claims should have P8a/P33/P35

---

## Task 14: Fill Validation

**Files:**
- No file modifications — validation only

- [ ] **Step 1: Fill each database with sqlseed and verify 0 violations**

For each database R1-R7:
```bash
# Build DB
python -c "
import sqlite3
conn = sqlite3.connect('/tmp/r1_fill.db')
conn.executescript(open('data_quality_demo/r1_ecommerce.sql').read())
conn.close()
"
# Fill with 1000 rows per table
sqlseed fill /tmp/r1_fill.db --config /tmp/r1_config.yaml -n 1000
# Verify no violations
python -c "
import sqlite3
conn = sqlite3.connect('/tmp/r1_fill.db')
# Check FK integrity
fk_violations = conn.execute('PRAGMA foreign_key_check').fetchall()
print(f'FK violations: {len(fk_violations)}')
conn.close()
"
```

Expected: 0 FK violations for each database.

- [ ] **Step 2: Repeat for R2-R7**

Repeat the fill and verify process for each database.

- [ ] **Step 3: Commit validation results (if any fixups were needed)**

If any fill failures required fixing the SQL:
```bash
git add data_quality_demo/*.sql
git commit -m "fix: adjust CHECK constraints based on fill validation results"
```

---

## Self-Review Checklist

After completing all tasks, verify:

- [ ] All 36+ CHECK patterns are covered across R1-R8
- [ ] All 18 logical structures are covered
- [ ] All 27+ field types are covered
- [ ] R1-R7 build successfully in SQLite
- [ ] R1-R7 are PostgreSQL-compatible (no PRAGMA, no subquery CHECK, no SQLite-only date math)
- [ ] R8 builds successfully in PostgreSQL (requires PG environment)
- [ ] Each new CHECK constraint is correctly recognized by the v4 pattern matcher
- [ ] sqlseed fill succeeds with 0 FK/CHECK violations for all databases
- [ ] Existing Round 5-7 regression baseline is not broken
