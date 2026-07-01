# E2E Generation Report

## 1. Row Counts

### complex_biz.db

| Table | Rows | Status |
|-------|------|--------|
| categories | 100 | OK |
| items | 0 | FAIL |
| merchants | 100 | OK |
| order_items | 100 | OK |
| orders | 100 | OK |
| products | 100 | OK |
| sales | 100 | OK |
| users | 100 | OK |

### hr_biz.db

| Table | Rows | Status |
|-------|------|--------|
| departments | 100 | OK |
| employees | 100 | OK |
| projects | 0 | FAIL |
| tasks | 0 | FAIL |

## 2. verify_business_logic

### complex_biz.db

```
======================================================================
  Schema-Driven Business Logic Verification
======================================================================

--- Row Counts ---
  categories: 100 rows
  items: 0 rows
  merchants: 100 rows
  order_items: 100 rows
  orders: 100 rows
  products: 100 rows
  sales: 100 rows
  users: 100 rows

--- CHECK Constraints ---

--- FK Integrity ---

--- UNIQUE Constraints ---

--- GENERATED Columns ---

--- Data Realism ---

======================================================================
  VERIFICATION RESULTS
======================================================================
  [CHECK    ] items.CHECK(price > 0): OK
             columns: ['price']
  [CHECK    ] items.CHECK(stock_count >= 0): OK
             columns: ['stock_count']
  [CHECK    ] merchants.CHECK(status IN ('active', 'suspended', 'closed')): OK
             columns: ['status', 'active', 'suspended', 'closed']
  [CHECK    ] order_items.CHECK(quantity > 0 AND quantity <= 5): OK
             columns: ['quantity']
  [CHECK    ] order_items.CHECK(price_per_unit > 0): OK
             columns: ['price_per_unit']
  [CHECK    ] order_items.CHECK(discount >= 0 AND discount <= price_per_unit): OK
             columns: ['discount', 'price_per_unit']
  [CHECK    ] orders.CHECK(order_status IN ('pending', 'paid', 'shipped', 'completed', 'refunded')): OK
             columns: ['order_status', 'pending', 'paid', 'shipped', 'completed', 'refunded']
  [CHECK    ] products.CHECK(cost_price > 0): OK
             columns: ['cost_price']
  [CHECK    ] products.CHECK(sale_price >= cost_price): OK
             columns: ['sale_price', 'cost_price']
  [CHECK    ] products.CHECK(stock >= 0): OK
             columns: ['stock']
  [CHECK    ] sales.CHECK(quantity_sold > 0): OK
             columns: ['quantity_sold']
  [CHECK    ] sales.CHECK(unit_price > 0): OK
             columns: ['unit_price']
  [CHECK    ] users.CHECK(length(phone) >= 10): OK
             columns: ['phone']
  [CHECK    ] users.CHECK(role IN ('admin', 'manager', 'staff')): OK
             columns: ['role', 'admin', 'manager', 'staff']
  [FK       ] FK items.category_id -> categories.id: OK
  [FK       ] FK order_items.product_id -> products.id: OK
  [FK       ] FK order_items.order_id -> orders.id: OK
  [FK       ] FK orders.merchant_id -> merchants.id: OK
  [FK       ] FK orders.user_id -> users.id: OK
  [FK       ] FK products.merchant_id -> merchants.id: OK
  [FK       ] FK sales.item_id -> items.id: FAIL (100)
  [FK       ] FK users.merchant_id -> merchants.id: OK
  [UNIQUE   ] UNIQUE categories.category_code: OK
  [UNIQUE   ] UNIQUE items.item_code: OK
  [UNIQUE   ] UNIQUE merchants.merchant_code: OK
  [UNIQUE   ] UNIQUE orders.order_no: OK
  [UNIQUE   ] UNIQUE products.sku: OK
  [UNIQUE   ] UNIQUE users.email: OK
  [UNIQUE   ] UNIQUE users.username: OK
  [GENERATED] GENERATED order_items.item_total: OK
             skipped: incomplete input
  [REALISM  ] REALISM sales.customer_email (not email format): OK

======================================================================
  TOTAL VIOLATIONS: 100
======================================================================

  Failed checks:
    - [FK] FK sales.item_id -> items.id: 100 violations

```

### hr_biz.db

```
======================================================================
  Schema-Driven Business Logic Verification
======================================================================

--- Row Counts ---
  departments: 100 rows
  employees: 100 rows
  projects: 0 rows
  tasks: 0 rows

--- CHECK Constraints ---

--- FK Integrity ---

--- UNIQUE Constraints ---

--- GENERATED Columns ---

--- Data Realism ---

======================================================================
  VERIFICATION RESULTS
======================================================================
  [CHECK    ] employees.CHECK(age >= 18 AND age <= 80): OK
             columns: ['age']
  [CHECK    ] employees.CHECK(salary >= 30000 AND salary <= 200000): OK
             columns: ['salary']
  [CHECK    ] projects.CHECK(budget >= 1000): OK
             columns: ['budget']
  [CHECK    ] projects.CHECK(end_date >= start_date): OK
             columns: ['end_date', 'start_date']
  [CHECK    ] tasks.CHECK(est_hours > 0): OK
             columns: ['est_hours']
  [CHECK    ] tasks.CHECK(actual_hours >= 0 AND actual_hours <= est_hours): OK
             columns: ['actual_hours', 'est_hours']
  [FK       ] FK employees.dept_id -> departments.id: OK
  [FK       ] FK projects.dept_id -> departments.id: OK
  [FK       ] FK tasks.assignee_id -> employees.id: OK
  [FK       ] FK tasks.project_id -> projects.id: OK
  [UNIQUE   ] UNIQUE departments.dept_code: OK
  [UNIQUE   ] UNIQUE employees.email: OK
  [UNIQUE   ] UNIQUE employees.employee_id: OK
  [UNIQUE   ] UNIQUE projects.project_code: OK
  [UNIQUE   ] UNIQUE tasks.task_no: OK
  [GENERATED] GENERATED tasks.total_cost: OK
             skipped: incomplete input

======================================================================
  TOTAL VIOLATIONS: 0
======================================================================

```


## 3. Cross-Column CHECK Pattern Coverage

| DB | Pattern | Table | Col | Expected | Actual | Status |
|----|---------|-------|-----|----------|--------|--------|
| complex_biz.db | C | merchants | status | generator in (choice, weighted_choice) | generator=weighted_choice | COVERED |
| complex_biz.db | C | orders | order_status | generator in (choice, weighted_choice) | generator=weighted_choice | COVERED |
| complex_biz.db | A | products | sale_price | derive_from=[cost_price] | derive_from=['cost_price'], generator=None | COVERED |
| complex_biz.db | C | users | role | generator in (choice, weighted_choice) | generator=weighted_choice | COVERED |
| hr_biz.db | D | employees | age | params.min_value=18, params.max_value=80 | params.min_value=18, params.max_value=80 | COVERED |
| hr_biz.db | D | employees | salary | params.min_value=30000, params.max_value=200000 | params.min_value=30000, params.max_value=200000 | COVERED |
| hr_biz.db | A | projects | end_date | derive_from=[start_date] | derive_from=['start_date'], generator=None | COVERED |

**Total: 7/7 covered, 0 gaps**
