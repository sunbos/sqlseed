"""sqlseed-ai CLI subcommand module.

Defines the `ai-suggest` command, which invokes the sqlseed-ai plugin to
analyze table schemas and generate data configuration suggestions.
Supports streaming output display and a self-correction workflow.

This module lives inside the sqlseed-ai package and is discovered by
sqlseed-cli via the ``sqlseed.cli_commands`` entry-point group. The
``register(cli_group)`` callable at the bottom of this file is the entry
point target.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import yaml
from rich.console import Console
from rich.live import Live
from rich.text import Text
from sqlseed_ai import AIBackend, AIConfig, AiConfigRefiner, SchemaAnalyzer
from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer

# sanitize_table_config lives in the sqlseed-cli package; this is the only
# cross-plugin import permitted per ARCHITECTURE.md Section 4 (sqlseed-ai
# may import sqlseed-cli for CLI entry-point integration). Installing
# sqlseed-ai auto-pulls sqlseed-cli as a dependency.
from sqlseed_cli._utils import sanitize_table_config

from sqlseed._utils.logger import get_logger
from sqlseed.core.orchestrator import DataOrchestrator

if TYPE_CHECKING:
    # Type-only import: StagedSchemaAnalyzer is imported lazily at runtime
    # (inside the ai_analyze branch) to avoid loading the staged pipeline
    # module unless --staged-pipeline is set. The TYPE_CHECKING alias
    # lets us annotate the union type for mypy without a runtime cost.
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

logger = get_logger(__name__)

# This module is always loaded from inside the sqlseed-ai package, so the
# AI plugin is always available. The flag is kept for backward-compatible
# internal references and tests that monkeypatch it.
HAS_AI_PLUGIN = True


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
            parts.append(("\u23f3", "bold yellow"))
            parts.append((f" Connecting to {self._model}...", "yellow"))
        elif self._phase == "streaming":
            parts.append(("\u26a1", "bold cyan"))
            parts.append((f" Generating ({self._token_count} tokens)", "cyan"))
            if self._preview:
                parts.append((f"  {self._preview[-60:]}", "dim"))
        elif self._phase == "parsing":
            parts.append(("\U0001f4cb", "bold blue"))
            parts.append((f" Parsing response ({self._token_count} tokens)...", "blue"))
        elif self._phase == "validating":
            parts.append(("\u2705", "bold green"))
            parts.append((" Validating configuration...", "green"))
        elif self._phase == "refining":
            parts.append(("\U0001f504", "bold yellow"))
            retry_info = f" (attempt {self._attempt + 1}/{self._max_retries})" if self._max_retries > 0 else ""
            parts.append((f" Self-correction{retry_info}...", "yellow"))
        elif self._phase == "done":
            parts.append(("\u2705", "bold green"))
            parts.append((f" Done ({self._token_count} tokens)", "green"))

        text = Text("")
        for content, style in parts:
            text.append(content, style=style)
        return text

    def start(self) -> None:
        """Start the live rich display for streaming LLM output."""
        self._live = Live(self._render(), console=Console(), transient=False, refresh_per_second=8)
        self._live.start()

    def stop(self) -> None:
        """Stop the live display and release the terminal."""
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, phase: str, info: dict[str, Any]) -> None:
        """Update the streaming progress display with a new phase and token info."""
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


def _emit_ai_suggestion_failure(
    e: Exception,
    *,
    display: _StreamingProgressDisplay | None = None,
) -> None:
    """Emit the standard ``AI suggestion failed: {e}`` error to stderr.

    Centralizes the ``(display.stop() if display) + click.echo("AI suggestion
    failed: {e}", err=True)`` pattern repeated across the AI handler
    functions (CodeFlow duplicate-code). The caller remains responsible for
    ``return None`` or ``raise SystemExit(1)`` as appropriate to its control
    flow — this helper only standardizes the side-effects (stop display +
    emit message).

    Args:
        e: The caught exception whose ``str()`` representation is echoed.
        display: Optional streaming display to stop before emitting the error
            so the Rich Live region is closed before the stderr write.
    """
    if display:
        display.stop()
    click.echo(f"AI suggestion failed: {e}", err=True)


def _run_ai_analysis(
    analyzer: Any,
    db_path: str,
    table: str,
    verify: bool,
    max_retries: int,
    no_cache: bool,
) -> Any:
    config = analyzer.config
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
    """Handle AI direct suggestion with prompt-level fallback."""
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
                    timeout_s = int(analyzer.config.resolve_timeout()) if analyzer.config else 300
                    click.echo(f"Analyzing schema & generating AI suggestions ({mode} mode, timeout: {timeout_s}s)...")
                    result = analyzer.call_llm(messages)
                if result:
                    return result
                click.echo("AI returned empty result, retrying with shorter prompt...", err=True)
                continue
            except (ValueError, RuntimeError, OSError) as e:
                err_msg = str(e).lower()
                if "context" in err_msg and "exceed" in err_msg and not ultra:
                    if display:
                        display.stop()
                    click.echo("Context size exceeded, retrying with shorter prompt...", err=True)
                    continue
                _emit_ai_suggestion_failure(e, display=display)
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
    refiner = AiConfigRefiner(analyzer, db_path)
    try:
        timeout_s = int(analyzer.config.resolve_timeout()) if analyzer.config else 300
        click.echo(f"Analyzing schema & generating AI suggestions with self-correction (timeout: {timeout_s}s)...")
        return refiner.generate_and_refine(
            table_name=table,
            max_retries=max_retries,
            no_cache=no_cache,
            use_compact=use_compact,
        )
    except (ValueError, RuntimeError, OSError) as e:
        _emit_ai_suggestion_failure(e)
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
        _emit_ai_suggestion_failure(e, display=display)
        return None


def _write_ai_output(output: str, db_path: str, result: Any) -> None:
    sanitize_table_config(result)
    output_data = {
        "db_path": db_path,
        "provider": result.pop("provider", "mimesis"),
        "locale": result.pop("locale", "en_US"),
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


@click.command("ai-suggest")
@click.argument("db_path")
@click.option("--table", "-t", required=False, help="Target table name (required unless --auto-heal)")
@click.option("--output", "-o", required=False, help="Output YAML file path (required unless --auto-heal)")
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
@click.option(
    "--auto-heal",
    is_flag=True,
    default=False,
    help=(
        "Enable Contract-Driven Self-Healing (Layer 4 LLM healer + progressive "
        "degrade). Processes ALL tables; ignores --table/--output."
    ),
)
def ai_suggest(
    db_path: str,
    table: str | None,
    output: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    max_retries: int,
    verify: bool,
    no_cache: bool,
    timeout: float,
    auto_heal: bool,
) -> None:
    """Analyze table schema and suggest generation rules via AI."""
    if auto_heal:
        _run_auto_heal(db_path, model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        return

    if not table or not output:
        click.echo(
            "Error: --table and --output are required (unless --auto-heal is set).",
            err=True,
        )
        raise SystemExit(2)

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
    ai_config.model = resolved_model  # Persist so _resolve_max_tokens_for_model
    # detects E2B/E4B and returns 4096 (not 2048 default).
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})")

    analyzer = SchemaAnalyzer(config=ai_config)

    # Timeouts are handled uniformly by the LLM client layer (httpx); no signal-based hack needed at the CLI layer
    try:
        result = _run_ai_analysis(analyzer, db_path, table, verify, max_retries, no_cache)
    except (ValueError, RuntimeError, OSError) as exc:
        err_msg = str(exc).lower()
        if "timeout" in err_msg or "timed out" in err_msg:
            click.echo(
                "\nError: AI suggestion timed out. "
                "Try a different model with --model, or increase timeout with --timeout.",
                err=True,
            )
        else:
            _emit_ai_suggestion_failure(exc)
        raise SystemExit(1) from exc

    if result:
        _write_ai_output(output, db_path, result)
    else:
        _report_ai_failure()


def _run_auto_heal(
    db_path: str,
    *,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    timeout: float,
) -> None:
    """Dispatch to :class:`AutoHealOrchestrator` for the ``--auto-heal`` flag.

    Builds the validator + healer from the resolved :class:`AIConfig` and
    emits the resulting YAML to stdout.
    """
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.healer.llm_healer import LLMHealer
    from sqlseed_ai.validator.main import FastValidator

    ai_config = AIConfig.from_env().apply_overrides(
        api_key=api_key, base_url=base_url, model=model
    )
    ai_config.timeout = timeout

    resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
    validator = FastValidator(resolver, db_path=db_path)
    client = _build_llm_client(ai_config)
    healer = LLMHealer(client=client, model=ai_config.resolve_model())

    orch = AutoHealOrchestrator(
        db_path=db_path, healer=healer, validator=validator,
        total_budget_seconds=300.0,
    )
    try:
        yaml_str = orch.run()
    except (ValueError, RuntimeError, OSError) as exc:
        click.echo(f"Error: auto-heal failed: {exc}", err=True)
        raise SystemExit(1) from exc
    click.echo(yaml_str)


def _build_llm_client(ai_config: AIConfig) -> Any:
    """Build an LLM client from the given :class:`AIConfig`.

    Reuses the existing OpenAI-compatible client construction from
    :mod:`sqlseed_ai.analyzer._client`. Returns an object satisfying the
    :class:`~sqlseed_ai.healer.llm_healer.LLMClient` protocol.
    """
    from openai import OpenAI

    resolved_key = ai_config.resolve_api_key()
    if not resolved_key:
        click.echo(
            "Error: AI API key not configured for --auto-heal. "
            "Set SQLSEED_AI_API_KEY or OPENAI_API_KEY.",
            err=True,
        )
        raise SystemExit(1)
    base = ai_config.resolve_base_url() or "https://api.openai.com/v1"
    return OpenAI(api_key=resolved_key, base_url=base, timeout=ai_config.timeout or None)


def _build_ai_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 0.0,
    staged_pipeline: bool = False,
    log_llm: bool = False,
) -> AIConfig:
    """Build an :class:`AIConfig` from env defaults plus CLI overrides.

    Centralizes the ``from_env`` + ``apply_overrides`` + ``timeout`` +
    ``use_staged_pipeline`` assignment previously inlined in ``ai_analyze``.
    Extracted as a helper so the ``--staged-pipeline`` flag can be unit-tested
    in isolation without invoking the Click command or the LLM.
    """
    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)
    ai_config.timeout = timeout
    ai_config.use_staged_pipeline = staged_pipeline
    ai_config.log_llm_interactions = log_llm
    return ai_config


@click.command("ai-analyze")
@click.option("--db", "db_path", required=True, help="SQLite database path")
@click.option("--url", "db_url", default=None, help="Database URL (alternative to --db)")
@click.option("--tables", default=None, help="Comma-separated table names (default: all tables)")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output YAML file path")
@click.option(
    "--no-dependencies",
    is_flag=True,
    default=False,
    help="Skip FK dependency resolution (analyze only specified tables)",
)
@click.option("--max-depth", default=5, type=int, help="Max FK recursion depth (default: 5)")
@click.option("--model", "-m", default=None, help="AI model name (default: auto-select based on backend)")
@click.option("--api-key", envvar="SQLSEED_AI_API_KEY", default=None, help="AI API key (env: SQLSEED_AI_API_KEY)")
@click.option(
    "--base-url",
    envvar="SQLSEED_AI_BASE_URL",
    default=None,
    help="AI API base URL (env: SQLSEED_AI_BASE_URL)",
)
@click.option("--timeout", default=0, type=float, help="API call timeout in seconds (0=auto, default: auto)")
@click.option(
    "--staged-pipeline",
    is_flag=True,
    default=False,
    help="Use the new 3-stage LtM pipeline (StagedSchemaAnalyzer) instead of "
    "the legacy SchemaSemanticAnalyzer. Recommended for 2B local models.",
)
@click.option(
    "--log-llm",
    is_flag=True,
    default=False,
    help="Log full LLM interactions (prompt + response) to JSON files under "
    "<cache_root>/ai_logs/. Useful for debugging LLM hallucinations and Rule failures.",
)
@click.option(
    "--max-retries",
    default=2,
    type=int,
    help="Max retries for failed table analysis (default: 2). On failure, the "
    "table is retried with a fresh LLM call up to this many times.",
)
@click.option(
    "--merge",
    is_flag=True,
    default=False,
    help="Merge newly generated tables into existing YAML (instead of overwriting). "
    "Only tables specified by --tables are replaced; others are kept. "
    "Useful for re-generating specific tables without re-analyzing the entire database.",
)
def ai_analyze(
    db_path: str,
    db_url: str | None,
    tables: str | None,
    output: str,
    no_dependencies: bool,
    max_depth: int,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    staged_pipeline: bool = False,
    log_llm: bool = False,
    max_retries: int = 2,
    merge: bool = False,
) -> None:
    """Analyze database schema via LLM and generate business YAML config.

    \b
    Modes:
      - Full database: sqlseed ai-analyze --db app.db -o config.yaml
      - Partial tables: sqlseed ai-analyze --db app.db --tables orders,items -o config.yaml
      - No dependencies: sqlseed ai-analyze --db app.db --tables orders --no-dependencies -o config.yaml
      - Merge mode: sqlseed ai-analyze --db app.db --tables orders -o config.yaml --merge
        (re-generates only 'orders', keeps other tables from existing YAML)

    \b
    The generated YAML contains business logic (column generators, params,
    constraints). Review and edit before using with `sqlseed fill`.
    """
    import yaml

    from sqlseed import connect

    # Initialize AIConfig from env + CLI overrides (mirrors ai-suggest pattern).
    # _build_ai_config centralizes from_env + apply_overrides + timeout +
    # use_staged_pipeline so the --staged-pipeline flag can be unit-tested
    # in isolation (see test_ai_analyze_command_staged_pipeline_flag_sets_config).
    ai_config = _build_ai_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        staged_pipeline=staged_pipeline,
        log_llm=log_llm,
    )

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
    ai_config.model = resolved_model  # Persist resolved model so downstream
    # code (_resolve_max_tokens_for_model) can detect E2B/E4B and return
    # the correct max_tokens (4096 for reasoning models vs 2048 default).
    # Without this, max_tokens=2048 is too small for Gemma 4 E2B's reasoning
    # + content generation, causing empty responses.
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})")
    if log_llm:
        from sqlseed._utils.paths import get_cache_dir

        log_dir = get_cache_dir("ai_logs")
        click.echo(f"LLM interaction logging enabled: {log_dir}")

    table_list = None
    if tables:
        table_list = [t.strip() for t in tables.split(",") if t.strip()]

    # Merge mode: load existing YAML and keep non-regenerated tables
    existing_tables: list[dict[str, Any]] = []
    if merge:
        output_path_check = Path(output)
        if output_path_check.exists():
            try:
                with output_path_check.open("r", encoding="utf-8") as f:
                    existing_config = yaml.safe_load(f) or {}
                existing_tables = existing_config.get("tables", [])
                if existing_tables:
                    click.echo(
                        f"Merge mode: keeping {len(existing_tables)} existing tables, "
                        f"re-generating: {table_list or 'all'}"
                    )
            except Exception as e:
                click.echo(f"Warning: could not load existing YAML for merge: {e}", err=True)

    orch = connect(url=db_url) if db_url else connect(db_path=db_path)

    try:
        with orch:
            # Use PUBLIC database_adapter property (not private _db)
            db = orch.database_adapter

            if ai_config.use_staged_pipeline:
                # New 3-stage LtM pipeline (StagedSchemaAnalyzer). Same
                # analyze() signature as SchemaSemanticAnalyzer, so the
                # downstream config_dict handling is unchanged.
                from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

                analyzer: StagedSchemaAnalyzer | SchemaSemanticAnalyzer = StagedSchemaAnalyzer(config=ai_config)
            else:
                analyzer = SchemaSemanticAnalyzer(config=ai_config)

            # Progress callback for real-time CLI display (user preference:
            # show progress during LLM calls, not just final result)
            def _progress(table: str, idx: int, total: int) -> None:
                click.echo(f"[{idx}/{total}] Analyzing table: {table} ...")

            # Retry loop: if analyze() fails, retry up to max_retries times.
            # Each retry gets a fresh LLM call (the StagedSchemaAnalyzer
            # internal cache is per-instance, so a new analyze() call
            # re-invokes the LLM).
            last_error: Exception | None = None
            config_dict: dict[str, Any] | None = None
            for attempt in range(1, max_retries + 2):  # +1 for initial attempt
                try:
                    config_dict = analyzer.analyze(
                        db,
                        tables=table_list,
                        include_dependencies=not no_dependencies,
                        max_depth=max_depth,
                        progress_callback=_progress,
                    )
                    break  # Success
                except Exception as e:
                    last_error = e
                    if attempt <= max_retries:
                        click.echo(
                            f"Attempt {attempt}/{max_retries + 1} failed: {e}. Retrying...",
                            err=True,
                        )
                    else:
                        click.echo(f"All {max_retries + 1} attempts failed.", err=True)

            if config_dict is None:
                raise last_error  # type: ignore[misc]

            # Merge mode: replace regenerated tables in existing config
            if merge and existing_tables:
                regenerated_names = {t.get("name") for t in config_dict.get("tables", [])}
                kept_tables = [t for t in existing_tables if t.get("name") not in regenerated_names]
                config_dict["tables"] = config_dict.get("tables", []) + kept_tables

            # Inject db_path/url + provider + locale so the generated YAML is
            # directly fillable by `sqlseed fill --config <yaml>` and matches
            # the field order of `ai-suggest` (db_path → provider → locale →
            # tables). Rebuilding the dict (instead of mutating in place)
            # guarantees a stable, human-readable top-level key order,
            # because PyYAML respects insertion order when sort_keys=False.
            # Reference: config/models.py GeneratorConfig defaults
            #   provider: ProviderType.MIMESIS
            #   locale:   "en_US"
            tables = config_dict.get("tables", [])
            rebuilt: dict[str, Any] = {}
            if db_url:
                rebuilt["url"] = db_url
            else:
                rebuilt["db_path"] = db_path
            rebuilt["provider"] = config_dict.pop("provider", "mimesis")
            rebuilt["locale"] = config_dict.pop("locale", "en_US")
            rebuilt["tables"] = tables
            # Preserve any remaining unexpected keys after the standard ones
            # (forward-compat for analyzer-added metadata without reordering).
            for k, v in config_dict.items():
                if k not in rebuilt:
                    rebuilt[k] = v
            config_dict = rebuilt

            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(config_dict, f, allow_unicode=True, sort_keys=False)

            click.echo(f"Generated YAML config: {output_path}")
            click.echo(f"Tables: {len(config_dict.get('tables', []))}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(1) from e


def register(cli_group: click.Group) -> None:
    """Entry-point target for the ``sqlseed.cli_commands`` group.

    Called by ``sqlseed_cli.__init__`` to attach the ``ai-suggest`` and
    ``ai-analyze`` subcommands to the ``sqlseed`` CLI group. Using
    ``register`` (rather than ``register_commands``) keeps this module's
    public name aligned with the entry-point callable signature documented
    in ``sqlseed_cli.__init__._register_plugin_commands``.
    """
    cli_group.add_command(ai_suggest)
    cli_group.add_command(ai_analyze)


# Backward-compat alias: existing tests import ``register_commands`` from
# the old ``sqlseed.cli.ai_commands`` location. Alias keeps such imports
# working after the move to ``sqlseed_ai.cli.ai_commands``.
register_commands = register
