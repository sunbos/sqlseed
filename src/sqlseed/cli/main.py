from __future__ import annotations

import os
import re
import signal
from typing import Any

import click
import yaml
from rich.console import Console
from rich.live import Live
from rich.table import Table as RichTable
from rich.text import Text

from sqlseed import fill as api_fill
from sqlseed import fill_from_config
from sqlseed import preview as api_preview
from sqlseed._utils.logger import configure_logging, get_logger
from sqlseed._version import __version__
from sqlseed.config.loader import generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig, ProviderType, TableConfig
from sqlseed.config.snapshot import SnapshotManager
from sqlseed.core.orchestrator import DataOrchestrator

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner

    HAS_AI_PLUGIN = True
except ImportError:
    HAS_AI_PLUGIN = False

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
        generator_specs, _, _ = orch._resolve_specs(tbl, count=1, columns=None, column_configs=None, enrich=False)

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


class _StreamingProgressDisplay:
    """Rich Live display for streaming LLM output with phase indicators."""

    def __init__(self) -> None:
        self._phase = "connecting"
        self._model = ""
        self._token_count = 0
        self._preview = ""
        self._attempt = 0
        self._max_retries = 0
        self._live: Live | None = None

    def _render(self) -> Text:
        parts: list[tuple[str, str]] = []

        # Phase icon and description
        if self._phase == "connecting":
            parts.append(("⏳", "bold yellow"))
            parts.append((f" Connecting to {self._model}...", "yellow"))
        elif self._phase == "streaming":
            parts.append(("⚡", "bold cyan"))
            parts.append((f" Generating ({self._token_count} tokens)", "cyan"))
            if self._preview:
                parts.append((f"  {self._preview[-60:]}", "dim"))
        elif self._phase == "parsing":
            parts.append(("📋", "bold blue"))
            parts.append((f" Parsing response ({self._token_count} tokens)...", "blue"))
        elif self._phase == "validating":
            parts.append(("✅", "bold green"))
            parts.append((" Validating configuration...", "green"))
        elif self._phase == "refining":
            parts.append(("🔄", "bold yellow"))
            retry_info = f" (attempt {self._attempt + 1}/{self._max_retries})" if self._max_retries > 0 else ""
            parts.append((f" Self-correction{retry_info}...", "yellow"))
        elif self._phase == "done":
            parts.append(("✅", "bold green"))
            parts.append((f" Done ({self._token_count} tokens)", "green"))

        text = Text("")
        for content, style in parts:
            text.append(content, style=style)
        return text

    def start(self) -> None:
        self._live = Live(self._render(), console=Console(), transient=False, refresh_per_second=8)
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, phase: str, info: dict[str, Any]) -> None:
        self._phase = phase
        if "model" in info:
            self._model = info["model"]
        if "count" in info:
            self._token_count = info["count"]
        if "token" in info:
            # Show a rolling preview of the last few tokens
            self._preview += info["token"]
            if len(self._preview) > 80:
                self._preview = self._preview[-80:]
        if "tokens" in info:
            self._token_count = info["tokens"]
        if "attempt" in info:
            self._attempt = info["attempt"]
        if "max_retries" in info:
            self._max_retries = info["max_retries"]
        if self._live:
            self._live.update(self._render())


def _run_ai_analysis(
    analyzer: Any,
    db_path: str,
    table: str,
    verify: bool,
    max_retries: int,
    no_cache: bool,
) -> Any:
    config = analyzer._config
    use_streaming = config.should_use_streaming() if config else True
    use_compact = config.should_use_ultra_compact() if config else False

    # Probe inference speed for local backends and show estimated time
    if config and config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
        speed_info = config.probe_inference_speed()
        if speed_info and speed_info.get("is_slow"):
            tps = speed_info["tokens_per_second"]
            est_seconds = int(512 / tps) if tps > 0 else 120
            timeout_display = int(config.resolve_timeout())
            click.echo(
                f"Local inference speed: ~{tps} tok/s. "
                f"Estimated wait: ~{est_seconds}s (timeout: {timeout_display}s). "
                f"Using optimized settings for {config.model}.",
                err=True,
            )
        elif speed_info is None:
            # Probe failed — LM Studio may not be running
            click.echo(
                "Warning: Could not probe local inference speed. "
                "Ensure LM Studio/Ollama is running and a model is loaded.",
                err=True,
            )

    if use_streaming:
        display = _StreamingProgressDisplay()
        if verify and max_retries > 0:
            return _handle_ai_verification_streaming(
                analyzer,
                db_path,
                table,
                max_retries,
                no_cache,
                display,
                use_compact=use_compact,
            )
        return _handle_ai_direct(analyzer, db_path, table, use_compact=use_compact, display=display)

    # Small local models: non-streaming is 5-7x faster (14s vs 75-100s)
    # because streaming TTFT is extremely high on limited GPU hardware.
    if verify and max_retries > 0:
        return _handle_ai_verification_non_streaming(
            analyzer, db_path, table, max_retries, no_cache, use_compact=use_compact
        )
    return _handle_ai_direct(analyzer, db_path, table, use_compact=use_compact)


