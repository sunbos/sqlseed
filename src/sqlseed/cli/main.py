from __future__ import annotations

import click

from sqlseed._version import __version__


@click.group()
@click.version_option(version=__version__, prog_name="sqlseed")
def cli() -> None:
    """sqlseed - Declarative SQLite test data generation toolkit."""
    pass


@cli.command()
@click.argument("db_path")
@click.option("--table", "-t", required=True, help="Target table name")
@click.option("--count", "-n", default=1000, type=int, help="Number of rows to generate")
@click.option("--provider", "-p", default="mimesis", help="Data provider (mimesis|faker|base)")
@click.option("--locale", "-l", default="en_US", help="Locale for data generation")
@click.option("--seed", "-s", default=None, type=int, help="Random seed for reproducibility")
@click.option("--batch-size", "-b", default=5000, type=int, help="Batch size for insertion")
@click.option("--clear", is_flag=True, help="Clear table before generating")
@click.option("--config", "-c", "config_path", default=None, help="YAML/JSON config file path")
@click.option("--snapshot", is_flag=True, help="Save generation snapshot for replay")
def fill(
    db_path: str,
    table: str,
    count: int,
    provider: str,
    locale: str,
    seed: int | None,
    batch_size: int,
    clear: bool,
    config_path: str | None,
    snapshot: bool,
) -> None:
    """Fill a table with generated test data."""
    if config_path:
        from sqlseed import fill_from_config

        results = fill_from_config(config_path)
        for result in results:
            click.echo(str(result))
        return

    from sqlseed import fill as api_fill

    result = api_fill(
        db_path,
        table=table,
        count=count,
        provider=provider,
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        clear_before=clear,
    )
    click.echo(str(result))

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
def ai_suggest(db_path: str, table: str, output: str) -> None:
    """Analyze table schema and suggest generation rules via AI."""
    import yaml
    from sqlseed.core.orchestrator import DataOrchestrator

    with DataOrchestrator(db_path) as orch:
        columns = orch._schema.get_column_info(table)
        fks = orch._db.get_foreign_keys(table)
        all_tables = orch._db.get_table_names()
        
        sample_data = []
        try:
            sample_data = orch._db.get_column_values(table, columns[0].name, limit=5)
        except Exception:
            pass
            
        import typing
        indexes: list[dict[str, typing.Any]] = []
        
        result = orch._plugins.hook.sqlseed_ai_analyze_table(
            table_name=table,
            columns=columns,
            indexes=indexes,
            sample_data=sample_data,
            foreign_keys=fks,
            all_table_names=all_tables,
        )
        
        if result:
            with open(output, "w", encoding="utf-8") as f:
                yaml.dump({"tables": [result]}, f, allow_unicode=True, sort_keys=False)
            click.echo(f"Suggestions saved to {output}")
        else:
            click.echo("No suggestions received from AI plugin.")

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
