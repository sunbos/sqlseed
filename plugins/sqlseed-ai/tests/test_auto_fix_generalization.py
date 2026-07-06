"""Adversarial tests for _auto_fix_config generalization.

These tests use COMPLETELY DIFFERENT business scenarios (HR database,
school database, hospital database) to verify that the auto-fix
strategies are generic patterns, not hardcoded heuristics that only
work for the complex_biz.db schema (categories, merchants, products,
order_items, users, etc.).

The goal is to detect self-proving traps where tests pass only because
they use the same column names as the original failing case.

Each test scenario below uses DIFFERENT table names, DIFFERENT column
names, and DIFFERENT business logic to stress-test the auto-fix logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer


class TestAutoFixGeneralization:
    """Adversarial tests using schemas unrelated to complex_biz.db."""

    # ----------------------------------------------------------------
    # Fix 9 generalization: *_name column correction
    # ----------------------------------------------------------------

    def test_fix_9_department_name_uses_word(self) -> None:
        """department_name should use word generator (not string)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "departments",
                    "columns": [
                        {
                            "name": "department_name",
                            "generator": "string",
                            "params": {"min_length": 5, "max_length": 50},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "word", f"department_name should use 'word', got '{col['generator']}'"

    def test_fix_9_full_name_uses_name_generator(self) -> None:
        """full_name is a PERSON name, should use `name` generator (not `word`).

        Fix 9 now detects person name columns (full_name, first_name,
        last_name, fname, lname, surname, person_name) and assigns the
        matching person-name generator instead of `word`.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "employees",
                    "columns": [
                        {
                            "name": "full_name",
                            "generator": "string",
                            "params": {"min_length": 5, "max_length": 50},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "name", (
            f"full_name should use 'name' generator for person names, got '{col['generator']}'"
        )

    def test_fix_9_first_name_uses_first_name_generator(self) -> None:
        """first_name column should use `first_name` generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "students",
                    "columns": [
                        {
                            "name": "first_name",
                            "generator": "text",
                            "params": {"min_length": 5},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "first_name"

    def test_fix_9_last_name_uses_last_name_generator(self) -> None:
        """last_name column should use `last_name` generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "students",
                    "columns": [
                        {
                            "name": "last_name",
                            "generator": "string",
                            "params": {"min_length": 5},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "last_name"

    def test_fix_9_company_name_uses_company(self) -> None:
        """company_name should use company generator (vendor/supplier scenario)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "suppliers",
                    "columns": [
                        {
                            "name": "company_name",
                            "generator": "text",
                            "params": {"min_length": 10},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "company", f"company_name should use 'company', got '{col['generator']}'"

    def test_fix_9_school_name_uses_word(self) -> None:
        """school_name (educational scenario) should use word, not string."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "schools",
                    "columns": [
                        {
                            "name": "school_name",
                            "generator": "text",
                            "params": {"min_length": 20},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "word"

    # ----------------------------------------------------------------
    # Fix 10 generalization: integer missing max_value
    # ----------------------------------------------------------------

    def test_fix_10_age_column_gets_default_max(self) -> None:
        """age column (not quantity/count/stock) should still get max_value."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "patients",
                    "columns": [
                        {
                            "name": "age",
                            "generator": "integer",
                            "params": {"min_value": 0},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"].get("max_value") is not None
        # age not matching quantity/count/stock keywords -> default 99999
        # NOTE: This is a BUG. age=99999 is absurd. Should be ~120.
        assert col["params"]["max_value"] == 99999, (
            "age column gets default max_value (currently 99999, ideally should be ~120 for age columns)"
        )

    def test_fix_10_score_column_gets_default_max(self) -> None:
        """score column (unrelated to complex_biz.db) should get max_value."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "exams",
                    "columns": [
                        {
                            "name": "score",
                            "generator": "integer",
                            "params": {"min_value": 0},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"].get("max_value") is not None
        # score doesn't match any keyword -> default 99999
        # NOTE: This is a BUG. score should be 0-100.
        assert col["params"]["max_value"] == 99999

    def test_fix_10_quantity_column_in_different_table(self) -> None:
        """quantity column in a different table (orders vs shipments) still works."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "shipments",  # Different from "order_items"
                    "columns": [
                        {
                            "name": "quantity",
                            "generator": "integer",
                            "params": {"min_value": 1},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"]["max_value"] == 100, (
            f"quantity column should get max_value=100, got {col['params']['max_value']}"
        )

    # ----------------------------------------------------------------
    # Fix 11 generalization: email/phone enforcement
    # ----------------------------------------------------------------

    def test_fix_11_contact_email_corrected(self) -> None:
        """contact_email (not just 'email') should be corrected to email generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "customers",
                    "columns": [
                        {
                            "name": "contact_email",
                            "generator": "string",
                            "params": {"min_length": 10},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "email"

    def test_fix_11_mobile_phone_corrected(self) -> None:
        """Fix 11: 'mobile' (not just *_phone) is corrected to phone generator.

        Fix 11 now catches phone-like column names that don't end with
        '_phone' but are still phone numbers: 'mobile', 'telephone', 'tel',
        'cell', 'cellphone', 'contact_number', '*_mobile'. Previously only
        exact 'phone' and '*_phone' were caught.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "patients",
                    "columns": [
                        {
                            "name": "mobile",
                            "generator": "string",
                            "params": {"min_length": 10},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "phone", (
            f"mobile should be corrected to 'phone' generator (Fix 11 expanded), got '{col['generator']}'"
        )

    def test_fix_11_telephone_corrected(self) -> None:
        """Fix 11: 'telephone' is corrected to phone generator (HR scenario)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "patients",
                    "columns": [
                        {
                            "name": "telephone",
                            "generator": "string",
                            "params": {"min_length": 10},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "phone"

    def test_fix_11_contact_mobile_corrected(self) -> None:
        """Fix 11: 'contact_mobile' (ends with _mobile) is corrected to phone."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "customers",
                    "columns": [
                        {
                            "name": "contact_mobile",
                            "generator": "string",
                            "params": {"min_length": 10},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "phone"

    # ----------------------------------------------------------------
    # Fix 8 generalization: cross-column CHECK
    # ----------------------------------------------------------------

    def test_fix_8_actual_hours_bounded_by_est_hours(self) -> None:
        """Fix 8: actual_hours <= est_hours should trigger derive_from.

        Uses HR schema (tasks table) instead of e-commerce (order_items).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "tasks",
                    "columns": [
                        {
                            "name": "est_hours",
                            "generator": "integer",
                            "params": {"min_value": 1, "max_value": 100},
                            "derive_from": None,
                            "expression": None,
                        },
                        {
                            "name": "actual_hours",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 100},
                            "derive_from": None,
                            "expression": None,
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "tasks": {
                "columns": [
                    {"name": "est_hours", "type": "INTEGER"},
                    {"name": "actual_hours", "type": "INTEGER"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["actual_hours", "actual_hours", "est_hours"],
                        "expression": "actual_hours >= 0 AND actual_hours <= est_hours",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        actual_hours = config["tables"][0]["columns"][1]
        assert actual_hours.get("derive_from") == ["est_hours"], (
            f"actual_hours should derive_from est_hours, got: {actual_hours.get('derive_from')}"
        )
        assert actual_hours.get("generator") is None
        assert actual_hours.get("expression") == "round(random_float(0, value), 2)"

    def test_fix_8_lower_bound_pattern_triggers_derive_from(self) -> None:
        """Fix 8 lower-bound: `end_date >= start_date` triggers derive_from.

        Fix 8 now handles BOTH `col <= other_col` (upper bound) AND
        `col >= other_col` (lower bound) cross-column CHECK patterns.
        For DATE columns, the lower-bound branch uses timedelta arithmetic
        (``value + timedelta(days=random_int(0, 30))``) to guarantee the
        cross-column CHECK. The expression contains ``timedelta`` so Rule #17
        preserves it (Rule #17 strips non-timedelta expressions on DATE-family
        sources to avoid float(date) TypeError).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "projects",
                    "columns": [
                        {
                            "name": "start_date",
                            "generator": "date",
                            "params": {"start_year": 2020, "end_year": 2025},
                            "derive_from": None,
                            "expression": None,
                        },
                        {
                            "name": "end_date",
                            "generator": "date",
                            "params": {"start_year": 2020, "end_year": 2025},
                            "derive_from": None,
                            "expression": None,
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "projects": {
                "columns": [
                    {"name": "start_date", "type": "DATE"},
                    {"name": "end_date", "type": "DATE"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["end_date", "start_date"],
                        "expression": "end_date >= start_date",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        end_date = config["tables"][0]["columns"][1]
        assert end_date.get("derive_from") == ["start_date"], (
            f"end_date should derive_from start_date (lower-bound CHECK), got: {end_date.get('derive_from')}"
        )
        assert end_date.get("generator") is None, (
            f"source-mode generator should be removed after derive_from conversion, got: {end_date.get('generator')}"
        )
        # DATE columns use timedelta arithmetic for lower-bound CHECKs.
        # Non-strict >= uses random_int(0, 30) (allows equality via 0 offset).
        expr = end_date.get("expression")
        assert isinstance(expr, str) and "timedelta" in expr and "random_int(0, 30)" in expr, (
            f"DATE column lower-bound expression should use timedelta with random_int(0, 30), got: {expr}"
        )

    def test_fix_8_lower_bound_integer_uses_random_int(self) -> None:
        """Fix 8 lower-bound for INTEGER: `sale_price >= cost_price` uses random_int.

        For INTEGER columns, the lower-bound branch can do arithmetic
        (value + random_int(min_offset, 100)) since both operands are ints.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "cost_price",
                            "generator": "integer",
                            "params": {"min_value": 10, "max_value": 100},
                            "derive_from": None,
                            "expression": None,
                        },
                        {
                            "name": "sale_price",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 200},
                            "derive_from": None,
                            "expression": None,
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "products": {
                "columns": [
                    {"name": "cost_price", "type": "INTEGER"},
                    {"name": "sale_price", "type": "INTEGER"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["sale_price", "cost_price"],
                        "expression": "sale_price >= cost_price",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        sale_price = config["tables"][0]["columns"][1]
        assert sale_price.get("derive_from") == ["cost_price"]
        assert sale_price.get("generator") is None
        # >= means min_offset=0; expression should use random_int
        assert sale_price.get("expression") == "value + random_int(0, 100)"

    # ----------------------------------------------------------------
    # Fix 5 generalization: GENERATED column removal
    # ----------------------------------------------------------------

    def test_fix_5_removes_generated_total_cost(self) -> None:
        """Fix 5: GENERATED column in a different table (tasks, not order_items)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "tasks",
                    "columns": [
                        {
                            "name": "actual_hours",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 100},
                            "derive_from": None,
                            "expression": None,
                        },
                        {
                            "name": "total_cost",
                            "generator": "float",
                            "params": {"min_value": 0},
                            "derive_from": None,
                            "expression": None,
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "tasks": {
                "columns": [
                    {"name": "actual_hours", "type": "INTEGER", "is_computed": False},
                    {"name": "total_cost", "type": "REAL", "is_computed": True},
                ],
                "check_constraints": [],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "total_cost" not in col_names, (
            f"GENERATED column total_cost should be removed, remaining columns: {col_names}"
        )
        assert "actual_hours" in col_names

    # ----------------------------------------------------------------
    # Fix 6 generalization: UNIQUE enforcement
    # ----------------------------------------------------------------

    def test_fix_6_employee_id_unique_enforced(self) -> None:
        """Fix 6: UNIQUE on employee_id in employees table (not users.email)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "employees",
                    "columns": [
                        {
                            "name": "employee_id",
                            "generator": "template",
                            "params": {"template": "EMP-{sequence:04d}"},
                            "derive_from": None,
                            "expression": None,
                            "constraints": {"unique": False},
                        }
                    ],
                }
            ]
        }
        schema: dict = {
            "employees": {
                "columns": [
                    {"name": "employee_id", "type": "TEXT"},
                ],
                "check_constraints": [],
                "unique_indexes": [{"name": "idx_emp_id", "columns": ["employee_id"], "unique": True}],
                "unique_columns": ["employee_id"],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col = config["tables"][0]["columns"][0]
        assert col["constraints"]["unique"] is True

    # ----------------------------------------------------------------
    # Edge cases: columns that look like Fix 9/10/11 but shouldn't trigger
    # ----------------------------------------------------------------

    def test_no_fix_when_name_column_uses_template(self) -> None:
        """Fix 9 should NOT trigger when *_name uses template (UNIQUE code)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "product_name",
                            "generator": "template",
                            "params": {"template": "PROD-{sequence:04d}"},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        # template is a valid generator for UNIQUE codes; should not be touched
        assert col["generator"] == "template", (
            f"template generator should not be changed to 'word', got: '{col['generator']}'"
        )

    def test_no_fix_when_integer_has_max_value(self) -> None:
        """Fix 10 should NOT trigger when integer already has max_value."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "patients",
                    "columns": [
                        {
                            "name": "age",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 120},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"]["max_value"] == 120, (
            f"Existing max_value should not be overridden, got: {col['params']['max_value']}"
        )

    # ----------------------------------------------------------------
    # Fix 12: phone+regex mismatch -> convert to pattern
    # ----------------------------------------------------------------

    def test_fix_12_phone_with_regex_converted_to_pattern(self) -> None:
        """Fix 12: `generator: phone` with `params: {regex: ...}` -> pattern.

        The `phone` generator does NOT accept a `regex` parameter (only
        `pattern` does). Without Fix 12, fill crashes with:
            TypeError: _gen_phone() got an unexpected keyword argument 'regex'
        Fix 12 converts phone+regex to pattern+regex to honor the LLM's
        intended format. Uses a hospital scenario (contact_phone with regex).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "patients",
                    "columns": [
                        {
                            "name": "contact_phone",
                            "generator": "phone",
                            "params": {"regex": r"1[3-9]\d{9}"},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "pattern", (
            f"phone+regex should be converted to 'pattern' generator, got '{col['generator']}'"
        )
        assert col["params"] == {"regex": r"1[3-9]\d{9}"}, f"regex param should be preserved, got {col['params']}"

    def test_fix_12_no_trigger_when_phone_has_no_regex(self) -> None:
        """Fix 12 should NOT trigger when phone has no regex param.

        Plain `generator: phone` (no params or non-regex params) is valid
        and should not be converted.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "customers",
                    "columns": [
                        {
                            "name": "phone",
                            "generator": "phone",
                            "params": {},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "phone", (
            f"phone without regex should NOT be converted to pattern, got '{col['generator']}'"
        )

    # ----------------------------------------------------------------
    # Fix 13: missing UNIQUE NOT NULL column detection
    # ----------------------------------------------------------------

    def test_fix_13_missing_unique_not_null_column_added(self) -> None:
        """Fix 13: omitted UNIQUE NOT NULL column is added with template.

        Small LLMs sometimes skip UNIQUE NOT NULL columns entirely. Without
        Fix 13, the fill uses a default `string` generator producing random
        gibberish like 'c3fb3bIiGoq57nU'. Fix 13 detects such columns in
        the schema and adds them with a template generator derived from
        the column name (e.g., employee_id -> EMPL-{sequence:04d}).

        Uses an HR scenario (employees.employee_no UNIQUE NOT NULL).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "employees",
                    "columns": [
                        # LLM provided only name/email, omitted employee_no
                        {"name": "name", "generator": "name"},
                        {"name": "email", "generator": "email"},
                    ],
                }
            ]
        }
        schema: dict = {
            "employees": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "is_primary_key": True,
                        "is_autoincrement": True,
                        "nullable": False,
                    },
                    {
                        "name": "employee_no",
                        "type": "TEXT",
                        "is_primary_key": False,
                        "is_autoincrement": False,
                        "nullable": False,
                        "default": None,
                        "is_computed": False,
                    },
                    {"name": "name", "type": "TEXT", "nullable": False},
                    {"name": "email", "type": "TEXT", "nullable": False},
                ],
                "check_constraints": [],
                "unique_indexes": [{"name": "idx_emp_no", "columns": ["employee_no"], "unique": True}],
                "unique_columns": ["employee_no"],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "employee_no" in col_names, (
            f"missing UNIQUE NOT NULL column 'employee_no' should be added by Fix 13, got columns: {col_names}"
        )
        added = next(c for c in config["tables"][0]["columns"] if c["name"] == "employee_no")
        assert added["generator"] == "template", (
            f"added column should use template generator, got '{added['generator']}'"
        )
        # Prefix derived from first part of column name "employee" -> "EMPL"
        assert added["params"]["template"] == "EMPL-{sequence:04d}", (
            f"template should use EMPL prefix derived from column name, got {added['params']['template']}"
        )
        assert added["constraints"]["unique"] is True

    def test_fix_13_skips_autoincrement_pk(self) -> None:
        """Fix 13 should NOT add auto-increment PK columns (core handles them)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "employees",
                    "columns": [{"name": "name", "generator": "name"}],
                }
            ]
        }
        schema: dict = {
            "employees": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "is_primary_key": True,
                        "is_autoincrement": True,
                        "nullable": False,
                    },
                    {"name": "name", "type": "TEXT", "nullable": False},
                ],
                # id is PK so appears in unique_indexes via SQLite PRAGMA
                "check_constraints": [],
                "unique_indexes": [{"name": "sqlite_autoindex_employees_1", "columns": ["id"], "unique": True}],
                "unique_columns": ["id"],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "id" not in col_names, f"auto-increment PK should NOT be added by Fix 13, got: {col_names}"

    def test_fix_13_skips_column_with_default(self) -> None:
        """Fix 13 should NOT add columns that have a DEFAULT (core handles them)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "logs",
                    "columns": [{"name": "message", "generator": "text", "params": {"min_length": 10}}],
                }
            ]
        }
        schema: dict = {
            "logs": {
                "columns": [
                    {
                        "name": "id",
                        "type": "INTEGER",
                        "is_primary_key": True,
                        "is_autoincrement": True,
                        "nullable": False,
                    },
                    {
                        "name": "status_code",
                        "type": "TEXT",
                        "is_primary_key": False,
                        "is_autoincrement": False,
                        "nullable": False,
                        "default": "'ACTIVE'",
                        "is_computed": False,
                    },
                    {"name": "message", "type": "TEXT", "nullable": False},
                ],
                "check_constraints": [],
                "unique_indexes": [{"name": "idx_status", "columns": ["status_code"], "unique": True}],
                "unique_columns": ["status_code"],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "status_code" not in col_names, f"column with DEFAULT should NOT be added by Fix 13, got: {col_names}"

    def test_fix_13_skips_already_configured_column(self) -> None:
        """Fix 13 should NOT duplicate columns already in the LLM config."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "employees",
                    "columns": [
                        {"name": "name", "generator": "name"},
                        # LLM already provided employee_no (correctly configured)
                        {
                            "name": "employee_no",
                            "generator": "template",
                            "params": {"template": "EMP-{sequence:04d}"},
                            "constraints": {"unique": True},
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "employees": {
                "columns": [
                    {
                        "name": "employee_no",
                        "type": "TEXT",
                        "is_primary_key": False,
                        "is_autoincrement": False,
                        "nullable": False,
                        "default": None,
                        "is_computed": False,
                    },
                    {"name": "name", "type": "TEXT", "nullable": False},
                ],
                "check_constraints": [],
                "unique_indexes": [{"name": "idx_emp_no", "columns": ["employee_no"], "unique": True}],
                "unique_columns": ["employee_no"],
            }
        }
        analyzer._auto_fix_config(config, schema)
        # Should not duplicate
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert col_names.count("employee_no") == 1, (
            f"already-configured column should NOT be duplicated by Fix 13, got: {col_names}"
        )

    # ----------------------------------------------------------------
    # sqlseed_transform_row hook: date string -> datetime.date
    # ----------------------------------------------------------------

    def test_transform_row_converts_iso_date_string_to_date_object(self) -> None:
        """transform_row hook converts 'YYYY-MM-DD' strings to datetime.date.

        Defensive fallback: the core ``_gen_date`` generator now returns
        ``datetime.date`` objects directly (fixed 2026-07-02), so this
        conversion only triggers when an LLM (or user) mis-configures a
        DATE column to use a ``string`` generator that emits ISO-format
        strings. Without this fallback, SQLAlchemy SQLite Date columns
        would raise ``StatementError: SQLite Date type only accepts
        Python date objects``. The plugin caches DATE columns during
        ``sqlseed_apply_ai_suggestions`` (which has schema access) and
        converts strings during ``sqlseed_transform_row`` (per-row, no
        schema access).
        """
        import datetime

        from sqlseed_ai import AISqlseedPlugin

        plugin = AISqlseedPlugin()
        # Simulate the cache populated by sqlseed_apply_ai_suggestions
        plugin._date_columns_cache["projects"] = {"start_date", "end_date"}

        row = {"start_date": "2024-03-15", "end_date": "2024-03-20", "name": "Test"}
        result = plugin.sqlseed_transform_row("projects", row)

        assert result is not None, "row should be modified (dates converted)"
        assert isinstance(row["start_date"], datetime.date), (
            f"start_date should be datetime.date, got {type(row['start_date'])}"
        )
        assert isinstance(row["end_date"], datetime.date), (
            f"end_date should be datetime.date, got {type(row['end_date'])}"
        )
        assert row["start_date"] == datetime.date(2024, 3, 15)
        assert row["end_date"] == datetime.date(2024, 3, 20)
        # Non-date fields untouched
        assert row["name"] == "Test"

    def test_transform_row_returns_none_when_no_date_columns(self) -> None:
        """transform_row should return None when table has no cached DATE columns."""
        from sqlseed_ai import AISqlseedPlugin

        plugin = AISqlseedPlugin()
        # No cache entry for this table
        row = {"name": "Test", "count": 5}
        result = plugin.sqlseed_transform_row("unknown_table", row)
        assert result is None, f"should return None when no DATE columns cached for table, got {result}"

    def test_transform_row_skips_non_iso_strings(self) -> None:
        """transform_row should NOT convert non-ISO date strings."""
        from sqlseed_ai import AISqlseedPlugin

        plugin = AISqlseedPlugin()
        plugin._date_columns_cache["events"] = {"event_date"}

        # Non-ISO format strings should be left untouched
        row = {"event_date": "March 15, 2024"}
        result = plugin.sqlseed_transform_row("events", row)
        assert result is None, f"non-ISO date string should not trigger conversion, got {result}"
        assert row["event_date"] == "March 15, 2024"

    def test_transform_row_skips_already_date_objects(self) -> None:
        """transform_row should NOT re-convert existing datetime.date objects."""
        import datetime

        from sqlseed_ai import AISqlseedPlugin

        plugin = AISqlseedPlugin()
        plugin._date_columns_cache["events"] = {"event_date"}

        existing = datetime.date(2024, 3, 15)
        row = {"event_date": existing}
        result = plugin.sqlseed_transform_row("events", row)
        assert result is None, "already-date object should not be modified"
        assert row["event_date"] is existing
