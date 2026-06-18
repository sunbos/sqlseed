from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

from mcp_server_sqlseed.config import MCPServerConfig
from sqlseed.config.models import ColumnConfig, GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator

try:
    from sqlseed_ai._hardware import MODEL_REQUIREMENTS, detect_hardware, evaluate_model_status
    from sqlseed_ai.analyzer import SchemaAnalyzer
    from sqlseed_ai.config import AIBackend, AIConfig, GemmaModel
    from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False

_server_config = MCPServerConfig()
mcp = FastMCP("sqlseed", host=_server_config.host, port=_server_config.port)

_MAX_YAML_CONFIG_SIZE = 256 * 1024


def _build_ai_config(
    db_path: str,
    model: str | None,
    backend: str | None,
) -> tuple[AIConfig | None, dict[str, Any] | None]:
    """Build an AIConfig with Gemma 4 defaults, validating db_path and backend.

    Returns (config, None) on success, or (None, error_dict) on failure.
    """
    if not _AI_AVAILABLE:
        return None, {"error": "sqlseed-ai plugin not installed. Install with: pip install sqlseed-ai"}

    db_path = _validate_db_path(db_path)

    ai_config = AIConfig.from_env()
    if model:
        ai_config.model = model
    if backend:
        try:
            ai_config.backend = AIBackend(backend)
        except ValueError:
            return None, {
                "error": f"Invalid backend: {backend}. Use: google_ai_studio, lm_studio, ollama, openai_compat"
            }
    ai_config.resolve_model()

    return ai_config, None


def _validate_db_path(db_path: str) -> str:
    resolved = Path(db_path).resolve()
    valid_exts = (".db", ".sqlite", ".sqlite3")
    if not str(resolved).endswith(valid_exts):
        raise ValueError(f"Invalid database path: {db_path}. Must be a .db, .sqlite, or .sqlite3 file.")
    if not resolved.exists():
        raise ValueError(f"Database file not found: {db_path}")
    return str(resolved)


def _validate_table_name(table_name: str, allowed_tables: list[str]) -> str:
    if table_name not in allowed_tables:
        raise ValueError(f"Table '{table_name}' does not exist in the database. Available: {allowed_tables}")
    return table_name


def _serialize_schema_context(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_name": ctx["table_name"],
        "columns": [
            {
                "name": c.name,
                "type": c.type,
                "nullable": c.nullable,
                "default": c.default,
                "is_primary_key": c.is_primary_key,
                "is_autoincrement": c.is_autoincrement,
            }
            for c in ctx["columns"]
        ],
        "foreign_keys": [
            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column} for fk in ctx["foreign_keys"]
        ],
        "indexes": ctx["indexes"],
        "sample_data": ctx["sample_data"],
        "all_table_names": ctx["all_table_names"],
    }


def _compute_schema_hash(schema_ctx: dict[str, Any]) -> str:
    hash_input = json.dumps(
        {
            "columns": [{"name": c.name, "type": c.type, "nullable": c.nullable} for c in schema_ctx["columns"]],
            "foreign_keys": [{"column": fk.column, "ref_table": fk.ref_table} for fk in schema_ctx["foreign_keys"]],
        },
        sort_keys=True,
    )
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


@mcp.resource("sqlseed://schema/{db_path}/{table_name}")
def get_schema_resource(db_path: str, table_name: str) -> str:
    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())
        ctx = orch.get_schema_context(table_name)
        serializable_ctx = _serialize_schema_context(ctx)
        return json.dumps(serializable_ctx, ensure_ascii=False, indent=2)


@mcp.tool()
def sqlseed_inspect_schema(db_path: str, table_name: str | None = None) -> dict[str, Any]:
    """Inspect database schema. Returns column info, foreign keys, indexes,
    sample data, and schema_hash for specified table or all tables."""
    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        if table_name:
            _validate_table_name(table_name, orch.get_table_names())
        tables = [table_name] if table_name else orch.get_table_names()
        result: dict[str, Any] = {}
        for tbl in tables:
            ctx = orch.get_schema_context(tbl)
            result[tbl] = _serialize_schema_context(ctx)
            result[tbl]["schema_hash"] = _compute_schema_hash(ctx)
        return result


