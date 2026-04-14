from __future__ import annotations

import json

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

        "output": json.dumps({
            "name": "users",
            "count": 1000,
            "columns": [
                {"name": "name", "generator": "name"},
                {"name": "email", "generator": "email", "constraints": {"unique": True}},
                {"name": "created_at", "generator": "datetime", "params": {"start_year": 2020, "end_year": 2025}},
            ]
        }, indent=2),
    },
    {
        "input": """# Table: bank_cards
## Columns
- cardId: INTEGER PRIMARY KEY AUTOINCREMENT
- card_number: VARCHAR(20) NOT NULL
- account_id: VARCHAR(32) NOT NULL
- last_eight: VARCHAR(8)
- nStatus: INTEGER DEFAULT 0
- dCreateTime: DATETIME
## Indexes
- UNIQUE INDEX (card_number)
- UNIQUE INDEX (account_id)
## All Tables in Database
bank_cards, user_info""",

        "output": json.dumps({
            "name": "bank_cards",
            "count": 1000,
            "columns": [
                {
                    "name": "card_number",
                    "generator": "pattern",
                    "params": {"regex": "[0-9]{16}"},
                    "constraints": {"unique": True},
                },
                {
                    "name": "account_id",
                    "generator": "pattern",
                    "params": {"regex": "U[0-9]{10}"},
                    "constraints": {"unique": True},
                },
                {"name": "last_eight", "derive_from": "card_number", "expression": "value[-8:]"},
                {
                    "name": "dCreateTime",
                    "generator": "datetime",
                    "params": {"start_year": 2023, "end_year": 2025},
                },
            ]
        }, indent=2),
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

        "output": json.dumps({
            "name": "orders",
            "count": 5000,
            "columns": [
                {
                    "name": "user_id",
                    "generator": "foreign_key",
                    "params": {"ref_table": "users", "ref_column": "id"},
                },
                {
                    "name": "product_name",
                    "generator": "string",
                    "params": {"min_length": 5, "max_length": 50},
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
                            "pending", "confirmed",
                            "shipped", "delivered", "cancelled",
                        ],
                    },
                },
                {
                    "name": "order_date",
                    "generator": "date",
                    "params": {"start_year": 2023, "end_year": 2025},
                },
            ]
        }, indent=2),
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

        "output": json.dumps({
            "name": "employees",
            "count": 2000,
            "columns": [
                {
                    "name": "dept_id",
                    "generator": "foreign_key",
                    "params": {"ref_table": "departments", "ref_column": "id"},
                },
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
            ]
        }, indent=2),
    },
]
