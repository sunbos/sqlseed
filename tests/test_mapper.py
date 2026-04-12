from __future__ import annotations

from sqlseed.core.mapper import ColumnMapper
from sqlseed.database._protocol import ColumnInfo


def _col(
    name: str,
    col_type: str = "TEXT",
    nullable: bool = True,
    default=None,
    is_primary_key: bool = False,
    is_autoincrement: bool = False,
) -> ColumnInfo:
    return ColumnInfo(
        name=name,
        type=col_type,
        nullable=nullable,
        default=default,
        is_primary_key=is_primary_key,
        is_autoincrement=is_autoincrement,
    )


class TestColumnMapper:
    def setup_method(self) -> None:
        self.mapper = ColumnMapper()

    def test_exact_match_email(self) -> None:
        spec = self.mapper.map_column(_col("email"))
        assert spec.generator_name == "email"

    def test_exact_match_phone(self) -> None:
        spec = self.mapper.map_column(_col("phone"))
        assert spec.generator_name == "phone"

    def test_exact_match_age(self) -> None:
        spec = self.mapper.map_column(_col("age", "INTEGER"))
        assert spec.generator_name == "integer"
        assert spec.params["min_value"] == 18
        assert spec.params["max_value"] == 100

    def test_exact_match_balance(self) -> None:
        spec = self.mapper.map_column(_col("balance", "REAL"))
        assert spec.generator_name == "float"
        assert spec.params["precision"] == 2

    def test_pattern_match_created_at(self) -> None:
        spec = self.mapper.map_column(_col("created_at"))
        assert spec.generator_name == "datetime"

    def test_pattern_match_is_active(self) -> None:
        spec = self.mapper.map_column(_col("is_active", "INTEGER"))
        assert spec.generator_name == "boolean"

    def test_pattern_match_user_id(self) -> None:
        spec = self.mapper.map_column(_col("user_id", "INTEGER"))
        assert spec.generator_name == "foreign_key_or_integer"

    def test_autoincrement_pk_skip(self) -> None:
        spec = self.mapper.map_column(_col("id", "INTEGER", nullable=False, is_primary_key=True, is_autoincrement=True))
        assert spec.generator_name == "skip"

    def test_type_fallback_integer(self) -> None:
        spec = self.mapper.map_column(_col("some_number", "INTEGER", nullable=False))
        assert spec.generator_name == "integer"

    def test_type_fallback_text(self) -> None:
        spec = self.mapper.map_column(_col("some_field", "TEXT", nullable=False))
        assert spec.generator_name == "string"

    def test_custom_exact_rule(self) -> None:
        self.mapper.register_exact_rule("custom_col", "email")
        spec = self.mapper.map_column(_col("custom_col"))
        assert spec.generator_name == "email"

    def test_custom_pattern_rule(self) -> None:
        self.mapper.register_pattern_rule(r"^custom_.*$", "uuid")
        spec = self.mapper.map_column(_col("custom_field"))
        assert spec.generator_name == "uuid"

    def test_user_config_overrides(self) -> None:
        from sqlseed.config.models import ColumnConfig

        user_config = ColumnConfig(name="email", generator="name")
        spec = self.mapper.map_column(_col("email"), user_config)
        assert spec.generator_name == "name"

    def test_map_columns(self) -> None:
        columns = [
            _col("id", "INTEGER", nullable=False, is_primary_key=True, is_autoincrement=True),
            _col("email"),
            _col("age", "INTEGER"),
        ]
        specs = self.mapper.map_columns(columns)
        assert specs["id"].generator_name == "skip"
        assert specs["email"].generator_name == "email"
        assert specs["age"].generator_name == "integer"
