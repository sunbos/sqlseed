"""MCP server exposing sqlseed-ai LLM-driven capabilities as tools.

Per ARCHITECTURE.md Section 3.3 and 7.4, this is the AI MCP server. It
provides LLM-driven tools that complement the rule-driven
``mcp-server-sqlseed`` package. Install with ``pip install sqlseed-ai[mcp]``.

Tools provided
--------------
- ``sqlseed_ai_generate_yaml``    LLM-driven YAML config (semantic inference)
- ``sqlseed_gemma4_analyze``      Gemma 4 schema analysis via native function calling
- ``sqlseed_gemma4_agent_fill``   End-to-end AI agent: analyze -> config -> fill
- ``sqlseed_list_gemma_models``   List Gemma 4 models with hardware compatibility

Boundary (ARCHITECTURE.md Section 7.4): the dividing line between
``mcp-server-sqlseed`` and ``sqlseed-ai[mcp]`` is "whether LLM runtime is
required", not "online/offline". This package requires an LLM runtime.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import yaml

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:  # pragma: no cover - import error path
    raise ImportError("mcp SDK not installed. Install with: pip install 'sqlseed-ai[mcp]'") from _exc

from sqlseed_ai import AIBackend, AIConfig, AiConfigRefiner, AISuggestionFailedError, GemmaModel, SchemaAnalyzer
from sqlseed_ai._hardware import MODEL_REQUIREMENTS, detect_hardware, evaluate_model_status

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import validate_db_target as _validate_db_target
from sqlseed._utils.paths import validate_table_name as _validate_table_name
from sqlseed.config.models import ColumnConfig
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)

mcp = FastMCP("sqlseed-ai")


def _build_ai_config(
    db_path: str,
    model: str | None,
    backend: str | None,
) -> AIConfig:
    """Build an AIConfig with Gemma 4 defaults, validating db_path and backend.

    Args:
        db_path: Database file path or URL.
        model: Optional model override.
        backend: Optional backend override.

    Returns:
        The validated AIConfig.

    Raises:
        ValueError: If db_path is invalid or backend is not a valid AIBackend value.
    """
    db_path = _validate_db_target(db_path)

    ai_config = AIConfig.from_env()
    if model:
        ai_config.model = model
    if backend:
        try:
            ai_config.backend = AIBackend(backend)
        except ValueError:
            raise ValueError(
                f"Invalid backend: {backend}. Use: google_ai_studio, lm_studio, ollama, openai_compat"
            ) from None
    ai_config.model = ai_config.resolve_model()

    logger.debug("Built AI config", model=ai_config.model, backend=ai_config.backend.value)
    return ai_config


@mcp.tool()
def sqlseed_ai_generate_yaml(
    db_path: str,
    table_name: str,
    max_retries: int = 3,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    backend: str | None = None,
) -> str:
    """Generate YAML config for a table using LLM-driven semantic analysis.

    Uses the sqlseed-ai SchemaAnalyzer (Gemma 4 native function calling)
    with a self-correction loop to infer column generators from schema
    semantics. For rule-driven offline generation, use the
    ``sqlseed_generate_yaml`` tool from ``mcp-server-sqlseed`` instead.

    Supported backends: google_ai_studio (default), lm_studio, ollama, openai_compat.
    Returns a YAML string for human review.
    """
    try:
        db_path = _validate_db_target(db_path)
        with DataOrchestrator(db_path) as orch:
            _validate_table_name(table_name, orch.get_table_names())

        ai_config = AIConfig.from_env().apply_overrides(
            api_key=api_key,
            base_url=base_url,
            model=model,
            backend=AIBackend(backend) if backend else None,
        )
        ai_config.model = ai_config.resolve_model()

        refiner = AiConfigRefiner.from_config(ai_config, db_path)

        result = refiner.generate_and_refine(
            table_name=table_name,
            max_retries=max_retries,
        )
    except AISuggestionFailedError as e:
        logger.warning("AI suggestion failed", table_name=table_name, error=str(e))
        return f"# AI suggestion failed: {e}"
    except (ValueError, RuntimeError, OSError) as e:
        logger.warning("YAML generation error", table_name=table_name, error=str(e))
        return f"# Error: {e}"

    if result:
        logger.info("AI YAML config generated", table_name=table_name)
        output = {"db_path": db_path, "provider": "faker", "locale": "en_US", "tables": [result]}
        return str(yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False))
    return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."


@mcp.tool()
def sqlseed_gemma4_analyze(
    db_path: str,
    table_name: str,
    model: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Analyze a database table schema using Gemma 4 with native function calling.

    This tool leverages Gemma 4's built-in tool use capability to analyze
    table structure and recommend data generation configurations. It demonstrates
    Gemma 4's Native Function Calling feature for the AI Agent track.

    Supported backends: google_ai_studio (default), lm_studio, ollama, openai_compat.
    Supported models: gemma-4-26b-a4b-it (default), gemma-4-31b-it, gemma-4-12b-it,
    gemma-4-e4b-it, gemma-4-e2b-it.
    """
    try:
        ai_config = _build_ai_config(db_path, model, backend)

        with DataOrchestrator(db_path) as orch:
            _validate_table_name(table_name, orch.get_table_names())
            schema_ctx = orch.get_schema_context(table_name)

        analyzer = SchemaAnalyzer(config=ai_config)
        result = analyzer.analyze_table_from_ctx(**schema_ctx)

        if not result:
            return {"error": "Gemma 4 analysis returned no result. Check API key and model availability."}

        logger.info("Gemma 4 analysis completed", table_name=table_name, model=ai_config.model)
        return {
            "model": ai_config.model,
            "backend": ai_config.backend.value,
            "table_name": table_name,
            "config": result,
        }
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Gemma 4 analysis failed", db_path=db_path, table_name=table_name, error=str(e))
        return {"error": str(e)}


