"""Tests for SchemaSemanticAnalyzer."""
from __future__ import annotations

from unittest.mock import MagicMock

from sqlseed_ai.schema_analyzer import AnalysisRequest, SchemaSemanticAnalyzer


class TestSchemaSemanticAnalyzerStructure:
    """Test analyzer structure and request building."""

    def test_analyzer_creation(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        assert analyzer is not None

    def test_build_request_full_database(self) -> None:
        """Full database analysis: tables=None means all tables."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders", "items"]
        db.get_column_info.return_value = []
        db.get_foreign_keys.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=None)
        assert req.target_tables == ["users", "orders", "items"]
        assert req.context_tables == []

    def test_build_request_partial_with_deps(self) -> None:
        """Partial analysis with dependency resolution."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders", "items", "categories"]
        from sqlseed.database._protocol import ForeignKeyInfo
        db.get_foreign_keys.side_effect = lambda t: {
            "orders": [ForeignKeyInfo(column="user_id", ref_table="users", ref_column="id")],
            "users": [],
        }.get(t, [])
        db.get_column_info.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=["orders"])
        assert req.target_tables == ["orders"]
        assert "users" in req.context_tables

    def test_build_request_partial_no_deps(self) -> None:
        """Partial analysis without dependencies."""
        db = MagicMock()
        db.get_table_names.return_value = ["users", "orders"]
        db.get_column_info.return_value = []
        db.get_foreign_keys.return_value = []
        db.get_check_constraints.return_value = []
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = analyzer.build_request(db, tables=["orders"], include_dependencies=False)
        assert req.target_tables == ["orders"]
        assert req.context_tables == []


