from __future__ import annotations

from sqlseed.config.models import ColumnConfig
from sqlseed.core.mapper import ColumnMapper
from tests.conftest import make_column_info


class TestColumnMapper:
    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_exact_match_email(self) -> None:
        spec = self.mapper.map_column(make_column_info("email"))
        assert spec.generator_name == "email"

    def test_exact_match_phone(self) -> None:
        spec = self.mapper.map_column(make_column_info("phone"))
        assert spec.generator_name == "phone"

    def test_exact_match_age(self) -> None:
        spec = self.mapper.map_column(make_column_info("age", "INTEGER"))
        assert spec.generator_name == "integer"
        assert spec.params["min_value"] == 18
        assert spec.params["max_value"] == 65

    def test_exact_match_balance(self) -> None:
        spec = self.mapper.map_column(make_column_info("balance", "REAL"))
        assert spec.generator_name == "float"
        assert spec.params["precision"] == 2

    def test_pattern_match_created_at(self) -> None:
        spec = self.mapper.map_column(make_column_info("created_at"))
        assert spec.generator_name == "datetime"

    def test_pattern_match_is_active(self) -> None:
        spec = self.mapper.map_column(make_column_info("is_active", "INTEGER"))
        assert spec.generator_name == "boolean"

    def test_column_with_default_is_skipped(self) -> None:
        spec = self.mapper.map_column(make_column_info("is_active", "INTEGER", nullable=False, default="1"))
        assert spec.generator_name == "skip"

    def test_column_with_default_nullable_still_skipped(self) -> None:
        spec = self.mapper.map_column(make_column_info("visibility", "INTEGER", nullable=True, default="0"))
        assert spec.generator_name == "skip"

    def test_pattern_match_user_id(self) -> None:
        spec = self.mapper.map_column(make_column_info("user_id", "INTEGER"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_autoincrement_pk_skip(self) -> None:
        spec = self.mapper.map_column(
            make_column_info("id", "INTEGER", nullable=False, is_primary_key=True, is_autoincrement=True)
        )
        assert spec.generator_name == "skip"

    def test_type_fallback_integer(self) -> None:
        spec = self.mapper.map_column(make_column_info("some_number", "INTEGER", nullable=False))
        assert spec.generator_name == "integer"

    def test_type_fallback_text(self) -> None:
        spec = self.mapper.map_column(make_column_info("some_field", "TEXT", nullable=False))
        assert spec.generator_name == "string"

    def test_custom_exact_rule(self) -> None:
        self.mapper.register_exact_rule("custom_col", "email")
        spec = self.mapper.map_column(make_column_info("custom_col"))
        assert spec.generator_name == "email"

    def test_custom_pattern_rule(self) -> None:
        self.mapper.register_pattern_rule(r"^custom_.*$", "uuid")
        spec = self.mapper.map_column(make_column_info("custom_field"))
        assert spec.generator_name == "uuid"

    def test_user_config_overrides(self) -> None:
        user_config = ColumnConfig(name="email", generator="name")
        spec = self.mapper.map_column(make_column_info("email"), user_config)
        assert spec.generator_name == "name"

    def test_exact_match_sku_maps_to_alphanumeric_string(self) -> None:
        """``sku`` column → string generator with alphanumeric charset.

        SKU (Stock Keeping Unit) codes must NOT contain spaces or dashes
        (they're used as product identifiers in URLs, barcodes, and joins).
        The default charset for the string generator includes ``" _-"`` which
        is unsafe for SKUs — the rule must explicitly use ``alphanumeric``.
        """
        spec = self.mapper.map_column(make_column_info("sku", "TEXT"))
        assert spec.generator_name == "string"
        assert spec.params["charset"] == "alphanumeric"

    def test_pattern_match_order_no_maps_to_string_not_integer(self) -> None:
        """``order_no`` column → string generator (not foreign_key_or_integer).

        Business codes like ``order_no``, ``task_no``, ``invoice_no`` are
        alphanumeric identifiers, not integers. The previous rule mapped
        ``.*_no$|.*_nbr$`` to ``foreign_key_or_integer`` which falls back
        to plain integer when the column is not a FK — producing numeric
        order numbers instead of alphanumeric codes.
        """
        spec = self.mapper.map_column(make_column_info("order_no", "TEXT"))
        assert spec.generator_name == "string", (
            f"order_no should map to 'string' (alphanumeric code), got {spec.generator_name!r}"
        )
        assert spec.params.get("charset") == "alphanumeric"

    def test_pattern_match_task_no_maps_to_string(self) -> None:
        """``task_no`` column → string generator (regression for task_no bug)."""
        spec = self.mapper.map_column(make_column_info("task_no", "TEXT"))
        assert spec.generator_name == "string"
        assert spec.params.get("charset") == "alphanumeric"

    def test_pattern_match_invoice_nbr_maps_to_string(self) -> None:
        """``invoice_nbr`` column → string generator (regression for *_nbr bug)."""
        spec = self.mapper.map_column(make_column_info("invoice_nbr", "TEXT"))
        assert spec.generator_name == "string"
        assert spec.params.get("charset") == "alphanumeric"


class TestNameColumnMapping:
    """Tests for *_name column mapping rules (word fallback, person-name contexts)."""

    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_person_name_user_name_maps_to_username(self) -> None:
        """user_name → username via exact match (more specific than person-name pattern)."""
        spec = self.mapper.map_column(make_column_info("user_name"))
        assert spec.generator_name == "username"

    def test_person_name_customer_name(self) -> None:
        """customer_name → name (person name, explicit human context via pattern match)."""
        spec = self.mapper.map_column(make_column_info("customer_name"))
        assert spec.generator_name == "name"

    def test_person_name_employee_name(self) -> None:
        """employee_name → name (person name, explicit human context via pattern match)."""
        spec = self.mapper.map_column(make_column_info("employee_name"))
        assert spec.generator_name == "name"

    def test_person_name_author_name(self) -> None:
        """author_name → name (person name, explicit human context via pattern match)."""
        spec = self.mapper.map_column(make_column_info("author_name"))
        assert spec.generator_name == "name"

    def test_company_name(self) -> None:
        """company_name → company (high-confidence domain context)."""
        spec = self.mapper.map_column(make_column_info("company_name"))
        assert spec.generator_name == "company"

    def test_product_name_falls_back_to_catch_phrase(self) -> None:
        """product_name → catch_phrase (multi-word business phrase, not single word)."""
        spec = self.mapper.map_column(make_column_info("product_name"))
        assert spec.generator_name == "catch_phrase"

    def test_animal_name_falls_back_to_catch_phrase(self) -> None:
        """animal_name → catch_phrase (not person name; multi-word fallback)."""
        spec = self.mapper.map_column(make_column_info("animal_name"))
        assert spec.generator_name == "catch_phrase"

    def test_medicine_name_falls_back_to_catch_phrase(self) -> None:
        """medicine_name → catch_phrase (not person name; multi-word fallback)."""
        spec = self.mapper.map_column(make_column_info("medicine_name"))
        assert spec.generator_name == "catch_phrase"

    def test_color_name_falls_back_to_catch_phrase(self) -> None:
        """color_name → catch_phrase (not person name; multi-word fallback)."""
        spec = self.mapper.map_column(make_column_info("color_name"))
        assert spec.generator_name == "catch_phrase"

    def test_generic_name_falls_back_to_catch_phrase(self) -> None:
        """Unknown *_name column → catch_phrase (not person name)."""
        spec = self.mapper.map_column(make_column_info("unknown_thing_name"))
        assert spec.generator_name == "catch_phrase"


class TestLoadCustomMappings:
    """Tests for loading custom column mappings from YAML config (CustomColumnMappings)."""

    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_load_exact_mapping_overrides_default(self) -> None:
        """Custom exact rule overrides built-in *_name fallback."""
        from sqlseed.config.models import CustomColumnMappings, ExactColumnMappingRule

        mappings = CustomColumnMappings(
            exact={"file_name": ExactColumnMappingRule(generator="string", params={"min_length": 5, "max_length": 20})}
        )
        self.mapper.load_custom_mappings(mappings)
        spec = self.mapper.map_column(make_column_info("file_name"))
        # Without override, file_name would match *_name → word.
        # With override, it should be string.
        assert spec.generator_name == "string"
        assert spec.params["min_length"] == 5

    def test_load_pattern_mapping_overrides_default(self) -> None:
        """Custom pattern rule overrides built-in *_name fallback."""
        from sqlseed.config.models import CustomColumnMappings, PatternColumnMappingRule

        mappings = CustomColumnMappings(pattern=[PatternColumnMappingRule(pattern=r"^sku_.*$", generator="uuid")])
        self.mapper.load_custom_mappings(mappings)
        spec = self.mapper.map_column(make_column_info("sku_product_id"))
        assert spec.generator_name == "uuid"

    def test_load_both_exact_and_pattern_mappings(self) -> None:
        """Both exact and pattern custom mappings can be loaded together."""
        from sqlseed.config.models import CustomColumnMappings, ExactColumnMappingRule, PatternColumnMappingRule

        mappings = CustomColumnMappings(
            exact={"tenant_id": ExactColumnMappingRule(generator="uuid")},
            pattern=[PatternColumnMappingRule(pattern=r"^external_.*$", generator="string")],
        )
        self.mapper.load_custom_mappings(mappings)
        assert self.mapper.map_column(make_column_info("tenant_id")).generator_name == "uuid"
        assert self.mapper.map_column(make_column_info("external_ref")).generator_name == "string"


class TestMapColumns:
    """Tests for the map_columns (plural) batch API."""

    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_map_columns(self) -> None:
        columns = [
            make_column_info("id", "INTEGER", nullable=False, is_primary_key=True, is_autoincrement=True),
            make_column_info("email"),
            make_column_info("age", "INTEGER"),
        ]
        specs = self.mapper.map_columns(columns)
        assert specs["id"].generator_name == "skip"
        assert specs["email"].generator_name == "email"
        assert specs["age"].generator_name == "integer"
