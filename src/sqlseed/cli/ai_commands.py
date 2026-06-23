"""sqlseed CLI AI subcommand module.

Defines the `ai-suggest` command, which invokes the sqlseed-ai plugin to
analyze table schemas and generate data configuration suggestions.
Supports streaming output display and a self-correction workflow.
"""

from __future__ import annotations

from typing import Any

import click
import yaml
from rich.console import Console
from rich.live import Live
from rich.text import Text

from sqlseed._utils.logger import get_logger
from sqlseed.cli.main import cli
from sqlseed.core.orchestrator import DataOrchestrator

# NOTE: Circular dependency explanation — this module is imported at the end of
# main.py, at which point `cli` is already defined, so no circular ImportError
# is triggered. See the design-decision comment at the end of main.py.

try:
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig
    from sqlseed_ai.refiner import AiConfigRefiner as _AiConfigRefiner

    HAS_AI_PLUGIN = True
    AiConfigRefiner: Any = _AiConfigRefiner
except ImportError:
    HAS_AI_PLUGIN = False
    AiConfigRefiner = None

logger = get_logger(__name__)


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
    if not HAS_AI_PLUGIN:
        raise ImportError("sqlseed-ai plugin not installed. Install with: pip install sqlseed-ai")

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
    if not HAS_AI_PLUGIN:
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
    # Import inside function to avoid circular dependency.
    from sqlseed.cli.main import _sanitize_table_config  # noqa: PLC0415

    _sanitize_table_config(result)
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
            click.echo(f"AI suggestion failed: {exc}", err=True)
        raise SystemExit(1) from exc

    if result:
        _write_ai_output(output, db_path, result)
    else:
        _report_ai_failure()
