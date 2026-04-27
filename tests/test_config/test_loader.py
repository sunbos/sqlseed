from __future__ import annotations

import json
from typing import Any

import pytest

from sqlseed.config.loader import generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig


class TestConfigLoader:
    def test_load_yaml(self, tmp_path: Any) -> None:
        config_path = tmp_path / "test.yaml"
        config_path.write_text("""
db_path: "test.db"
provider: mimesis
locale: en_US
tables:
  - name: users
    count: 1000
""")
        config = load_config(str(config_path))
        assert config.db_path == "test.db"
        assert config.provider == ProviderType.MIMESIS
        assert len(config.tables) == 1
        assert config.tables[0].name == "users"

    def test_load_json(self, tmp_path: Any) -> None:
        config_path = tmp_path / "test.json"
        data = {
            "db_path": "test.db",
            "provider": "faker",
            "locale": "zh_CN",
            "tables": [{"name": "orders", "count": 5000}],
        }
        config_path.write_text(json.dumps(data))
        config = load_config(str(config_path))
        assert config.db_path == "test.db"
        assert config.provider == ProviderType.FAKER

    def test_load_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_load_unsupported_format(self, tmp_path: Any) -> None:
        config_path = tmp_path / "test.txt"
        config_path.write_text("db_path: test.db")
        with pytest.raises(ValueError, match="Unsupported"):
            load_config(str(config_path))

    def test_load_non_dict_content(self, tmp_path: Any) -> None:
        config_path = tmp_path / "test.yaml"
        config_path.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must contain a YAML/JSON object"):
            load_config(str(config_path))

    def test_save_yaml(self, tmp_path: Any) -> None:
        config = GeneratorConfig(
            db_path="test.db",
            tables=[TableConfig(name="users", count=100)],
        )
        config_path = str(tmp_path / "output.yaml")
        save_config(config, config_path)
        loaded = load_config(config_path)
        assert loaded.db_path == "test.db"
        assert loaded.tables[0].name == "users"

    def test_save_json(self, tmp_path: Any) -> None:
        config = GeneratorConfig(db_path="test.db")
        config_path = str(tmp_path / "output.json")
        save_config(config, config_path)
        loaded = load_config(config_path)
        assert loaded.db_path == "test.db"

    def test_save_unsupported_format(self, tmp_path: Any) -> None:
        config = GeneratorConfig(db_path="test.db")
        with pytest.raises(ValueError, match="Unsupported"):
            save_config(config, str(tmp_path / "output.txt"))

    def test_generate_template(self) -> None:
        template = generate_template("test.db", "users")
        assert template.db_path == "test.db"
        assert len(template.tables) == 1
        assert template.tables[0].name == "users"