class TestSchemaSemanticAnalyzerPrompt:
    """Test LLM prompt construction with target/context separation."""

    def test_prompt_includes_target_tables(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["orders"],
            context_tables=["users"],
            all_tables_schema={
                "orders": {"columns": [{"name": "id", "type": "INTEGER"}], "foreign_keys": [], "check_constraints": []},
                "users": {"columns": [{"name": "id", "type": "INTEGER"}], "foreign_keys": [], "check_constraints": []},
            },
        )
        messages = analyzer._build_llm_messages(req)
        assert len(messages) >= 1
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "orders" in user_msg["content"]
        assert "GENERATE YAML" in user_msg["content"] or "generate" in user_msg["content"].lower()

    def test_prompt_marks_context_tables_as_do_not_generate(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["orders"],
            context_tables=["users", "merchants"],
            all_tables_schema={},
        )
        messages = analyzer._build_llm_messages(req)
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "DO NOT generate" in user_msg["content"] or "do not generate" in user_msg["content"].lower()
        assert "users" in user_msg["content"]
        assert "merchants" in user_msg["content"]

    def test_prompt_includes_check_constraints(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        req = AnalysisRequest(
            target_tables=["products"],
            context_tables=[],
            all_tables_schema={
                "products": {
                    "columns": [{"name": "price", "type": "REAL"}],
                    "foreign_keys": [],
                    "check_constraints": [
                        {"name": "chk_price", "columns": ["price"], "expression": "price >= 0"}
                    ],
                }
            },
        )
        messages = analyzer._build_llm_messages(req)
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "price >= 0" in user_msg["content"]
        assert "CHECK" in user_msg["content"] or "check" in user_msg["content"].lower()


class TestSchemaSemanticAnalyzerLLMCall:
    """Test LLM call delegation and output filtering."""

    def test_call_llm_delegates_to_analyzer(self) -> None:
        """_call_llm should delegate to SchemaAnalyzer._call_llm_once."""
        mock_config = MagicMock()
        analyzer = SchemaSemanticAnalyzer(config=mock_config)

        # Set the backing attribute directly because _analyzer is a property
        # without a setter (lazy-init). patch.object cannot override it.
        mock_sa = MagicMock()
        mock_sa._call_llm_once.return_value = {"tables": [{"name": "orders"}]}
        analyzer._sa = mock_sa

        messages = [{"role": "user", "content": "test"}]
        result = analyzer._call_llm(messages)

        assert result == {"tables": [{"name": "orders"}]}
        mock_sa._call_llm_once.assert_called_once_with(messages)

    def test_filter_to_targets_removes_context(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config_dict = {
            "tables": [
                {"name": "orders", "columns": []},
                {"name": "users", "columns": []},
            ]
        }
        result = analyzer._filter_to_targets(config_dict, ["orders"])
        assert len(result["tables"]) == 1
        assert result["tables"][0]["name"] == "orders"

    def test_filter_to_targets_keeps_all_when_all_targets(self) -> None:
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config_dict = {
            "tables": [
                {"name": "orders", "columns": []},
                {"name": "items", "columns": []},
            ]
        }
        result = analyzer._filter_to_targets(config_dict, ["orders", "items"])
        assert len(result["tables"]) == 2


class TestAutoFixConfig:
    """Tests for _auto_fix_config post-processing of LLM output.

    Small LLMs (e.g., Gemma 4 E2B, 2B params) sometimes violate the
    ColumnConfig mutual exclusivity rule by including both "generator"
    and "derive_from" in the same column, or confuse "choice" with
    "weighted_choice". These tests verify the deterministic fixes.
    """

    def test_strips_generator_when_both_generator_and_derive_from_present(self) -> None:
        """Mutual exclusivity violation: generator+params stripped, derive_from kept.

        Also verifies Fix 3: value[0] is replaced with value for single-column
        derive_from (the expression is auto-fixed after generator is stripped).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "discount",
                            "generator": "float",
                            "params": {"min_value": 0, "max_value": 1000},
                            "derive_from": ["price_per_unit"],
                            "expression": "round(random()*value[0],2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert "generator" not in col
        assert "params" not in col
        assert col["derive_from"] == ["price_per_unit"]
        # Fix 3: value[0] -> value for single-column derive_from
        assert col["expression"] == "round(random()*value,2)"

    def test_fixes_choice_to_weighted_choice_when_weighted_choices_present(self) -> None:
        """Generator 'choice' with weighted_choices in params fixed to 'weighted_choice'."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "role",
                            "generator": "choice",
                            "params": {"weighted_choices": {"admin": 50, "manager": 30, "staff": 20}},
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "weighted_choice"

    def test_clean_config_unchanged(self) -> None:
        """Config without violations is returned unchanged."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {"name": "sku", "generator": "template", "params": {"template": "PROD-{sequence:04d}"}},
                        {"name": "sale_price", "derive_from": "cost_price", "expression": "round(value*1.2,2)"},
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        cols = config["tables"][0]["columns"]
        assert cols[0]["generator"] == "template"
        assert "derive_from" not in cols[0] or cols[0].get("derive_from") is None
        assert cols[1].get("derive_from") == "cost_price"
        assert "generator" not in cols[1]

    def test_single_table_format(self) -> None:
        """Auto-fix works on single-table format (no 'tables' wrapper)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "name": "order_items",
            "columns": [
                {
                    "name": "item_total",
                    "generator": "float",
                    "params": {"min_value": 0},
                    "derive_from": ["quantity", "price_per_unit"],
                    "expression": "round(value[0]*value[1],2)",
                }
            ],
        }
        analyzer._auto_fix_config(config)
        col = config["columns"][0]
        assert "generator" not in col
        assert "params" not in col
        assert col["derive_from"] == ["quantity", "price_per_unit"]

    def test_multi_table_fixes_all_tables(self) -> None:
        """Auto-fix applied to all tables in multi-table config."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "orders",
                    "columns": [
                        {
                            "name": "total",
                            "generator": "float",
                            "params": {},
                            "derive_from": "subtotal",
                            "expression": "value*1.0",
                        }
                    ],
                },
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "discount",
                            "generator": "float",
                            "params": {"min_value": 0},
                            "derive_from": "price_per_unit",
                            "expression": "round(value*0.05,2)",
                        }
                    ],
                },
            ]
        }
        analyzer._auto_fix_config(config)
        for table in config["tables"]:
            for col in table["columns"]:
                assert "generator" not in col
                assert "params" not in col

    def test_fixes_value_index_zero_for_single_column_derive_from(self) -> None:
        """Single-column derive_from with value[0] in expression is fixed to value."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": ["cost_price"],
                            "expression": "round(value[0]*1.2,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value*1.2,2)"

    def test_value_index_zero_unchanged_for_multi_column_derive_from(self) -> None:
        """Multi-column derive_from keeps value[0] in expression (it's correct)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "item_total",
                            "derive_from": ["price_per_unit", "quantity"],
                            "expression": "round(value[0]*value[1],2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value[0]*value[1],2)"

    def test_replaces_source_column_name_with_value_string_derive_from(self) -> None:
        """Fix 4: LLM uses source column name instead of 'value' (string derive_from).

        Example: derive_from: cost_price, expression: round(cost_price*1.2,2)
        Fixed:  expression: round(value*1.2,2)
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": "cost_price",
                            "expression": "round(cost_price*1.2,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value*1.2,2)"

    def test_replaces_source_column_name_with_value_list_derive_from(self) -> None:
        """Fix 4: LLM uses source column name instead of 'value' (list derive_from).

        Example: derive_from: [cost_price], expression: round(cost_price*1.2,2)
        Fixed:  expression: round(value*1.2,2)
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": ["cost_price"],
                            "expression": "round(cost_price*1.2,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value*1.2,2)"

    def test_does_not_replace_when_value_already_used(self) -> None:
        """Fix 4: skip replacement when expression already uses 'value' keyword.

        If the LLM correctly used 'value', we must not replace the source column
        name even if it appears in the expression (e.g., as part of a longer
        identifier or as a function name).
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": "cost_price",
                            "expression": "round(value*1.2,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        # Expression unchanged: 'value' was already used correctly
        assert col["expression"] == "round(value*1.2,2)"

    def test_replaces_only_bare_column_name_not_substring(self) -> None:
        """Fix 4: word-boundary matching prevents partial replacements.

        If source column is 'price', it should NOT replace 'price' inside
        'price_per_unit' if that's the source. But if 'price' IS the source
        column, only bare 'price' (whole word) is replaced.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {
                            "name": "discount_price",
                            "derive_from": "price",
                            "expression": "round(price*0.9,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value*0.9,2)"

    def test_removes_generated_columns_from_config(self) -> None:
        """Fix 5: GENERATED columns (is_computed=True) are removed from config."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {"name": "quantity", "generator": "integer", "params": {"min_value": 1}},
                        {"name": "price_per_unit", "generator": "float", "params": {"min_value": 0.01}},
                        {"name": "item_total", "derive_from": ["quantity", "price_per_unit"],
                         "expression": "round(value[0]*value[1],2)"},
                    ],
                }
            ]
        }
        schema = {
            "order_items": {
                "columns": [
                    {"name": "quantity", "type": "INTEGER", "is_computed": False},
                    {"name": "price_per_unit", "type": "REAL", "is_computed": False},
                    {"name": "item_total", "type": "REAL", "is_computed": True},
                ],
                "unique_indexes": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "item_total" not in col_names
        assert "quantity" in col_names
        assert "price_per_unit" in col_names

    def test_no_generated_removal_without_schema(self) -> None:
        """Fix 5: without schema, GENERATED columns are NOT removed (no-op)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {"name": "item_total", "derive_from": ["quantity"],
                         "expression": "round(value,2)"},
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config, schema=None)
        # Without schema, the column is NOT removed
        col_names = [c["name"] for c in config["tables"][0]["columns"]]
        assert "item_total" in col_names

    def test_sets_unique_true_for_unique_index_columns(self) -> None:
        """Fix 6: columns with UNIQUE index get constraints.unique=true."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "username", "generator": "template",
                         "params": {"template": "USER-{sequence:04d}"},
                         "constraints": {"unique": True}},
                        {"name": "email", "generator": "email", "params": {},
                         "constraints": {"unique": False}},
                    ],
                }
            ]
        }
        schema = {
            "users": {
                "columns": [
                    {"name": "username", "type": "TEXT", "is_computed": False},
                    {"name": "email", "type": "TEXT", "is_computed": False},
                ],
                "unique_indexes": [
                    {"name": "idx_username", "columns": ["username"], "unique": True},
                    {"name": "sqlite_autoindex_users_2", "columns": ["email"], "unique": True},
                ],
            }
        }
        analyzer._auto_fix_config(config, schema)
        cols = config["tables"][0]["columns"]
        # username was already unique=True, should stay True
        assert cols[0]["constraints"]["unique"] is True
        # email was unique=False, should be fixed to True
        assert cols[1]["constraints"]["unique"] is True

    def test_sets_unique_true_creates_constraints_dict_if_missing(self) -> None:
        """Fix 6: creates constraints dict if the LLM omitted it entirely."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "email", "generator": "email", "params": {}},
                    ],
                }
            ]
        }
        schema = {
            "users": {
                "columns": [
                    {"name": "email", "type": "TEXT", "is_computed": False},
                ],
                "unique_indexes": [
                    {"name": "sqlite_autoindex_users_2", "columns": ["email"], "unique": True},
                ],
            }
        }
        analyzer._auto_fix_config(config, schema)
        col = config["tables"][0]["columns"][0]
        assert col["constraints"]["unique"] is True

    def test_removes_orphan_expression_when_generator_set(self) -> None:
        """Fix 7: expression removed when generator is set and derive_from is null.

        This happens when the LLM provides both a generator and an expression
        but no derive_from — the expression is meaningless in source mode.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "discount",
                            "generator": "float",
                            "params": {"min_value": 0, "max_value": 1},
                            "derive_from": None,
                            "expression": "round(random_float(0,value),2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["generator"] == "float"
        assert "expression" not in col or col.get("expression") is None

    def test_keeps_expression_when_derive_from_set(self) -> None:
        """Fix 7: expression is kept when derive_from is set (derived mode)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "sale_price",
                            "derive_from": "cost_price",
                            "expression": "round(value*1.2,2)",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["expression"] == "round(value*1.2,2)"

    def test_converts_source_col_to_derive_from_for_cross_column_check(self) -> None:
        """Fix 8: source-mode column converted to derive_from when bounded by another column.

        When a column has a CHECK like "discount >= 0 AND discount <= price_per_unit"
        and is in source mode (has generator, no derive_from), generating it
        independently risks CHECK violations. Convert to derive_from.
        """
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "price_per_unit",
                            "generator": "float",
                            "params": {"min_value": 0.01, "max_value": 100.0},
                            "derive_from": None,
                            "expression": None,
                        },
                        {
                            "name": "discount",
                            "generator": "float",
                            "params": {"min_value": 0.0, "max_value": 1.0},
                            "derive_from": None,
                            "expression": None,
                        },
                    ],
                }
            ]
        }
        schema: dict = {
            "order_items": {
                "columns": [
                    {"name": "price_per_unit", "type": "REAL"},
                    {"name": "discount", "type": "REAL"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["discount", "discount", "price_per_unit"],
                        "expression": "discount >= 0 AND discount <= price_per_unit",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        discount = config["tables"][0]["columns"][1]
        assert discount["derive_from"] == ["price_per_unit"]
        assert discount["expression"] == "round(random_float(0, value), 2)"
        assert discount.get("generator") is None
        assert discount.get("params") is None

    def test_no_conversion_when_already_derive_from(self) -> None:
        """Fix 8: no conversion when column already has derive_from set."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "discount",
                            "derive_from": "price_per_unit",
                            "expression": "round(random_float(0,value),2)",
                        }
                    ],
                }
            ]
        }
        schema: dict = {
            "order_items": {
                "columns": [
                    {"name": "price_per_unit", "type": "REAL"},
                    {"name": "discount", "type": "REAL"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["discount", "price_per_unit"],
                        "expression": "discount >= 0 AND discount <= price_per_unit",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        discount = config["tables"][0]["columns"][0]
        assert discount["derive_from"] == "price_per_unit"
        assert discount["expression"] == "round(random_float(0,value),2)"
        assert "generator" not in discount

    def test_no_conversion_for_single_column_check(self) -> None:
        """Fix 8: no conversion for single-column CHECK (e.g., quantity > 0 AND quantity <= 5)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "quantity",
                            "generator": "integer",
                            "params": {"min_value": 1, "max_value": 5},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        schema: dict = {
            "order_items": {
                "columns": [{"name": "quantity", "type": "INTEGER"}],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["quantity", "quantity"],
                        "expression": "quantity > 0 AND quantity <= 5",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        quantity = config["tables"][0]["columns"][0]
        assert quantity["generator"] == "integer"
        assert quantity.get("derive_from") is None

    def test_no_conversion_without_schema(self) -> None:
        """Fix 8: no conversion when schema is None."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "order_items",
                    "columns": [
                        {
                            "name": "discount",
                            "generator": "float",
                            "params": {"min_value": 0.0, "max_value": 1.0},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config, schema=None)
        discount = config["tables"][0]["columns"][0]
        assert discount["generator"] == "float"
        assert discount.get("derive_from") is None

    def test_converts_with_greater_than_zero_lower_bound(self) -> None:
        """Fix 8: triggers for '> 0' lower bound (not just '>= 0')."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {
                            "name": "margin",
                            "generator": "float",
                            "params": {"min_value": 0.0, "max_value": 1.0},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        schema: dict = {
            "items": {
                "columns": [
                    {"name": "margin", "type": "REAL"},
                    {"name": "price", "type": "REAL"},
                ],
                "check_constraints": [
                    {
                        "name": "",
                        "columns": ["margin", "price"],
                        "expression": "margin > 0 AND margin <= price",
                    }
                ],
                "unique_indexes": [],
                "unique_columns": [],
            }
        }
        analyzer._auto_fix_config(config, schema)
        margin = config["tables"][0]["columns"][0]
        assert margin["derive_from"] == ["price"]
        assert margin["expression"] == "round(random_float(0, value), 2)"
        assert margin.get("generator") is None

    def test_fixes_name_column_generator_to_word(self) -> None:
        """Fix 9: *_name columns using string/text should be corrected to word."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "categories",
                    "columns": [
                        {
                            "name": "category_name",
                            "generator": "string",
                            "params": {"min_length": 10, "max_length": 100},
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
        assert col.get("params") is None or col["params"] == {}

    def test_fixes_merchant_name_to_company(self) -> None:
        """Fix 9: merchant_name / company_name should use company generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "merchants",
                    "columns": [
                        {
                            "name": "merchant_name",
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
        assert col["generator"] == "company"

    def test_no_fix_when_name_col_already_uses_word(self) -> None:
        """Fix 9: no correction when *_name already uses word/company."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "product_name",
                            "generator": "word",
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
        assert col["generator"] == "word"

    def test_no_fix_when_name_col_has_derive_from(self) -> None:
        """Fix 9: no correction when *_name column is in derived mode."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "full_name",
                            "derive_from": "first_name",
                            "expression": "value",
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert "generator" not in col
        assert col["derive_from"] == "first_name"

    def test_adds_max_value_to_integer_without_max(self) -> None:
        """Fix 10: integer generator without max_value gets a reasonable default."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "products",
                    "columns": [
                        {
                            "name": "stock",
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
        assert col["params"]["max_value"] <= 99999

    def test_no_max_value_added_when_already_present(self) -> None:
        """Fix 10: no change when max_value already set."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {
                            "name": "stock_count",
                            "generator": "integer",
                            "params": {"min_value": 0, "max_value": 5000},
                            "derive_from": None,
                            "expression": None,
                        }
                    ],
                }
            ]
        }
        analyzer._auto_fix_config(config)
        col = config["tables"][0]["columns"][0]
        assert col["params"]["max_value"] == 5000

    def test_quantity_column_gets_smaller_max(self) -> None:
        """Fix 10: quantity* columns get max_value=100 (not 99999)."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "sales",
                    "columns": [
                        {
                            "name": "quantity_sold",
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
        assert col["params"]["max_value"] == 100

    def test_fixes_email_column_to_email_generator(self) -> None:
        """Fix 11: *_email columns using string should be corrected to email."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "contact_email",
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
        assert col["generator"] == "email"

    def test_fixes_phone_column_to_phone_generator(self) -> None:
        """Fix 11: *_phone columns using string should be corrected to phone."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "phone",
                            "generator": "string",
                            "params": {"min_length": 10, "max_length": 15},
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

    def test_no_fix_when_email_already_correct(self) -> None:
        """Fix 11: no correction when *_email already uses email generator."""
        analyzer = SchemaSemanticAnalyzer(config=MagicMock())
        config: dict = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {
                            "name": "email",
                            "generator": "email",
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
        assert col["generator"] == "email"


