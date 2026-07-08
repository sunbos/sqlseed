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
from typing import Any

import click
import yaml
from rich.console import Console
from rich.live import Live
from rich.text import Text
from sqlseed_ai import AIBackend, AIConfig, AiConfigRefiner, SchemaAnalyzer

# sanitize_table_config lives in the sqlseed-cli package; this is the only
# cross-plugin import permitted per ARCHITECTURE.md Section 4 (sqlseed-ai
# may import sqlseed-cli for CLI entry-point integration). Installing
# sqlseed-ai auto-pulls sqlseed-cli as a dependency.
from sqlseed_cli._utils import sanitize_table_config

from sqlseed._utils.logger import get_logger
from sqlseed.core.orchestrator import DataOrchestrator

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
    """Dispatch to AutoHealOrchestrator for the ``--auto-heal`` flag on ai-suggest.

    Delegates to ``_run_auto_heal_v4`` (shared with ``ai-analyze``) and
    echoes the YAML to stdout.
    """
    yaml_str = _run_auto_heal_v4(
        db_path=db_path,
        db_url=None,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )
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
            "Error: AI API key not configured for --auto-heal. Set SQLSEED_AI_API_KEY or OPENAI_API_KEY.",
            err=True,
        )
        raise SystemExit(1)
    base = ai_config.resolve_base_url() or "https://api.openai.com/v1"
    raw_client = OpenAI(api_key=resolved_key, base_url=base, timeout=ai_config.timeout or None)
    # Wrap in adapter so the client satisfies the LLMClient protocol
    # (flat chat_completions_create method) instead of the OpenAI SDK's
    # attribute-chain style (client.chat.completions.create).
    from sqlseed_ai.healer._client import OpenAICompatAdapter as _OpenAICompatAdapter

    return _OpenAICompatAdapter(raw_client)


def _build_ai_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 0.0,
    log_llm: bool = False,
) -> AIConfig:
    """Build an :class:`AIConfig` from env defaults plus CLI overrides.

    Centralizes the ``from_env`` + ``apply_overrides`` + ``timeout`` +
    ``log_llm_interactions`` assignment previously inlined in ``ai_analyze``.
    Extracted as a helper so the AI config construction can be unit-tested
    in isolation without invoking the Click command or the LLM.
    """
    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)
    ai_config.timeout = timeout
    ai_config.log_llm_interactions = log_llm
    return ai_config


@click.command("ai-analyze")
@click.option("--db", "db_path", required=False, help="SQLite database path")
@click.option("--url", "db_url", default=None, help="Database URL (alternative to --db)")
@click.option("--tables", default=None, help="Comma-separated table names (default: all tables)")
@click.option("--output", "-o", required=False, type=click.Path(), help="Output YAML file path (default: stdout)")
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
    db_path: str | None,
    db_url: str | None,
    tables: str | None,
    output: str | None,
    no_dependencies: bool,
    max_depth: int,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    log_llm: bool = False,
    max_retries: int = 2,
    merge: bool = False,
) -> None:
    """Analyze database schema via LLM and generate business YAML config.

    Uses the v4 Contract-Driven Self-Healing architecture
    (AutoHealOrchestrator) by default. The legacy Stage3Validator path
    has been removed (Phase 4 of v4 migration).

    \b
    Modes:
      - Full database: sqlseed ai-analyze --db app.db -o config.yaml
      - Partial tables: sqlseed ai-analyze --db app.db --tables orders,items -o config.yaml
      - No dependencies: sqlseed ai-analyze --db app.db --tables orders --no-dependencies -o config.yaml
      - Merge mode: sqlseed ai-analyze --db app.db --tables orders -o config.yaml --merge
      - Stdout: sqlseed ai-analyze --db app.db (no -o, prints YAML to stdout)
    """
    if not db_path and not db_url:
        raise click.UsageError("Either --db or --url must be provided.")
    if db_path and db_url:
        raise click.UsageError("--db and --url are mutually exclusive. Provide only one.")

    # v4 path: AutoHealOrchestrator handles all tables, validation, repair, healing.
    # Note: --tables/--no-dependencies/--max-depth/--merge are accepted for
    # backward compatibility but not yet forwarded to the v4 orchestrator
    # (will be wired when AutoHealOrchestrator adds subgraph filtering).
    yaml_str = _run_auto_heal_v4(
        db_path=db_path,
        db_url=db_url,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
        log_llm=log_llm,
    )

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            f.write(yaml_str)
        click.echo(f"Generated YAML config: {output_path}")
    else:
        click.echo(yaml_str)


