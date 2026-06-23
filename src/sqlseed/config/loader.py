"""sqlseed configuration file loader.

Supports loading, saving, and template generation for YAML and JSON
configuration files. Template generation supports SQLite file paths and
database URLs (multi-database).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sqlseed._utils.logger import get_logger
from sqlseed.config.models import GeneratorConfig, TableConfig

logger = get_logger(__name__)

_DEFAULT_TEMPLATE_COUNT = 1000


def _read_table_names(target: str) -> list[str]:
    """Read all user table names from the database.

    Supports SQLite file paths and database URLs (postgresql://, mysql://, etc.).
    Excludes SQLite system tables (sqlite_ prefix).

    Args:
        target: Database file path or URL

    Returns:
        List of user table names

    Raises:
        OSError: File does not exist or cannot be accessed
        RuntimeError: Database driver not installed or connection failed
        ValueError: Invalid URL
    """
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    # A plain file path is automatically converted to a SQLite URL
    db_url = target if "://" in target else f"sqlite:///{target}"
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        # inspector.get_table_names() does not return SQLite system tables by default,
        # but filter them out as a safeguard
        return [name for name in table_names if not name.startswith("sqlite_")]
    finally:
        engine.dispose()


def load_config(path: str) -> GeneratorConfig:
    """Load a YAML or JSON configuration file.

    Selects the parser automatically based on the file extension:
    - .yaml/.yml → YAML parsing
    - .json → JSON parsing

    Args:
        path: Configuration file path

    Returns:
        Parsed GeneratorConfig

    Raises:
        FileNotFoundError: File does not exist
        ValueError: Unsupported format or content is not an object
    """
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
    """Save a configuration to a YAML or JSON file.

    Selects the serialization format automatically based on the file extension:
    - .yaml/.yml → YAML serialization
    - .json → JSON serialization

    Args:
        config: Configuration to save
        path: Target file path

    Raises:
        ValueError: Unsupported format
    """
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


def generate_template(
    db_path: str | None = None,
    *,
    url: str | None = None,
    table_name: str | None = None,
) -> GeneratorConfig:
    """Generate a configuration template.

    Reads table names from the database and generates a configuration template
    containing all tables. Supports SQLite file paths and database URLs
    (postgresql://, mysql://, etc.).

    Args:
        db_path: SQLite database file path. Mutually exclusive with url.
        url: Database URL (e.g. postgresql://user:pass@host/db). Mutually exclusive with db_path.
        table_name: If specified, generate configuration only for this table
            (without reading the database).

    Returns:
        GeneratorConfig configuration template

    Raises:
        ValueError: When db_path and url are both provided, or neither is provided
    """
    if db_path and url:
        raise ValueError("Cannot specify both 'db_path' and 'url'. Use one or the other.")
    if not db_path and not url:
        raise ValueError("Either 'db_path' or 'url' must be provided.")

    tables: list[TableConfig] = []
    if table_name:
        tables.append(
            TableConfig(
                name=table_name,
                count=_DEFAULT_TEMPLATE_COUNT,
                columns=[],
            )
        )
    else:
        connection_target = url if url else db_path
        if connection_target is None:
            raise ValueError("Either db_path or url must be provided.")
        from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

        try:
            for tbl_name in _read_table_names(connection_target):
                tables.append(
                    TableConfig(
                        name=tbl_name,
                        count=_DEFAULT_TEMPLATE_COUNT,
                        columns=[],
                    )
                )
        except (OSError, ValueError, RuntimeError, SQLAlchemyError):
            logger.warning("Could not read tables from database", target=connection_target)

    return GeneratorConfig(
        db_path=db_path,
        url=url,
        tables=tables,
    )
