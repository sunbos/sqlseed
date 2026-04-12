from __future__ import annotations

import pytest

from sqlseed.config.models import ColumnConfig, GeneratorConfig, ProviderType, TableConfig


class TestConfigModels:
    def test_column_config_defaults(self) -> None:
        config = ColumnConfig(name="test")
        assert config.name == "test"
        assert config.generator is None
        assert config.params == {}
        assert config.null_ratio == 0.0

    def test_column_config_with_params(self) -> None:
        config = ColumnConfig(
            name="age",
            generator="integer",
            params={"min_value": 18, "max_value": 65},
        )
        assert config.generator == "integer"
        assert config.params["min_value"] == 18

    def test_column_config_null_ratio_validation(self) -> None:
        config = ColumnConfig(name="test", null_ratio=0.5)
        assert config.null_ratio == 0.5

    def test_column_config_null_ratio_too_high(self) -> None:
        with pytest.raises(ValueError):
            ColumnConfig(name="test", null_ratio=1.5)

    def test_column_config_null_ratio_negative(self) -> None:
        with pytest.raises(ValueError):
            ColumnConfig(name="test", null_ratio=-0.1)

    def test_table_config_defaults(self) -> None:
        config = TableConfig(name="users")
        assert config.name == "users"
        assert config.count == 1000
        assert config.batch_size == 5000
        assert config.columns == []
        assert config.clear_before is False
        assert config.seed is None

    def test_generator_config_defaults(self) -> None:
        config = GeneratorConfig(db_path="test.db")
        assert config.db_path == "test.db"
        assert config.provider == ProviderType.MIMESIS
        assert config.locale == "en_US"
        assert config.optimize_pragma is True

    def test_generator_config_full(self) -> None:
        config = GeneratorConfig(
            db_path="test.db",
            provider=ProviderType.FAKER,
            locale="zh_CN",
            tables=[
                TableConfig(
                    name="users",
                    count=10000,
                    columns=[
                        ColumnConfig(name="email", generator="email"),
                        ColumnConfig(name="age", generator="integer", params={"min_value": 18}),
                    ],
                ),
            ],
        )
        assert config.provider == ProviderType.FAKER
        assert len(config.tables) == 1
        assert len(config.tables[0].columns) == 2
