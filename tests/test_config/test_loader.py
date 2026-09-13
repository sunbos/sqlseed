"""Tests for the config loader module."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed.config.loader import _read_table_names, generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig

if TYPE_CHECKING:
    from pathlib import Path


class TestConfigLoader:
    def test_load_yaml(self, tmp_path: Path) -> None:
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

    def test_load_json(self, tmp_path: Path) -> None:
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

    def test_load_unsupported_format(self, tmp_path: Path) -> None:
        config_path = tmp_path / "test.txt"
        config_path.write_text("db_path: test.db")
        with pytest.raises(ValueError, match="Unsupported"):
            load_config(str(config_path))

    def test_load_non_dict_content(self, tmp_path: Path) -> None:
        config_path = tmp_path / "test.yaml"
        config_path.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must contain a YAML/JSON object"):
            load_config(str(config_path))

    def test_save_yaml(self, tmp_path: Path) -> None:
        config = GeneratorConfig(
            db_path="test.db",
            tables=[TableConfig(name="users", count=100)],
        )
        config_path = str(tmp_path / "output.yaml")
        save_config(config, config_path)
        loaded = load_config(config_path)
        assert loaded.db_path == "test.db"
        assert loaded.tables[0].name == "users"

    def test_save_json(self, tmp_path: Path) -> None:
        config = GeneratorConfig(db_path="test.db")
        config_path = str(tmp_path / "output.json")
        save_config(config, config_path)
        loaded = load_config(config_path)
        assert loaded.db_path == "test.db"

    def test_save_unsupported_format(self, tmp_path: Path) -> None:
        config = GeneratorConfig(db_path="test.db")
        with pytest.raises(ValueError, match="Unsupported"):
            save_config(config, str(tmp_path / "output.txt"))

    def test_generate_template(self) -> None:
        template = generate_template("test.db", table_name="users")
        assert template.db_path == "test.db"
        assert len(template.tables) == 1
        assert template.tables[0].name == "users"


class TestReadTableNames:
    """Tests for the _read_table_names function (private, leading underscore)."""

    def test_read_table_names_empty_database(self, tmp_path: Path) -> None:
        """Empty database returns []."""
        db_path = str(tmp_path / "empty.db")
        sqlite3.connect(db_path).close()  # create empty file
        assert _read_table_names(db_path) == []

    def test_read_table_names_excludes_system_tables(self, tmp_path: Path) -> None:
        """Exclude sqlite_% system tables."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        # AUTOINCREMENT automatically creates the sqlite_sequence system table
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
        conn.commit()
        conn.close()

        names = _read_table_names(db_path)
        assert "users" in names
        assert "sqlite_sequence" not in names

    def test_read_table_names_returns_all_user_tables(self, tmp_path: Path) -> None:
        """Multi-table database returns all user tables."""
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        names = _read_table_names(db_path)
        assert set(names) == {"users", "orders", "products"}

    def test_generate_template_accepts_url(self, tmp_path: Path) -> None:
        """generate_template supports the url parameter (multi-database)."""
        # Use sqlite:/// format URL to verify multi-DB table name reading logic
        db_path = tmp_path / "test_url.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        url = f"sqlite:///{db_path}"
        template = generate_template(url=url)
        assert template.url == url
        assert template.db_path is None
        table_names = [t.name for t in template.tables]
        assert "users" in table_names
        assert "orders" in table_names

    def test_generate_template_db_path_and_url_mutually_exclusive(self) -> None:
        """generate_template's db_path and url are mutually exclusive."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            generate_template(db_path="test.db", url="postgresql://user:pass@host/db")

    def test_generate_template_requires_connection_target(self) -> None:
        """generate_template requires at least db_path or url."""
        with pytest.raises(ValueError, match="must be provided"):
            generate_template()

    def test_read_table_names_nonexistent_parent_dir_raises(self, tmp_path: Path) -> None:
        """Raises an exception when the parent directory does not exist."""
        # SQLAlchemy raises sqlalchemy.exc.OperationalError for inaccessible paths
        nonexistent = str(tmp_path / "nonexistent_dir" / "test.db")
        with pytest.raises((OSError, SAOperationalError)):
            _read_table_names(nonexistent)
