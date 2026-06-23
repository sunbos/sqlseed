"""Tests for the config models."""

from __future__ import annotations

import json

import pytest
import yaml

from sqlseed.config.loader import load_config
from sqlseed.config.models import ColumnConfig, GeneratorConfig, ProviderType, TableConfig


class TestConfigModels:
    def test_column_config_defaults(self) -> None:
        config = ColumnConfig(name="test")
        assert config.name == "test"
        assert config.generator is None
        assert config.params == {}
        assert config.null_ratio == pytest.approx(0.0)

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
        assert config.null_ratio == pytest.approx(0.5)

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


class TestGeneratorConfigUrl:
    """Tests for the url field and connection_target property of GeneratorConfig."""

    def test_url_field_accepted(self) -> None:
        """GeneratorConfig(url=...) successfully accepts the url field."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        assert config.url == "postgresql://user:pass@host/db"
        assert config.db_path is None

    def test_db_path_and_url_mutual_exclusion(self) -> None:
        """Providing both db_path and url raises ValidationError."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            GeneratorConfig(
                db_path="test.db",
                url="postgresql://user:pass@host/db",
                tables=[],
            )

    def test_neither_db_path_nor_url_raises(self) -> None:
        """Providing neither raises ValidationError."""
        with pytest.raises(ValueError, match="Either 'db_path' or 'url' must be provided"):
            GeneratorConfig(tables=[])

    def test_connection_target_returns_url(self) -> None:
        """config.connection_target returns url (when url is set)."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        assert config.connection_target == "postgresql://user:pass@host/db"

    def test_connection_target_returns_db_path(self) -> None:
        """config.connection_target returns db_path (when db_path is set)."""
        config = GeneratorConfig(db_path="test.db", tables=[])
        assert config.connection_target == "test.db"

    def test_connection_target_property_consistency(self) -> None:
        """Multiple calls to connection_target return the same value."""
        config = GeneratorConfig(url="postgresql://user:pass@host/db", tables=[])
        target1 = config.connection_target
        target2 = config.connection_target
        assert target1 == target2

    def test_from_config_uses_connection_target(self, tmp_path) -> None:
        """from_config uses connection_target instead of db_path."""
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": f"sqlite:///{tmp_path / 'test.db'}",
            "provider": "base",
            "tables": [{"name": "users", "count": 5}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        config = load_config(str(config_path))
        assert config.url is not None
        assert config.connection_target == config.url

    def test_config_with_url_serialization(self, tmp_path) -> None:
        """YAML containing the url field can be loaded correctly."""
        config_path = tmp_path / "gen.yaml"
        config_data = {
            "url": "postgresql://user:pass@host:5432/mydb",
            "provider": "base",
            "tables": [{"name": "users", "count": 100}],
        }
        config_path.write_text(yaml.dump(config_data), encoding="utf-8")

        config = load_config(str(config_path))
        assert config.url == "postgresql://user:pass@host:5432/mydb"
        assert config.db_path is None

    def test_config_with_url_json_serialization(self, tmp_path) -> None:
        """JSON containing the url field can be loaded correctly."""
        config_path = tmp_path / "gen.json"
        config_data = {
            "url": "postgresql://user:pass@host:5432/mydb",
            "provider": "base",
            "tables": [{"name": "users", "count": 100}],
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        config = load_config(str(config_path))
        assert config.url == "postgresql://user:pass@host:5432/mydb"
        assert config.db_path is None