@mcp.tool()
def sqlseed_gemma4_agent_fill(
    db_path: str,
    table_name: str,
    count: int = 1000,
    model: str | None = None,
    backend: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """End-to-end AI Agent: Gemma 4 analyzes schema -> generates config -> fills data.

    This is a complete Agent workflow that demonstrates Gemma 4's Native Function
    Calling capability for the AI Agent track:
    1. Inspect schema (Tool Calling: analyze_schema)
    2. Generate data configuration (self-correction loop)
    3. Execute data fill

    The agent uses Gemma 4's tool use to understand schema semantics and
    produce appropriate data generation rules automatically.
    """
    try:
        ai_config = _build_ai_config(db_path, model, backend)

        # Step 1: AI analysis with self-correction
        refiner = AiConfigRefiner.from_config(ai_config, db_path)

        try:
            ai_result = refiner.generate_and_refine(
                table_name=table_name,
                max_retries=max_retries,
            )
        except AISuggestionFailedError as e:
            return {"error": f"AI suggestion failed: {e}", "model": ai_config.model}
        except (ValueError, RuntimeError, OSError) as e:
            return {"error": f"Error: {e}", "model": ai_config.model}

        if not ai_result:
            return {"error": "No AI suggestions available", "model": ai_config.model}

        # Step 2: Execute fill with AI-generated config
        with DataOrchestrator(db_path) as orch:
            _validate_table_name(table_name, orch.get_table_names())

            column_configs = [ColumnConfig(**c) for c in ai_result.get("columns", [])]
            result = orch.fill_table(
                table_name=table_name,
                count=count,
                column_configs=column_configs,
            )

            logger.info(
                "Agent fill completed",
                table_name=result.table_name,
                count=result.count,
                model=ai_config.model,
            )
            return {
                "model": ai_config.model,
                "backend": ai_config.backend.value,
                "table_name": result.table_name,
                "count": result.count,
                "elapsed": result.elapsed,
                "errors": result.errors,
                "ai_config": ai_result,
            }
    except (ValueError, RuntimeError, OSError) as e:
        logger.error("Agent fill failed", db_path=db_path, table_name=table_name, error=str(e))
        return {"error": str(e)}


_BACKEND_DESCRIPTIONS: dict[str, str] = {
    "google_ai_studio": "Google AI Studio API (free tier available, recommended)",
    "lm_studio": "LM Studio local deployment (http://127.0.0.1:1234, GUI-based)",
    "ollama": "Ollama local deployment (offline, CLI-based)",
    "openai_compat": "Any OpenAI-compatible API endpoint",
}

_LOCAL_BACKEND_URLS: dict[str, str] = {
    "lm_studio": "http://127.0.0.1:1234/v1/models",
    "ollama": "http://localhost:11434/v1/models",
}

_STATUS_ICONS: dict[str, str] = {
    "recommended": "recommended",
    "capable": "capable (meets minimum specs)",
    "capable_slow": "capable but likely slow (VRAM < minimum, will use RAM offloading)",
    "cpu_only": "CPU-only inference (no GPU detected)",
    "insufficient": "insufficient hardware",
    "cloud_only": "cloud API only",
}


def _check_local_backend(backend_id: str, url: str) -> dict[str, Any]:
    """Check reachability and loaded models for a local LLM backend."""
    reachable = False
    loaded: list[str] = []
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            loaded = [m.get("id", "unknown") for m in data.get("data", []) if m.get("id")]
            reachable = True
    except (OSError, ValueError):
        pass

    if reachable and loaded:
        reason = f"{len(loaded)} model(s) loaded"
    elif reachable:
        reason = "Service running, no models loaded"
    else:
        reason = "Service not running"

    return {
        "id": backend_id,
        "description": _BACKEND_DESCRIPTIONS[backend_id],
        "available": reachable and bool(loaded),
        "reachable": reachable,
        "loaded_models": loaded,
        "reason": reason,
    }


def _build_backends(ai_config: AIConfig) -> list[dict[str, Any]]:
    """Build the list of backend availability info."""
    backends: list[dict[str, Any]] = []

    # Google AI Studio: check API key
    has_api_key = ai_config.has_real_api_key
    backends.append(
        {
            "id": "google_ai_studio",
            "description": _BACKEND_DESCRIPTIONS["google_ai_studio"],
            "available": has_api_key,
            "reason": "API key configured" if has_api_key else "No API key (set GOOGLE_API_KEY or SQLSEED_AI_API_KEY)",
        }
    )

    # LM Studio / Ollama: check service reachability + loaded models
    for backend_id, url in _LOCAL_BACKEND_URLS.items():
        backends.append(_check_local_backend(backend_id, url))

    # OpenAI-compatible: informational only
    backends.append(
        {
            "id": "openai_compat",
            "description": _BACKEND_DESCRIPTIONS["openai_compat"],
            "available": False,
            "reason": "Requires explicit base_url configuration",
        }
    )
    return backends


def _build_models(hw: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the list of Gemma models with hardware compatibility status."""
    models = []
    for member in GemmaModel:
        status = evaluate_model_status(member.value, hw)
        req = MODEL_REQUIREMENTS.get(member.value)
        models.append(
            {
                "id": member.value,
                "display_name": member.display_name,
                "status": status,
                "status_description": _STATUS_ICONS.get(status, status),
                "local_only": member.is_local_only,
                "requirements": {
                    "min_ram_gb": req.min_ram_gb if req else 0,
                    "min_vram_gb": req.min_vram_gb if req else 0,
                    "recommended_vram_gb": req.recommended_vram_gb if req else 0,
                },
            }
        )
    return models


def _pick_default_model(models: list[dict[str, Any]]) -> str:
    """Pick the largest capable model (iterate from largest to smallest)."""
    for m in reversed(models):
        if m["status"] in {"recommended", "capable"} and not m["local_only"]:
            return str(m["id"])
    return str(GemmaModel.GEMMA_4_26B_A4B.value)


def _pick_default_backend(backends: list[dict[str, Any]]) -> str:
    """Pick the first available backend, preferring local over cloud."""
    priority = ["lm_studio", "ollama", "google_ai_studio", "openai_compat"]
    for b_id in priority:
        for b in backends:
            if b["id"] == b_id and b.get("available"):
                return b_id
    return "google_ai_studio"


@mcp.tool()
def sqlseed_list_gemma_models() -> dict[str, Any]:
    """List Gemma 4 models with hardware compatibility and backend availability.

    Dynamically detects the current hardware environment (RAM, GPU/VRAM)
    and checks which LLM backends are reachable. Returns models annotated
    with compatibility status and backends annotated with availability.
    """
    # ── 1. Detect hardware ──
    hw = detect_hardware()

    # ── 2. Check backend availability ──
    ai_config = AIConfig.from_env()
    backends_result = _build_backends(ai_config)

    # ── 3. Build model list with compatibility status ──
    models = _build_models(hw)

    # ── 4. Determine best defaults ──
    default_model = _pick_default_model(models)
    default_backend = _pick_default_backend(backends_result)

    return {
        "models": models,
        "backends": backends_result,
        "default_model": default_model,
        "default_backend": default_backend,
        "hardware": {
            "platform": hw["platform"],
            "ram": hw["ram"],
            "gpus": hw["gpus"],
            "max_vram_gb": hw["max_vram_gb"],
        },
    }


def main() -> None:
    """Run the sqlseed-ai MCP server."""
    mcp.run()