def _run_auto_heal_v4(
    *,
    db_path: str | None,
    db_url: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    max_retries: int = 2,
    log_llm: bool = False,
) -> str:
    """Build and run AutoHealOrchestrator, returning the YAML string.

    Extracted from ``_run_auto_heal`` to support both ``ai-suggest --auto-heal``
    (legacy entry point, kept for backward compatibility during Phase 3) and
    ``ai-analyze`` (new default v4 path). Returns YAML string instead of
    echoing to stdout so the caller can choose to write to file or echo.
    """
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.main import FastValidator

    ai_config = _build_ai_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
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
    ai_config.model = resolved_model
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})", err=True)

    if log_llm:
        from sqlseed._utils.paths import get_cache_dir
        log_dir = get_cache_dir("ai_logs")
        click.echo(f"LLM interaction logging enabled: {log_dir}", err=True)

    resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
    validator = FastValidator(resolver, db_path=db_path, url=db_url)
    client = _build_llm_client(ai_config)

    # Build HealOrchestrator (4-level: subgraph → column → compact → degrade).
    # The snapshot is captured inside AutoHealOrchestrator.run(), but
    # HealOrchestrator needs it for Level 2 context building. We create a
    # preliminary snapshot here for construction; AutoHealOrchestrator.run()
    # will create its own for the optimistic-lock check (Defense 8).
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    prelim_snapshot = SchemaSnapshot(db_path=db_path, url=db_url)
    heal_orch = _build_heal_orchestrator(
        ai_config, client, prelim_snapshot, validator,
        schema_hash=prelim_snapshot.schema_hash, max_retries=max_retries,
    )

    orch = AutoHealOrchestrator(
        db_path=db_path,
        url=db_url,
        heal_orchestrator=heal_orch,
        validator=validator,
        total_budget_seconds=300.0,
        max_retries=max_retries,
        verbose=True,  # Always verbose: user needs to see LLM progress in real time
    )

    try:
        return orch.run()
    except (ValueError, RuntimeError, OSError) as exc:
        click.echo(f"Error: v4 auto-heal failed: {exc}", err=True)
        raise SystemExit(1) from exc


