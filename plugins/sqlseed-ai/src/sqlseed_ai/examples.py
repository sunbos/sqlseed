"""Few-shot examples for LLM schema analysis prompts.

This module holds :data:`FEW_SHOT_EXAMPLES`, a list of input/output pairs
that teach the Gemma 4 model how to map a SQL table schema (rendered as
markdown) to a sqlseed generation template (JSON). The examples cover
common patterns: basic columns, unique constraints, derived columns,
foreign keys, and composite unique indexes.
"""

from __future__ import annotations

import json

# Few-shot input/output pairs for the schema-analysis prompt.
# Each "input" is a markdown table schema; each "output" is the expected
# JSON generation template. Used to prime the LLM before analyzing a
# real table.
FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "input": """# Table: users
## Columns
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- name: VARCHAR(50) NOT NULL
- email: VARCHAR(100) NOT NULL
- status: INTEGER DEFAULT 1
- created_at: DATETIME
## Indexes
- UNIQUE INDEX (email)
## All Tables in Database
users, orders""",
        "output": json.dumps(
            {
                "name": "users",
                "count": 1000,
                "columns": [
                    {"name": "name", "generator": "name"},
                    {"name": "email", "generator": "email", "constraints": {"unique": True}},
                    {"name": "created_at", "generator": "datetime", "params": {"start_year": 2020, "end_year": 2025}},
                ],
            },
            indent=2,
        ),
    },
    {
        "input": """# Table: projects
## Columns
- projectId: INTEGER PRIMARY KEY AUTOINCREMENT
- project_no: VARCHAR(20) NOT NULL
- member_no: VARCHAR(32) NOT NULL
- short_code: VARCHAR(8)
- nStatus: INTEGER DEFAULT 0
- dCreateTime: DATETIME
## Indexes
- UNIQUE INDEX (project_no)
- UNIQUE INDEX (member_no)
## All Tables in Database
projects, user_info""",
        "output": json.dumps(
            {
                "name": "projects",
                "count": 1000,
                "columns": [
                    {
                        "name": "project_no",
                        "generator": "pattern",
                        "params": {"regex": "[0-9]{16}"},
                        "constraints": {"unique": True},
                    },
                    {
                        "name": "member_no",
                        "generator": "pattern",
                        "params": {"regex": "U[0-9]{10}"},
                        "constraints": {"unique": True},
                    },
                    {"name": "short_code", "derive_from": "project_no", "expression": "value[-6:]"},
                    {
                        "name": "dCreateTime",
                        "generator": "datetime",
                        "params": {"start_year": 2023, "end_year": 2025},
                    },
                ],
            },
            indent=2,
        ),
    },
    {
        "input": """# Table: orders
## Columns
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- user_id: INTEGER NOT NULL
- product_name: VARCHAR(100) NOT NULL
- quantity: INTEGER NOT NULL
- unit_price: FLOAT NOT NULL
- order_status: VARCHAR(20) NOT NULL
- order_date: DATE
- notes: TEXT
## Foreign Keys
- user_id → users.id
## Indexes
- INDEX (user_id)
## All Tables in Database
users, orders""",
        "output": json.dumps(
            {
                "name": "orders",
                "count": 5000,
                "columns": [
                    # NOTE: user_id is a foreign key column — DO NOT include it
                    # in the columns list. The sqlseed core auto-resolves FK
                    # columns by sampling existing parent-table ids.
                    {
                        "name": "product_name",
                        "generator": "word",
                    },
                    {
                        "name": "quantity",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 100},
                    },
                    {
                        "name": "unit_price",
                        "generator": "float",
                        "params": {"min_value": 0.99, "max_value": 999.99, "precision": 2},
                    },
                    {
                        "name": "order_status",
                        "generator": "choice",
                        "params": {
                            "choices": [
                                "pending",
                                "confirmed",
                                "shipped",
                                "delivered",
                                "cancelled",
                            ],
                        },
                    },
                    {
                        "name": "order_date",
                        "generator": "date",
                        "params": {"start_year": 2023, "end_year": 2025},
                    },
                ],
            },
            indent=2,
        ),
    },
    {
        "input": """# Table: employees
## Columns
- emp_id: INTEGER PRIMARY KEY AUTOINCREMENT
- dept_id: INTEGER NOT NULL
- first_name: VARCHAR(50) NOT NULL
- last_name: VARCHAR(50) NOT NULL
- hire_date: DATE NOT NULL
- salary: INTEGER NOT NULL
- is_active: BOOLEAN
- metadata: TEXT
## Foreign Keys
- dept_id → departments.id
## Indexes
- UNIQUE INDEX (first_name, last_name)
## All Tables in Database
departments, employees""",
        "output": json.dumps(
            {
                "name": "employees",
                "count": 2000,
                "columns": [
                    # NOTE: dept_id is a foreign key column — DO NOT include it
                    # in the columns list. The sqlseed core auto-resolves FK
                    # columns by sampling existing parent-table ids.
                    {"name": "first_name", "generator": "first_name"},
                    {"name": "last_name", "generator": "last_name"},
                    {
                        "name": "hire_date",
                        "generator": "date",
                        "params": {"start_year": 2015, "end_year": 2025},
                    },
                    {
                        "name": "salary",
                        "generator": "integer",
                        "params": {"min_value": 30000, "max_value": 200000},
                    },
                    {"name": "is_active", "generator": "boolean"},
                ],
            },
            indent=2,
        ),
    },
    {
        "input": """# Table: merchants
## Columns
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- merchant_code: VARCHAR(20) NOT NULL
- merchant_name: VARCHAR(100) NOT NULL
- status: VARCHAR(20) NOT NULL
- created_at: DATETIME DEFAULT CURRENT_TIMESTAMP
## Indexes
- UNIQUE INDEX (merchant_code)
## CHECK Constraints
- status IN ('active', 'suspended', 'closed')
## All Tables in Database
merchants, users""",
        "output": json.dumps(
            {
                "name": "merchants",
                "count": 1000,
                "columns": [
                    {
                        "name": "merchant_code",
                        "generator": "template",
                        "params": {"template": "MER-{sequence:04d}"},
                        "constraints": {"unique": True},
                    },
                    {"name": "merchant_name", "generator": "company"},
                    {
                        "name": "status",
                        "generator": "weighted_choice",
                        "params": {"weighted_choices": {"active": 80, "suspended": 15, "closed": 5}},
                    },
                    # NOTE: created_at has DEFAULT CURRENT_TIMESTAMP → skip (auto-handled by core)
                ],
            },
            indent=2,
        ),
    },
    {
        "input": """# Table: order_items
## Columns
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- order_id: INTEGER NOT NULL
- product_id: INTEGER NOT NULL
- quantity: INTEGER NOT NULL
- price_per_unit: REAL NOT NULL
- discount: REAL NOT NULL
- item_total: REAL GENERATED ALWAYS AS (quantity * price_per_unit - discount) STORED
- created_at: DATETIME DEFAULT CURRENT_TIMESTAMP
## Foreign Keys
- order_id → orders.id
- product_id → products.id
## CHECK Constraints
- quantity > 0 AND quantity <= 5
- price_per_unit > 0
- discount >= 0 AND discount <= price_per_unit
## All Tables in Database
orders, products, order_items""",
        "output": json.dumps(
            {
                "name": "order_items",
                "count": 1000,
                "columns": [
                    # NOTE: order_id, product_id are FK columns → skip (auto-resolved by core)
                    {
                        "name": "quantity",
                        "generator": "integer",
                        "params": {"min_value": 1, "max_value": 5},
                    },
                    # P0 cross-table lookup: price_per_unit must equal products.sale_price
                    {
                        "name": "price_per_unit",
                        "derive_from": "product_id",
                        "expression": "lookup('products', 'sale_price', value)",
                    },
                    # P3 multi-column derive: discount scales with quantity (max at qty=5)
                    {
                        "name": "discount",
                        "derive_from": ["price_per_unit", "quantity"],
                        "expression": "round(value[0] * 0.05 * min(value[1], 5) / 5, 2)",
                    },
                    # NOTE: item_total is GENERATED → skip. created_at has DEFAULT → skip.
                ],
            },
            indent=2,
        ),
    },
]
