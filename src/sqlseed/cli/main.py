from __future__ import annotations

import os
import re
import signal
from typing import Any

import click
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
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

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

    HAS_AI_PLUGIN = True
except ImportError:
    HAS_AI_PLUGIN = False


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

    if not config_path and count is None:
        count = _FILL_DEFAULT_COUNT

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

    if show_mapping:
        rich_table.add_column("Generator")
        rich_table.add_column("Params")

    for col in columns:
        row_data = [
            col.name,
            col.type,
            "\u2713" if col.nullable else "\u2717",
            "\u2713" if col.is_primary_key else "",
            "\u2713" if col.is_autoincrement else "",
        ]
        if show_mapping:
            spec = orch.map_column(col)
            row_data.extend([spec.generator_name, str(spec.params)])
        rich_table.add_row(*row_data)

    console.print(rich_table)

    if fks:
        fk_table = RichTable(title=f"Foreign Keys: {tbl}")
        fk_table.add_column("Column")
        fk_table.add_column("Ref Table")
        fk_table.add_column("Ref Column")
        for fk in fks:
            fk_table.add_row(fk.column, fk.ref_table, fk.ref_column)
        console.print(fk_table)


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
    result = manager.replay(snapshot_path)
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


def _handle_ai_verification(analyzer: Any, db_path: str, table: str, max_retries: int, no_cache: bool) -> Any:

    refiner = AiConfigRefiner(analyzer, db_path)
    try:
        return refiner.generate_and_refine(
            table_name=table,
            max_retries=max_retries,
            no_cache=no_cache,
        )
    except AISuggestionFailedError as e:
        click.echo(f"AI suggestion failed: {e}", err=True)
        return None


def _handle_ai_direct(analyzer: Any, db_path: str, table: str) -> Any:
    with DataOrchestrator(db_path) as orch:
        schema_ctx = orch.get_schema_context(table)
        messages = analyzer.build_initial_messages(schema_ctx)
        try:
            return analyzer.call_llm(messages)
        except (ValueError, RuntimeError) as e:
            click.echo(f"AI suggestion failed: {e}", err=True)
            return None


def _run_ai_analysis(
    analyzer: Any,
    db_path: str,
    table: str,
    verify: bool,
    max_retries: int,
    no_cache: bool,
) -> Any:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=Console(),
        transient=False,
    ) as progress:
        task = progress.add_task("Analyzing schema & generating AI suggestions...", total=None)
        if verify and max_retries > 0:
            result = _handle_ai_verification(analyzer, db_path, table, max_retries, no_cache)
        else:
            result = _handle_ai_direct(analyzer, db_path, table)
        progress.update(task, completed=1, total=1)
    return result


def _write_ai_output(output: str, db_path: str, result: Any) -> None:
    _sanitize_table_config(result)
    output_data = {
        "db_path": db_path,
        "provider": "mimesis",
        "locale": "en_US",
        "tables": [result],
    }
    yaml_str = yaml.dump(output_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    lines = yaml_str.split("\n")
    result_lines: list[str] = []
    for line in lines:
        result_lines.append(line)
        if line.strip().startswith("count:"):
            indent = len(line) - len(line.lstrip())
            result_lines.append(
                " " * indent + "# clear_before: true  # Uncomment to clear existing data before generation"
            )
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(result_lines))
    click.echo(f"AI suggestions saved to {output}")
    click.echo("Tip: Add 'clear_before: true' to reset data before generation, or use --clear flag.")


def _report_ai_failure() -> None:
    click.echo(
        "No suggestions received. The AI model may not support this task.\n"
        "Suggestions:\n"
        "  - Try a different model: --model 'deepseek/deepseek-r1-0528:free'\n"
        "  - Use DeepSeek API: --base-url 'https://api.deepseek.com/v1' --model 'deepseek-chat'\n"
        "  - Use OpenAI API: --base-url 'https://api.openai.com/v1' --model 'gpt-4o-mini'\n"
        "  - Increase timeout: --timeout 180",
        err=True,
    )
    raise SystemExit(1)


@cli.command("ai-suggest")
@click.argument("db_path")
@click.option("--table", "-t", required=True, help="Target table name")
@click.option("--output", "-o", required=True, help="Output YAML file path")
@click.option("--model", "-m", default=None, help="AI model name (default: auto-select best free model via OpenRouter)")
@click.option("--api-key", envvar="SQLSEED_AI_API_KEY", default=None, help="AI API key (env: SQLSEED_AI_API_KEY)")
@click.option(
    "--base-url",
    envvar="SQLSEED_AI_BASE_URL",
    default=None,
    help="AI API base URL (env: SQLSEED_AI_BASE_URL)",
)
@click.option("--max-retries", default=3, type=int, help="Max refinement retries, 0=disable (default: 3)")
@click.option("--verify/--no-verify", default=True, help="Enable AI config self-correction (default: verify)")
@click.option("--no-cache", is_flag=True, help="Skip cached AI configs")
@click.option("--timeout", default=120, type=float, help="API call timeout in seconds (default: 120)")
def ai_suggest(
    db_path: str,
    table: str,
    output: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    max_retries: int,
    verify: bool,
    no_cache: bool,
    timeout: float,
) -> None:
    """Analyze table schema and suggest generation rules via AI."""
    if not HAS_AI_PLUGIN:
        raise click.UsageError("sqlseed-ai plugin is required for this command. Run `pip install sqlseed-ai`.")

    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)
    ai_config.timeout = timeout

    if not ai_config.api_key:
        click.echo(
            "Error: AI API key not configured. Set SQLSEED_AI_API_KEY or OPENAI_API_KEY, or use --api-key.",
            err=True,
        )
        raise SystemExit(1)

    resolved_model = ai_config.resolve_model()
    click.echo(f"Using AI model: {resolved_model} (via OpenRouter)")

    analyzer = SchemaAnalyzer(config=ai_config)
    total_timeout = timeout * 2

    old_handler: Any = None
    if hasattr(signal, "SIGALRM"):
        old_handler = signal.signal(signal.SIGALRM, lambda _s, _f: _sigalrm_handler(total_timeout))
        signal.alarm(int(total_timeout))

    try:
        result = _run_ai_analysis(analyzer, db_path, table, verify, max_retries, no_cache)
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)

    if ai_config.model != resolved_model:
        click.echo(f"Model fallback: {resolved_model} → {ai_config.model}")

    if result:
        _write_ai_output(output, db_path, result)
    else:
        _report_ai_failure()


def _sigalrm_handler(total_timeout: float) -> None:
    click.echo(
        f"\nError: AI suggestion timed out after {total_timeout:.0f}s. "
        "Try a different model with --model, or increase timeout with --timeout.",
        err=True,
    )
    raise SystemExit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
