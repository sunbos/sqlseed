from __future__ import annotations

import os
import re
from typing import Any

import click
from rich.console import Console
from rich.table import Table as RichTable

from sqlseed import fill as api_fill
from sqlseed import fill_from_config
from sqlseed import preview as api_preview
from sqlseed._utils.logger import configure_logging, get_logger
from sqlseed._version import __version__
from sqlseed.config.loader import generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)


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
    db_path: str,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
) -> None:
    config = GeneratorConfig(
        db_path=db_path,
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
def fill(**kwargs: Any) -> None:
    """Fill a table with generated test data.

    Use --config for config-driven generation, or provide db_path + --table
    + --count for direct generation. When using --config, CLI options
    override the corresponding YAML values.
    """
    count = kwargs.get("count")
    config_path = kwargs.get("config_path")

    if count is not None and count <= 0:
        logger.debug("Invalid count value", count=count)
        raise click.UsageError(f"--count must be greater than 0, got {count}")

    if not config_path and count is None:
        raise click.UsageError(
            "--count is required when not using --config. Use -n <number> to specify the number of rows to generate."
        )

    kwargs["count"] = count
    _execute_fill(kwargs)


def _execute_fill(opts: dict[str, Any]) -> None:
    config_path = opts.get("config_path")
    if config_path:
        logger.debug("Using config-driven generation", config_path=config_path)
        _fill_from_config_cmd(
            config_path,
            clear_before=opts.get("clear", False),
            skip_ai=opts.get("no_ai", False),
            count=opts.get("count"),
            provider=opts.get("provider"),
            seed=opts.get("seed"),
            batch_size=opts.get("batch_size"),
            locale=opts.get("locale"),
        )
        return

    db_path = opts.get("db_path")
    table = opts.get("table")
    if not db_path:
        raise click.UsageError("db_path is required when not using --config")
    if not table:
        raise click.UsageError("--table is required when not using --config")

    count = opts.get("count", _FILL_DEFAULT_COUNT)
    provider = opts.get("provider", "mimesis")
    locale = opts.get("locale", "en_US")
    seed = opts.get("seed")
    batch_size = opts.get("batch_size", 5000)
    clear_before = opts.get("clear", False)
    enrich = opts.get("enrich", False)
    transform = opts.get("transform_path")
    skip_ai = opts.get("no_ai", False)

    logger.debug("Starting fill", db_path=db_path, table=table, count=count)

    try:
        result = api_fill(
            db_path,
            table=table,
            count=count,
            provider=provider,
            locale=locale,
            seed=seed,
            batch_size=batch_size,
            clear_before=clear_before,
            enrich=enrich,
            transform=transform,
            skip_ai=skip_ai,
        )
    except ValueError as exc:
        logger.debug("Fill failed with ValueError", error=str(exc))
        raise click.UsageError(str(exc)) from exc
    click.echo(str(result))
    if result.errors:
        for err in result.errors:
            click.echo(f"  Warning: {err}", err=True)

    if opts.get("snapshot"):
        _save_snapshot_cmd(
            db_path,
            table,
            count,
            provider,
            locale,
            seed,
            batch_size,
            clear_before,
        )


@cli.command()
@click.argument("db_path")
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
def preview(
    db_path: str,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
) -> None:
    """Preview generated data without writing to database."""
    rows = api_preview(
        db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
    )

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
@click.argument("db_path")
@click.option("--table", "-t", default=None, help="Specific table to inspect")
@click.option("--show-mapping", is_flag=True, help="Show column mapping strategy")
def inspect(db_path: str, table: str | None, show_mapping: bool) -> None:
    """Inspect database schema and column mapping strategies."""
    with DataOrchestrator(db_path) as orch:
        console = Console()

        tables = [table] if table else orch.get_table_names()

        for tbl in tables:
            _inspect_table(orch, tbl, show_mapping, console)


@cli.command()
@click.argument("config_path")
@click.option("--db", default="test.db", help="Database path for template (default: test.db)")
def init(config_path: str, db: str) -> None:
    """Generate a YAML configuration template."""
    config = generate_template(db)
    save_config(config, config_path)
    click.echo(f"Configuration template saved to: {config_path}")


@cli.command()
@click.argument("snapshot_path")
def replay(snapshot_path: str) -> None:
    """Replay a previously saved snapshot."""
    manager = SnapshotManager()
    data = manager.load(snapshot_path)
    config = GeneratorConfig(**data["config"])
    table_name = data["table_name"]
    count = data["count"]
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


def _sanitize_table_config(config_dict: dict[str, Any]) -> None:
    name = config_dict.get("name")
    if isinstance(name, str):
        config_dict["name"] = re.sub(r"^[:.]+", "", name)
    for col in config_dict.get("columns", []):
        if isinstance(col, dict):
            col_name = col.get("name")
            if isinstance(col_name, str):
                col["name"] = re.sub(r"^[:.]+", "", col_name)


def main() -> None:
    cli()


# Import AI commands to register them with the CLI group.
# Must be after `cli` is defined to avoid circular ImportError
# (ai_commands imports `cli` from this module at module level).
# NOTE: Do NOT use contextlib.suppress here — it silently swallows
# the circular ImportError that occurs when main.py is loaded first.
try:  # noqa: SIM105
    import sqlseed.cli.ai_commands  # noqa: F401
except ImportError:
    pass


if __name__ == "__main__":
    main()