@mcp.tool()
def sqlseed_generate_yaml(
    db_path: str,
    table_name: str,
    max_retries: int = 3,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """Generate YAML config for a table using AI analysis with self-correction.
    Returns YAML string for human review. Requires sqlseed-ai plugin and API key."""
    if not _AI_AVAILABLE:
        return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."

    db_path = _validate_db_path(db_path)
    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())

    ai_config = AIConfig.from_env().apply_overrides(api_key=api_key, base_url=base_url, model=model)

    ai_config.resolve_model()

    analyzer = SchemaAnalyzer(config=ai_config)
    refiner = AiConfigRefiner(analyzer, db_path)

    try:
        result = refiner.generate_and_refine(
            table_name=table_name,
            max_retries=max_retries,
        )
    except AISuggestionFailedError as e:
        return f"# AI suggestion failed: {e}"
    except (ValueError, RuntimeError, OSError) as e:
        return f"# Error: {e}"

    if result:
        output = {"db_path": db_path, "provider": "mimesis", "locale": "en_US", "tables": [result]}
        return str(yaml.dump(output, allow_unicode=True, sort_keys=False, default_flow_style=False))
    return "# No AI suggestions available. Ensure sqlseed-ai plugin is installed and API key is configured."


@mcp.tool()
def sqlseed_execute_fill(
    db_path: str,
    table_name: str,
    count: int = 1000,
    yaml_config: str | None = None,
    enrich: bool = False,
) -> dict[str, Any]:
    """Execute data generation for a table. Optionally provide YAML config string for column rules."""
    db_path = _validate_db_path(db_path)

    if yaml_config is not None and len(yaml_config) > _MAX_YAML_CONFIG_SIZE:
        raise ValueError(f"yaml_config exceeds maximum allowed size of {_MAX_YAML_CONFIG_SIZE} bytes")

    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())
        column_configs = None
        clear_before = False
        seed = None

        if yaml_config:
            data = yaml.safe_load(yaml_config)
            config = GeneratorConfig(**data)
            for t in config.tables:
                if t.name == table_name:
                    column_configs = t.columns
                    clear_before = t.clear_before
                    seed = t.seed
                    break

        result = orch.fill_table(
            table_name=table_name,
            count=count,
            column_configs=column_configs,
            clear_before=clear_before,
            seed=seed,
            enrich=enrich,
        )

        return {
            "table_name": result.table_name,
            "count": result.count,
            "elapsed": result.elapsed,
            "errors": result.errors,
        }


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
    Supported models: gemma-4-26b-a4b-it (default), gemma-4-31b-it, gemma-4-12b-it, gemma-4-e4b-it, gemma-4-e2b-it.
    """
    ai_config, err = _build_ai_config(db_path, model, backend)
    if err is not None:
        return err
    if ai_config is None:
        raise ValueError("AI configuration is required but was not provided.")

    with DataOrchestrator(db_path) as orch:
        _validate_table_name(table_name, orch.get_table_names())
        schema_ctx = orch.get_schema_context(table_name)

    analyzer = SchemaAnalyzer(config=ai_config)
    result = analyzer.analyze_table_from_ctx(**schema_ctx)

    if not result:
        return {"error": "Gemma 4 analysis returned no result. Check API key and model availability."}

    return {
        "model": ai_config.model,
        "backend": ai_config.backend.value,
        "table_name": table_name,
        "config": result,
    }


@mcp.tool()
def sqlseed_gemma4_agent_fill(
    db_path: str,
    table_name: str,
    count: int = 1000,
    model: str | None = None,
    backend: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """End-to-end AI Agent: Gemma 4 analyzes schema → generates config → fills data.

    This is a complete Agent workflow that demonstrates Gemma 4's Native Function
    Calling capability for the AI Agent track:
    1. Inspect schema (Tool Calling: analyze_schema)
    2. Generate data configuration (self-correction loop)
    3. Execute data fill

    The agent uses Gemma 4's tool use to understand schema semantics and
    produce appropriate data generation rules automatically.
    """
    ai_config, err = _build_ai_config(db_path, model, backend)
    if err is not None:
        return err
    if ai_config is None:
        raise ValueError("AI configuration is required but was not provided.")

    # Step 1: AI analysis with self-correction
    analyzer = SchemaAnalyzer(config=ai_config)
    refiner = AiConfigRefiner(analyzer, db_path)

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

        return {
            "model": ai_config.model,
            "backend": ai_config.backend.value,
            "table_name": result.table_name,
            "count": result.count,
            "elapsed": result.elapsed,
            "errors": result.errors,
            "ai_config": ai_result,
        }


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


def _build_backends(ai_config: Any) -> list[dict[str, Any]]:
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
    return GemmaModel.GEMMA_4_26B_A4B.value


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
    if not _AI_AVAILABLE:
        return {
            "models": [],
            "backends": [
                {"id": bid, "description": desc, "available": False} for bid, desc in _BACKEND_DESCRIPTIONS.items()
            ],
            "hardware": {},
            "error": "sqlseed-ai plugin not installed. Install with: pip install sqlseed-ai",
        }

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
