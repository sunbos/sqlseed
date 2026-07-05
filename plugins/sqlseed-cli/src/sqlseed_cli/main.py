"""sqlseed CLI entry module.

Defines the `cli` group and core subcommands: fill, preview, inspect, init, replay.
AI-related commands (e.g. ai-suggest) are discovered via the
``sqlseed.cli_commands`` entry-point group and registered by
``sqlseed_cli.__init__`` (no source-level import of sqlseed-ai).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import pydantic
from rich.console import Console
from rich.table import Table as RichTable

from sqlseed import fill as api_fill
from sqlseed import fill_from_config
from sqlseed import preview as api_preview
from sqlseed._utils.logger import configure_logging, get_logger
from sqlseed._utils.paths import get_cache_dir
from sqlseed._version import __version__
from sqlseed.config.loader import generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)

# Redact credentials (user:pass@) in database URLs so error messages never
# leak secrets, e.g. "postgresql://admin:s3cret@host/db" -> "postgresql://***:***@host/db".
_CREDENTIAL_PATTERN = re.compile(r"://[^:@/\s]+:[^@/\s]+@")


def _redact_credentials(text: str) -> str:
    """Redact credentials in URLs to prevent leaking secrets in error messages.

    Replaces the ``user:pass@`` segment of a URL with ``***:***@``.
    """
    return _CREDENTIAL_PATTERN.sub("://***:***@", text)


@click.group()
@click.version_option(version=__version__, prog_name="sqlseed")
def cli() -> None:
    """sqlseed - Declarative SQLite test data generation toolkit."""
    log_level = os.environ.get("SQLSEED_LOG_LEVEL", "WARNING").upper()
    configure_logging(log_level)


def _fill_from_config_cmd(config_path: str, *, clear_before: bool = False, **kwargs: Any) -> None:
    config = load_config(config_path)
    table_count = len(config.tables)
    click.echo(f"Loading config: {config_path} ({table_count} table(s))")

    any_clear = clear_before or any(tc.clear_before for tc in config.tables)
    if not any_clear:
        click.echo("Note: Data will be appended. Use --clear to reset tables before generation.")

    results = fill_from_config(config_path, clear_before=clear_before, **kwargs)
    for result in results:
        click.echo(str(result))


def _save_snapshot_cmd(
    db_path: str | None,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    *,
    url: str | None = None,
) -> None:
    config = GeneratorConfig(
        db_path=db_path,
        url=url,
        provider=ProviderType(provider),
        locale=locale,
        tables=[
            TableConfig(
                name=table,
                count=count,
                batch_size=batch_size,
                clear_before=clear,
                seed=seed,
            )
        ],
    )
    manager = SnapshotManager()
    snapshot_path = manager.save(config, table, count, seed)
    click.echo(f"Snapshot saved: {snapshot_path}")


_FILL_DEFAULT_COUNT = 1000
# Upper bound for --count to prevent memory exhaustion from accidental huge values.
_MAX_COUNT = 10_000_000


@dataclass(frozen=True)
class ConnectionTarget:
    """Connection target for the ``fill`` command (mutually exclusive)."""

    db_path: str | None
    db_url: str | None


@dataclass(frozen=True)
class FillGeneratorConfig:
    """Generator configuration for the ``fill`` command."""

    provider: str
    locale: str
    seed: int | None
    batch_size: int


@dataclass(frozen=True)
class FillFlags:
    """Boolean flags for the ``fill`` command."""

    clear: bool
    snapshot: bool
    enrich: bool
    no_ai: bool


@dataclass(frozen=True)
class FillOptions:
    """Encapsulates all options for the ``fill`` command.

    Passed from the Click ``fill`` command to ``_execute_fill`` to avoid
    duplicating the 14-parameter list in both function signatures (which
    triggered pylint ``duplicate-code`` warnings). Fields are grouped into
    sub-dataclasses (ConnectionTarget, FillGeneratorConfig, FillFlags) to keep
    the instance attribute count under pylint's too-many-instance-attributes
    threshold (11).
    """

    connection: ConnectionTarget
    generator: FillGeneratorConfig
    flags: FillFlags
    table: str | None
    count: int | None
    config_path: str | None
    transform_path: str | None


@cli.command()
@click.argument("db_path", required=False)
@click.option("--table", "-t", default=None, help="Target table name")
@click.option(
    "--count",
    "-n",
    default=None,
    type=int,
    help="Number of rows to generate (required when not using --config)",
)
@click.option(
    "--provider",
    "-p",
    default="mimesis",
    help="Data provider: mimesis|faker|base (default: mimesis)",
)
@click.option("--locale", "-l", default="en_US", help="Locale for data generation (default: en_US)")
@click.option("--seed", "-s", default=None, type=int, help="Random seed for reproducibility")
@click.option(
    "--batch-size",
    "-b",
    default=5000,
    type=int,
    help="Batch size for insertion (default: 5000)",
)
@click.option("--clear", is_flag=True, help="Clear table before generating")
@click.option("--config", "-c", "config_path", default=None, help="YAML/JSON config file path")
@click.option("--transform", "transform_path", default=None, help="Python transform script path")
@click.option("--snapshot", is_flag=True, help="Save generation snapshot for replay")
@click.option("--enrich", is_flag=True, help="Enrich data using existing table distribution")
@click.option("--no-ai", is_flag=True, help="Skip AI suggestions and template generation")
@click.option(
    "--url",
    "db_url",
    default=None,
    help="Database URL (e.g., postgresql://user:pass@host/db). Alternative to db_path argument.",
)
def fill(**kwargs: Any) -> None:
    """Fill a table with generated test data.

    Use --config for config-driven generation, or provide db_path + --table
    + --count for direct generation. When using --config, CLI options
    override the corresponding YAML values.

    Connection methods (mutually exclusive):
    - Positional db_path: sqlseed fill app.db -t users -n 1000
    - --url flag: sqlseed fill --url "postgresql://user:pass@host/db" -t users -n 1000

    Note: the 14 Click options are collected via ``**kwargs`` to keep the
    function signature under pylint's too-many-arguments threshold (10).
    The kwargs are unpacked into a ``FillOptions`` dataclass below, which
    is then passed to ``_execute_fill``.
    """
    db_path: str | None = kwargs["db_path"]
    table: str | None = kwargs["table"]
    count: int | None = kwargs["count"]
    provider: str = kwargs["provider"]
    locale: str = kwargs["locale"]
    seed: int | None = kwargs["seed"]
    batch_size: int = kwargs["batch_size"]
    clear: bool = kwargs["clear"]
    config_path: str | None = kwargs["config_path"]
    transform_path: str | None = kwargs["transform_path"]
    snapshot: bool = kwargs["snapshot"]
    enrich: bool = kwargs["enrich"]
    no_ai: bool = kwargs["no_ai"]
    db_url: str | None = kwargs["db_url"]

    if count is not None and count <= 0:
        logger.debug("Invalid count value", count=count)
        raise click.UsageError(f"--count must be greater than 0, got {count}")

    if count is not None and count > _MAX_COUNT:
        logger.debug("Count exceeds maximum", count=count, max_count=_MAX_COUNT)
        raise click.UsageError(f"--count must be <= {_MAX_COUNT}, got {count}")

    if not config_path and count is None:
        raise click.UsageError(
            "--count is required when not using --config. Use -n <number> to specify the number of rows to generate."
        )

    # Validate that db_path and --url are mutually exclusive
    if db_path and db_url:
        raise click.UsageError("Cannot specify both positional db_path and --url. Use one or the other.")
    if not config_path and not db_path and not db_url:
        raise click.UsageError("db_path or --url is required when not using --config.")

    options = FillOptions(
        connection=ConnectionTarget(db_path=db_path, db_url=db_url),
        generator=FillGeneratorConfig(provider=provider, locale=locale, seed=seed, batch_size=batch_size),
        flags=FillFlags(clear=clear, snapshot=snapshot, enrich=enrich, no_ai=no_ai),
        table=table,
        count=count,
        config_path=config_path,
        transform_path=transform_path,
    )
    _execute_fill(options)


def _execute_fill(options: FillOptions) -> None:
    config_path = options.config_path
    if config_path:
        logger.debug("Using config-driven generation", config_path=config_path)
        _fill_from_config_cmd(
            config_path,
            clear_before=options.flags.clear,
            skip_ai=options.flags.no_ai,
            count=options.count,
            provider=options.generator.provider,
            seed=options.generator.seed,
            batch_size=options.generator.batch_size,
            locale=options.generator.locale,
        )
        return

    if not options.table:
        raise click.UsageError("--table is required when not using --config")

    effective_count = options.count if options.count is not None else _FILL_DEFAULT_COUNT

    # Resolve connection target: db_url takes precedence over db_path.
    # api_fill's db_path and url are mutually exclusive; pass None for the unused one.
    if options.connection.db_url:
        fill_db_path: str | None = None
        fill_url: str | None = options.connection.db_url
    else:
        fill_db_path = options.connection.db_path
        fill_url = None

    if not (fill_db_path or fill_url):
        raise click.UsageError("db_path or --url is required when not using --config")

    logger.debug("Starting fill", target=fill_url or fill_db_path, table=options.table, count=effective_count)

    try:
        result = api_fill(
            fill_db_path,
            url=fill_url,
            table=options.table,
            count=effective_count,
            provider=options.generator.provider,
            locale=options.generator.locale,
            seed=options.generator.seed,
            batch_size=options.generator.batch_size,
            clear_before=options.flags.clear,
            enrich=options.flags.enrich,
            transform=options.transform_path,
            skip_ai=options.flags.no_ai,
        )
    except ValueError as exc:
        logger.debug("Fill failed with ValueError", error=str(exc))
        raise click.UsageError(_redact_credentials(str(exc))) from exc
    click.echo(str(result))
    if result.errors:
        for err in result.errors:
            click.echo(f"  Warning: {err}", err=True)

    if options.flags.snapshot:
        _save_snapshot_cmd(
            db_path=fill_db_path,
            table=options.table,
            count=effective_count,
            provider=options.generator.provider,
            locale=options.generator.locale,
            seed=options.generator.seed,
            batch_size=options.generator.batch_size,
            clear=options.flags.clear,
            url=fill_url,
        )

    # Generation completed with errors: exit non-zero so callers/scripts can detect partial failure.
    if result.errors:
        raise SystemExit(1)


@cli.command()
@click.argument("db_path", required=False)
@click.option("--table", "-t", required=True, help="Target table name")
@click.option("--count", "-n", default=5, type=int, help="Number of rows to preview (default: 5)")
@click.option(
    "--provider",
    "-p",
    default="mimesis",
    help="Data provider: mimesis|faker|base (default: mimesis)",
)
@click.option("--locale", "-l", default="en_US", help="Locale (default: en_US)")
@click.option("--seed", "-s", default=None, type=int, help="Random seed")
@click.option(
    "--url",
    "db_url",
    default=None,
    help="Database URL (e.g., postgresql://user:pass@host/db). Alternative to db_path argument.",
)
def preview(
    db_path: str | None,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    db_url: str | None,
) -> None:
    """Preview generated data without writing to database.

    Connection methods (mutually exclusive):
    - Positional db_path: sqlseed preview app.db -t users
    - --url flag: sqlseed preview --url "postgresql://..." -t users
    """
    if db_path and db_url:
        raise click.UsageError("Cannot specify both positional db_path and --url. Use one or the other.")
    if not db_path and not db_url:
        raise click.UsageError("db_path or --url is required.")

    try:
        rows = api_preview(
            db_path,
            url=db_url,
            table=table,
            count=count,
            provider=provider,
            locale=locale,
            seed=seed,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        logger.debug("Preview failed", error=str(exc))
        raise click.UsageError(_redact_credentials(str(exc))) from exc

    if not rows:
        click.echo("No data generated.")
        return

    console = Console()
    rich_table = RichTable(title=f"Preview: {table} ({count} rows)")

    for col_name in rows[0]:
        rich_table.add_column(col_name)

    for row in rows:
        rich_table.add_row(*[str(v) for v in row.values()])

    console.print(rich_table)


def _print_foreign_keys(fks: list[Any], tbl: str, console: Any) -> None:
    if not fks:
        return
    fk_table = RichTable(title=f"Foreign Keys: {tbl}")
    fk_table.add_column("Column")
    fk_table.add_column("Ref Table")
    fk_table.add_column("Ref Column")
    for fk in fks:
        fk_table.add_row(fk.column, fk.ref_table, fk.ref_column)
    console.print(fk_table)


def _inspect_table(orch: Any, tbl: str, show_mapping: bool, console: Any) -> None:
    count = orch.get_row_count(tbl)
    columns = orch.get_column_info(tbl)
    fks = orch.get_foreign_keys(tbl)

    rich_table = RichTable(title=f"Table: {tbl} ({count} rows)")
    rich_table.add_column("Column")
    rich_table.add_column("Type")
    rich_table.add_column("Nullable")
    rich_table.add_column("PK")
    rich_table.add_column("Auto")

    generator_specs = None
    if show_mapping:
        rich_table.add_column("Generator")
        rich_table.add_column("Params")
        generator_specs = orch.get_column_mapping(tbl)

    for col in columns:
        row_data = [
            col.name,
            col.type,
            "\u2713" if col.nullable else "\u2717",
            "\u2713" if col.is_primary_key else "",
            "\u2713" if col.is_autoincrement else "",
        ]
        if show_mapping and generator_specs:
            spec = generator_specs.get(col.name)
            if spec:
                row_data.extend([spec.generator_name, str(spec.params)])
            else:
                row_data.extend(["skip", "{}"])
        rich_table.add_row(*row_data)

    console.print(rich_table)
    _print_foreign_keys(fks, tbl, console)


@cli.command()
@click.argument("db_path", required=False)
@click.option("--table", "-t", default=None, help="Specific table to inspect")
@click.option("--show-mapping", is_flag=True, help="Show column mapping strategy")
@click.option(
    "--url",
    "db_url",
    default=None,
    help="Database URL (e.g., postgresql://user:pass@host/db). Alternative to db_path argument.",
)
def inspect(db_path: str | None, table: str | None, show_mapping: bool, db_url: str | None) -> None:
    """Inspect database schema and column mapping strategies.

    Connection methods (mutually exclusive):
    - Positional db_path: sqlseed inspect app.db
    - --url flag: sqlseed inspect --url "postgresql://..."
    """
    if db_path and db_url:
        raise click.UsageError("Cannot specify both positional db_path and --url. Use one or the other.")
    target = db_url or db_path
    if not target:
        raise click.UsageError("db_path or --url is required.")
    try:
        with DataOrchestrator(target) as orch:
            console = Console()

            tables = [table] if table else orch.get_table_names()

            for tbl in tables:
                _inspect_table(orch, tbl, show_mapping, console)
    except (ValueError, RuntimeError, OSError) as exc:
        logger.debug("Inspect failed", error=str(exc))
        raise click.UsageError(_redact_credentials(str(exc))) from exc


@cli.command()
@click.argument("config_path")
@click.option("--db", default=None, help="Database path for template (default: test.db)")
@click.option(
    "--url",
    "db_url",
    default=None,
    help="Database URL (e.g., postgresql://user:pass@host/db). Alternative to --db.",
)
def init(config_path: str, db: str | None, db_url: str | None) -> None:
    """Generate a YAML configuration template.

    Connection methods (mutually exclusive):
    - --db flag: sqlseed init config.yaml --db app.db
    - --url flag: sqlseed init config.yaml --url "postgresql://..."

    If neither --db nor --url is provided, --db defaults to "test.db".
    """
    if db and db_url:
        raise click.UsageError("Cannot specify both --db and --url. Use one or the other.")

    # Apply the "test.db" default only when neither --db nor --url was provided.
    # Previously --db had default="test.db" which made `db` always truthy,
    # causing the mutual-exclusion check above to always fire when --url was
    # passed — rendering `init --url` completely unusable.
    if not db and not db_url:
        db = "test.db"

    effective_db = None if db_url else db

    try:
        config = generate_template(db_path=effective_db, url=db_url)
        save_config(config, config_path)
    except (ValueError, RuntimeError, OSError) as exc:
        logger.debug("Init failed", error=str(exc))
        raise click.UsageError(_redact_credentials(str(exc))) from exc
    click.echo(f"Configuration template saved to: {config_path}")


@cli.command()
@click.argument("snapshot_path")
def replay(snapshot_path: str) -> None:
    """Replay a previously saved snapshot."""
    # Security: block path-traversal attempts. A snapshot path containing ``..``
    # that resolves outside the cache directory is rejected to prevent reading
    # arbitrary files. Absolute paths without ``..`` are allowed so that users
    # can still replay snapshots from custom directories.
    cache_dir = get_cache_dir("snapshots")
    resolved_path = Path(snapshot_path).resolve()
    if ".." in Path(snapshot_path).parts and not resolved_path.is_relative_to(cache_dir):
        raise click.UsageError("snapshot path must be within cache directory")

    manager = SnapshotManager()
    try:
        data = manager.load(snapshot_path)
    except FileNotFoundError as exc:
        raise click.UsageError(f"Snapshot file not found: {snapshot_path}") from exc
    except (ValueError, KeyError) as exc:
        raise click.UsageError(_redact_credentials(f"Invalid snapshot file format: {exc}")) from exc

    try:
        config = GeneratorConfig(**data["config"])
    except (pydantic.ValidationError, KeyError, TypeError) as exc:
        raise click.UsageError(_redact_credentials(f"Invalid config in snapshot: {exc}")) from exc

    try:
        table_name = data["table_name"]
        count = data["count"]
    except (KeyError, TypeError) as exc:
        raise click.UsageError(f"Invalid snapshot file format: {exc}") from exc
    seed = data.get("seed")

    table_config = None
    for tc in config.tables:
        if tc.name == table_name:
            table_config = tc
            break

    with DataOrchestrator.from_config(config) as orch:
        result = orch.fill_table(
            table_name=table_name,
            count=count,
            seed=seed,
            batch_size=table_config.batch_size if table_config else 5000,
            clear_before=table_config.clear_before if table_config else False,
            column_configs=table_config.columns if table_config else None,
        )
    click.echo(str(result))
    if result.errors:
        for err in result.errors:
            click.echo(f"  Warning: {err}", err=True)
        raise SystemExit(1)


def main() -> None:
    """Entry point for the ``sqlseed`` console script (registered via ``[project.scripts]``)."""
    cli()


if __name__ == "__main__":
    main()
