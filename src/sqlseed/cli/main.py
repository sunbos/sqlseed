from __future__ import annotations

import click

from sqlseed._version import __version__


@click.group()
@click.version_option(version=__version__, prog_name="sqlseed")
def cli() -> None:
    """sqlseed - Declarative SQLite test data generation toolkit."""
    pass


@cli.command()
@click.argument("db_path", required=False)
@click.option("--table", "-t", default=None, help="Target table name")
@click.option("--count", "-n", default=1000, type=int, help="Number of rows to generate")
@click.option("--provider", "-p", default="mimesis", help="Data provider (mimesis|faker|base)")
@click.option("--locale", "-l", default="en_US", help="Locale for data generation")
@click.option("--seed", "-s", default=None, type=int, help="Random seed for reproducibility")
@click.option("--batch-size", "-b", default=5000, type=int, help="Batch size for insertion")
@click.option("--clear", is_flag=True, help="Clear table before generating")
@click.option("--config", "-c", "config_path", default=None, help="YAML/JSON config file path")
@click.option("--transform", "transform_path", default=None, help="Python transform script path")
@click.option("--snapshot", is_flag=True, help="Save generation snapshot for replay")
@click.option("--enrich", is_flag=True, help="Enrich data using existing table distribution")
def fill(
    db_path: str | None,
    table: str | None,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    config_path: str | None,
    transform_path: str | None,
    snapshot: bool,
    enrich: bool,
) -> None:
    """Fill a table with generated test data.

    Use --config for config-driven generation, or provide db_path + --table
    for direct generation.
    """
    if config_path:
        from sqlseed import fill_from_config

        results = fill_from_config(config_path)
        for result in results:
            click.echo(str(result))
        return

    if not db_path:
        raise click.UsageError("db_path is required when not using --config")
    if not table:
        raise click.UsageError("--table is required when not using --config")

    from sqlseed import fill as api_fill

    transform_fn = None
    if transform_path:
        from sqlseed.core.transform import load_transform

        transform_fn = load_transform(transform_path)
        click.echo(f"Transform script loaded: {transform_path}")

    result = api_fill(
        db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        clear_before=clear,
        enrich=enrich,
    )
    click.echo(str(result))

    if transform_fn:
        click.echo(f"Transform applied: {transform_path}")

    if snapshot:
        from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
        from sqlseed.config.snapshot import SnapshotManager

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


@cli.command()
@click.argument("db_path")
@click.option("--table", "-t", required=True, help="Target table name")
@click.option("--count", "-n", default=5, type=int, help="Number of rows to preview")
@click.option("--provider", "-p", default="mimesis", help="Data provider")
@click.option("--locale", "-l", default="en_US", help="Locale")
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
    from rich.console import Console
    from rich.table import Table as RichTable

    from sqlseed import preview as api_preview

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


@cli.command()
@click.argument("db_path")
@click.option("--table", "-t", default=None, help="Specific table to inspect")
@click.option("--show-mapping", is_flag=True, help="Show column mapping strategy")
def inspect(db_path: str, table: str | None, show_mapping: bool) -> None:
    """Inspect database schema and column mapping strategies."""
    from rich.console import Console
    from rich.table import Table as RichTable

    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        console = Console()

        tables = [table] if table else orch._db.get_table_names()

        for tbl in tables:
            count = orch._db.get_row_count(tbl)
            columns = orch._schema.get_column_info(tbl)
            fks = orch._db.get_foreign_keys(tbl)

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
                    "✓" if col.nullable else "✗",
                    "✓" if col.is_primary_key else "",
                    "✓" if col.is_autoincrement else "",
                ]
                if show_mapping:
                    spec = orch._mapper.map_column(col)
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
@click.argument("config_path")
@click.option("--db", default="test.db", help="Database path for template")
def init(config_path: str, db: str) -> None:
    """Generate a YAML configuration template."""
    from sqlseed.config.loader import generate_template, save_config

    config = generate_template(db)
    save_config(config, config_path)
    click.echo(f"Configuration template saved to: {config_path}")


@cli.command()
@click.argument("snapshot_path")
def replay(snapshot_path: str) -> None:
    """Replay a previously saved snapshot."""
    from sqlseed.config.snapshot import SnapshotManager

    manager = SnapshotManager()
    result = manager.replay(snapshot_path)
    click.echo(str(result))


@cli.command("ai-suggest")
@click.argument("db_path")
@click.option("--table", "-t", required=True, help="Target table name")
@click.option("--output", "-o", required=True, help="Output YAML file path")
@click.option("--model", "-m", default=None, help="AI model name (default: qwen3-coder-plus)")
@click.option("--api-key", envvar="SQLSEED_AI_API_KEY", default=None, help="AI API key")
@click.option("--base-url", envvar="SQLSEED_AI_BASE_URL", default=None, help="AI API base URL")
@click.option("--max-retries", default=3, type=int, help="Max refinement retries (0=disable)")
@click.option("--verify/--no-verify", default=True, help="Enable AI config self-correction")
@click.option("--no-cache", is_flag=True, help="Skip cached AI configs")
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
) -> None:
    """Analyze table schema and suggest generation rules via AI."""
    import yaml
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIConfig

    ai_config = AIConfig(api_key=api_key, base_url=base_url)
    if model:
        ai_config.model = model

    analyzer = SchemaAnalyzer(config=ai_config)

    if verify and max_retries > 0:
        from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

        refiner = AiConfigRefiner(analyzer, db_path)
        try:
            result = refiner.generate_and_refine(
                table_name=table,
                max_retries=max_retries,
                no_cache=no_cache,
            )
        except AISuggestionFailedError as e:
            click.echo(f"AI suggestion failed: {e}", err=True)
            return
    else:
        from sqlseed.core.orchestrator import DataOrchestrator

        with DataOrchestrator(db_path) as orch:
            schema_ctx = orch.get_schema_context(table)
            messages = analyzer.build_initial_messages(
                table_name=schema_ctx["table_name"],
                columns=schema_ctx["columns"],
                indexes=schema_ctx["indexes"],
                sample_data=schema_ctx["sample_data"],
                foreign_keys=schema_ctx["foreign_keys"],
                all_table_names=schema_ctx["all_table_names"],
                distribution_profiles=schema_ctx.get("distribution"),
            )
            try:
                result = analyzer.call_llm(messages)
            except (ValueError, RuntimeError) as e:
                click.echo(f"AI suggestion failed: {e}", err=True)
                return

    if result:
        output_data = {
            "db_path": db_path,
            "provider": "mimesis",
            "locale": "zh_CN",
            "tables": [result],
        }
        with open(output, "w", encoding="utf-8") as f:
            yaml.dump(output_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        click.echo(f"AI suggestions saved to {output}")
    else:
        click.echo("No suggestions received. Ensure sqlseed-ai plugin is installed and API key is configured.")
        click.echo("Set SQLSEED_AI_API_KEY environment variable or use --api-key option.")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