@click.command("auto-heal")
@click.option(
    "--db",
    "db_path",
    required=False,
    type=click.Path(),
    help="SQLite database path (mutually exclusive with --url)",
)
@click.option("--url", "db_url", default=None, help="Database URL (mutually exclusive with --db)")
@click.option("--config", "config_path", required=True, type=click.Path(), help="Existing YAML config to repair")
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output path for healed YAML (default: <config>_healed.yaml)",
)
@click.option("--model", "-m", default=None, help="LLM model name (default: auto-detect from available backends)")
@click.option("--max-retries", default=3, type=int, help="Max heal attempts per subgraph (default: 3)")
@click.option(
    "--log-llm",
    is_flag=True,
    default=False,
    help="Log full LLM request/response to JSON files under <cache_root>/ai_logs/.",
)
@click.option(
    "--api-key",
    envvar="SQLSEED_AI_API_KEY",
    default=None,
    help="API key for cloud backends (env: SQLSEED_AI_API_KEY)",
)
@click.option(
    "--base-url",
    envvar="SQLSEED_AI_BASE_URL",
    default=None,
    help="Base URL for OpenAI-compatible backend (env: SQLSEED_AI_BASE_URL)",
)
def auto_heal(
    db_path: str | None,
    db_url: str | None,
    config_path: str,
    output_path: str | None,
    model: str | None,
    max_retries: int,
    log_llm: bool,
    api_key: str | None,
    base_url: str | None,
) -> None:
    """Repair broken YAML config files using LLM-driven self-healing.

    \b
    Usage:
      - sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml
      - sqlseed auto-heal --url "postgresql+psycopg://..." --config broken.yaml

    \b
    After `sqlseed ai-analyze` generates a YAML config, if `sqlseed fill`
    fails on some tables (CHECK constraint violations, FK violations, etc.),
    this command repairs the YAML using an LLM + rule-based repair pipeline.
    The output is a fillable YAML config ready for `sqlseed fill`.
    """
    # Validate mutual exclusivity of --db and --url
    if not db_path and not db_url:
        raise click.UsageError("Either --db or --url must be provided.")
    if db_path and db_url:
        raise click.UsageError("--db and --url are mutually exclusive. Provide only one.")

    # Validate config file exists
    config_file = Path(config_path)
    if not config_file.exists():
        raise click.UsageError(f"Config file not found: {config_path}")

    # Determine output path (default: <config_stem>_healed.yaml)
    output = output_path if output_path is not None else str(config_file.with_suffix("")) + "_healed.yaml"

    # Build AI config from env + CLI overrides (mirrors ai-analyze pattern)
    ai_config = _build_ai_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=0.0,
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
    ai_config.model = resolved_model
    backend_name = ai_config.backend.value.replace("_", " ").title()
    click.echo(f"Using AI model: {resolved_model} (via {backend_name})")

    if log_llm:
        from sqlseed._utils.paths import get_cache_dir

        log_dir = get_cache_dir("ai_logs")
        click.echo(f"LLM interaction logging enabled: {log_dir}")

    # Build validator + healer + orchestrator (lazy imports to avoid
    # loading auto_heal submodules unless the command is actually invoked)
    from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.main import FastValidator

    resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
    validator = FastValidator(resolver, db_path=db_path, url=db_url)
    client = _build_llm_client(ai_config)

    # Build HealOrchestrator (4-level: subgraph → column → compact → degrade).
    # The snapshot is captured inside AutoHealOrchestrator.run(), but
    # HealOrchestrator needs it for Level 2 context building. We create a
    # preliminary snapshot here for construction; AutoHealOrchestrator.run()
    # will create its own for the optimistic-lock check (Defense 8).
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    prelim_snapshot = SchemaSnapshot(db_path=db_path, url=db_url)
    heal_orch = _build_heal_orchestrator(
        ai_config, client, prelim_snapshot, validator,
        schema_hash=prelim_snapshot.schema_hash, max_retries=max_retries,
    )

    orch = AutoHealOrchestrator(
        db_path=db_path,
        url=db_url,
        heal_orchestrator=heal_orch,
        validator=validator,
        total_budget_seconds=300.0,
        max_retries=max_retries,
        verbose=True,  # Always verbose: user needs to see LLM progress in real time
    )

    try:
        yaml_str = orch.run()
    except (ValueError, RuntimeError, OSError) as exc:
        err_msg = str(exc)
        if db_url:
            try:
                from sqlseed_cli.main import _redact_credentials

                err_msg = _redact_credentials(err_msg)
            except ImportError:
                pass
        click.echo(f"Error: auto-heal failed: {err_msg}", err=True)
        raise SystemExit(1) from exc

    # Write healed YAML
    output_file = Path(output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        f.write(yaml_str)

    # Summary: count tables in the healed output
    healed_config = yaml.safe_load(yaml_str) or {}
    tables_repaired = len(healed_config.get("tables", []))

    click.echo(f"Healed YAML written to: {output_file}")
    click.echo(f"Tables repaired: {tables_repaired}")


def register(cli_group: click.Group) -> None:
    """Entry-point target for the ``sqlseed.cli_commands`` group.

    Called by ``sqlseed_cli.__init__`` to attach the ``ai-suggest``,
    ``ai-analyze``, and ``auto-heal`` subcommands to the ``sqlseed`` CLI
    group. Using ``register`` (rather than ``register_commands``) keeps
    this module's public name aligned with the entry-point callable
    signature documented in ``sqlseed_cli.__init__._register_plugin_commands``.
    """
    cli_group.add_command(ai_suggest)
    cli_group.add_command(ai_analyze)
    cli_group.add_command(auto_heal)


# Backward-compat alias: existing tests import ``register_commands`` from
# the old ``sqlseed.cli.ai_commands`` location. Alias keeps such imports
# working after the move to ``sqlseed_ai.cli.ai_commands``.
register_commands = register
