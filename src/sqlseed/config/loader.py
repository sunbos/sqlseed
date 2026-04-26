from __future__ import annotations

import json
from pathlib import Path

import yaml

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import GeneratorConfig, TableConfig

logger = get_logger(__name__)


def load_config(path: str) -> GeneratorConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    suffix = config_path.suffix.lower()
    with open(config_path, encoding="utf-8") as f:
        if suffix in {".yaml", ".yml"}:
            raw = yaml.safe_load(f)
        elif suffix == ".json":
            raw = json.load(f)
        else:
            raise ValueError(f"Unsupported configuration file format: {suffix}")

    if not isinstance(raw, dict):
        raise ValueError("Configuration file must contain a YAML/JSON object")

    return GeneratorConfig(**raw)


def save_config(config: GeneratorConfig, path: str) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    suffix = config_path.suffix.lower()
    data = config.model_dump(mode="json")

    with open(config_path, "w", encoding="utf-8") as f:
        if suffix in {".yaml", ".yml"}:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        elif suffix == ".json":
            json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported configuration file format: {suffix}")

    logger.info("Configuration saved", path=path)


def generate_template(db_path: str, table_name: str | None = None) -> GeneratorConfig:
    tables: list[TableConfig] = []
    if table_name:
        tables.append(
            TableConfig(
                name=table_name,
                count=1000,
                columns=[],
            )
        )
    else:
        try:
            from sqlseed.database._compat import HAS_SQLITE_UTILS  # noqa: PLC0415

            if HAS_SQLITE_UTILS:
                import sqlite_utils  # noqa: PLC0415

                db = sqlite_utils.Database(db_path)
                for tbl_name in db.table_names():
                    if tbl_name.startswith("sqlite_"):
                        continue
                    tables.append(
                        TableConfig(
                            name=tbl_name,
                            count=1000,
                            columns=[],
                        )
                    )
                db.close()
            else:
                import sqlite3  # noqa: PLC0415

                conn = sqlite3.connect(db_path)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                for (tbl_name,) in cursor.fetchall():
                    tables.append(
                        TableConfig(
                            name=tbl_name,
                            count=1000,
                            columns=[],
                        )
                    )
                conn.close()
        except (OSError, ValueError, ImportError):
            logger.warning("Could not read tables from database", db_path=db_path)

    return GeneratorConfig(
        db_path=db_path,
        tables=tables,
    )