def _handle_ai_direct(
    analyzer: Any,
    db_path: str,
    table: str,
    *,
    use_compact: bool = False,
    display: _StreamingProgressDisplay | None = None,
) -> Any:
    """Handle AI direct suggestion with prompt-level fallback.

    Args:
        analyzer: SchemaAnalyzer instance.
        db_path: Path to the SQLite database.
        table: Table name to analyze.
        use_compact: Whether to force ultra-compact mode.
        display: If provided, use streaming with this progress display.
    """
    with DataOrchestrator(db_path) as orch:
        schema_ctx = orch.get_schema_context(table)

        prompt_levels = [(True, True)] if use_compact else [(False, False), (True, False), (True, True)]

        for compact, ultra in prompt_levels:
            messages = analyzer.build_initial_messages(schema_ctx, compact=compact, ultra_compact=ultra)
            try:
                if display:
                    display.start()
                    result = analyzer.call_llm_streaming(messages, on_progress=display.update)
                    display.stop()
                else:
                    mode = "ultra-compact" if ultra else ("compact" if compact else "standard")
                    timeout_s = int(analyzer._config.resolve_timeout()) if analyzer._config else 300
                    click.echo(f"Analyzing schema & generating AI suggestions ({mode} mode, timeout: {timeout_s}s)...")
                    result = analyzer.call_llm(messages)
                if result:
                    return result
                click.echo("AI returned empty result, retrying with shorter prompt...", err=True)
                continue
            except (ValueError, RuntimeError, OSError) as e:
                if display:
                    display.stop()
                err_msg = str(e).lower()
                if "context" in err_msg and "exceed" in err_msg and not ultra:
                    click.echo("Context size exceeded, retrying with shorter prompt...", err=True)
                    continue
                click.echo(f"AI suggestion failed: {e}", err=True)
                return None
    return None


def _handle_ai_verification_non_streaming(
    analyzer: Any,
    db_path: str,
    table: str,
    max_retries: int,
    no_cache: bool,
    *,
    use_compact: bool = False,
) -> Any:
    if AiConfigRefiner is None:
        raise ImportError("sqlseed-ai plugin not installed. Install with: pip install sqlseed-ai")

    refiner = AiConfigRefiner(analyzer, db_path)
    try:
        timeout_s = int(analyzer._config.resolve_timeout()) if analyzer._config else 300
        click.echo(f"Analyzing schema & generating AI suggestions with self-correction (timeout: {timeout_s}s)...")
        return refiner.generate_and_refine(
            table_name=table,
            max_retries=max_retries,
            no_cache=no_cache,
            use_compact=use_compact,
        )
    except (ValueError, RuntimeError, OSError) as e:
        click.echo(f"AI suggestion failed: {e}", err=True)
        return None


def _handle_ai_verification_streaming(
    analyzer: Any,
    db_path: str,
    table: str,
    max_retries: int,
    no_cache: bool,
    display: _StreamingProgressDisplay,
    *,
    use_compact: bool = False,
) -> Any:
    if AiConfigRefiner is None:
        raise ImportError("sqlseed-ai plugin not installed. Install with: pip install sqlseed-ai")

    refiner = AiConfigRefiner(analyzer, db_path)
    try:
        display.start()
        result = refiner.generate_and_refine_streaming(
            table_name=table,
            max_retries=max_retries,
            no_cache=no_cache,
            on_progress=display.update,
            use_compact=use_compact,
        )
        display.stop()
        return result
    except (ValueError, RuntimeError, OSError) as e:
        display.stop()
        click.echo(f"AI suggestion failed: {e}", err=True)
        return None


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
@click.option("--model", "-m", default=None, help="AI model name (default: auto-select based on backend)")
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
@click.option("--timeout", default=0, type=float, help="API call timeout in seconds (0=auto, default: auto)")
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

    if not ai_config.resolve_api_key():
        click.echo(
            "Error: AI API key not configured. "
            "Set SQLSEED_AI_API_KEY or OPENAI_API_KEY. "
            "For Google AI Studio, set GOOGLE_API_KEY. "
            "For LM Studio/Ollama, set SQLSEED_AI_BACKEND=lm_studio or ollama.",
            err=True,
        )
        raise SystemExit(1)

    resolved_model = ai_config.resolve_model()
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})")

    analyzer = SchemaAnalyzer(config=ai_config)
    resolved_timeout = ai_config.resolve_timeout()
    total_timeout = resolved_timeout * 2

    old_handler: Any = None
    if hasattr(signal, "SIGALRM"):
        old_handler = signal.signal(signal.SIGALRM, lambda _s, _f: _sigalrm_handler(total_timeout))
        _alarm_fn = vars(signal)["alarm"]
        _alarm_fn(int(total_timeout))

    try:
        result = _run_ai_analysis(analyzer, db_path, table, verify, max_retries, no_cache)
    finally:
        if hasattr(signal, "SIGALRM"):
            _alarm_fn = vars(signal)["alarm"]
            _alarm_fn(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)

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
