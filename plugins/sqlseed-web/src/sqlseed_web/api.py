"""HTTP API for sqlseed-web.

Routers (all mounted under ``/api``):

- ``/api/meta``      — introspection: generators + param signatures, hooks,
                       providers, AI backend status. The "acceptance cockpit"
                       surface: counts must match the code (35 generators,
                       12 hooks).
- ``/api/connections`` — open/list/close databases; table listing.
- ``/api/connections/{id}/tables/{t}`` — schema (columns/FKs/indexes),
                       column mapping (the 9-level chain output per column).
- preview / fill / rows — generation execution and data browsing.
- ``/api/config``    — YAML <-> dict round-trip via core load_config.
- ``/api/connections/{id}/heal`` — self-heal laboratory:
                       validate (Layer 2), repair (Layer 3), auto-heal
                       (Layer 5, requires sqlseed-ai + LLM backend).

sqlseed-ai is an optional dependency: heal endpoints degrade to
``{"available": false, "reason": ...}`` when it is not installed.
"""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.config.loader import load_config
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._dispatch import GeneratorDispatchMixin

from sqlseed_web.state import state

logger = get_logger(__name__)

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------


class ConnectRequest(BaseModel):
    db_path: str | None = None
    url: str | None = None
    provider: str = "mimesis"
    locale: str = "en_US"


class PreviewRequest(BaseModel):
    table: str
    count: int = 5
    columns: dict[str, Any] | None = None
    seed: int | None = None


class FillRequest(BaseModel):
    table: str
    count: int = 1000
    columns: dict[str, Any] | None = None
    seed: int | None = None
    batch_size: int = 5000
    clear_before: bool = False
    enrich: bool = False


class YamlRequest(BaseModel):
    yaml: str


class HealValidateRequest(BaseModel):
    yaml: str
    dialect: str = "sqlite"


class AutoHealRequest(BaseModel):
    budget_seconds: float = 300.0
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    backend: str | None = None
    timeout: float = 0.0


class AIConfigRequest(BaseModel):
    backend: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _conn_or_404(conn_id: str) -> DataOrchestrator:
    try:
        return state.get_connection(conn_id).orchestrator
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _serialize(value: Any) -> Any:
    """Make any core dataclass JSON-safe (dates/datetimes/bytes -> str)."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return value


def _yaml_to_config_dict(yaml_text: str) -> dict[str, Any]:
    """Parse YAML into a plain dict; empty input -> empty dict."""
    text = (yaml_text or "").strip()
    if not text:
        return {}
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"invalid YAML: {exc}") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="YAML root must be a mapping")
    return parsed


def _run_fill_job(conn_id: str, job_id: str, req: FillRequest) -> None:
    """Background-thread body for a fill job."""
    conn = state.get_connection(conn_id)
    orch = conn.orchestrator
    job = state.get_job(job_id)
    try:
        with state.connection_lock(conn_id):
            job.rows_before = orch.get_row_count(req.table)
            result = orch.fill_table(
                req.table,
                count=req.count,
                columns=req.columns,
                seed=req.seed,
                batch_size=req.batch_size,
                clear_before=req.clear_before,
                enrich=req.enrich,
            )
        job.rows_inserted = getattr(result, "count", 0) or 0
        # Assign result BEFORE status: the polling endpoint may otherwise
        # observe status="done" with an empty result dict (read race).
        job.result = {
            "rows_inserted": job.rows_inserted,
            "elapsed": getattr(result, "elapsed", 0.0),
            "rows_per_second": getattr(result, "rows_per_second", 0.0),
            "errors": getattr(result, "errors", None),
            "table": req.table,
            "row_count_after": orch.get_row_count(req.table),
        }
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 — job isolation boundary
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        logger.error("fill job failed", job_id=job_id, error=job.error)
    finally:
        job.finished_at = time.time()


# --------------------------------------------------------------------------
# Meta: generators / hooks / providers / AI — the acceptance cockpit
# --------------------------------------------------------------------------


def _generator_param_schema() -> dict[str, list[str]]:
    """Param names per generator, from ``BaseProvider._gen_*`` signatures."""
    from sqlseed.generators.base_provider import BaseProvider

    provider = BaseProvider()
    schema: dict[str, list[str]] = {}
    for name in GeneratorDispatchMixin.GENERATOR_MAP:
        method = getattr(provider, f"_gen_{name}", None)
        if method is None:
            schema[name] = []
            continue
        params = [p for p in inspect.signature(method).parameters if p != "self"]
        schema[name] = params
    return schema


@router.get("/meta/generators")
def meta_generators() -> dict[str, Any]:
    names = sorted(GeneratorDispatchMixin.GENERATOR_MAP.keys())
    return {"count": len(names), "names": names, "params": _generator_param_schema()}


@router.get("/meta/hooks")
def meta_hooks() -> dict[str, Any]:
    from sqlseed.plugins.hookspecs import SqlseedHookSpec

    hooks = []
    for name, fn in vars(SqlseedHookSpec).items():
        if name.startswith("sqlseed_") and callable(fn):
            marker: dict[str, Any] | None = getattr(fn, "sqlseed_spec", None)
            hooks.append(
                {
                    "name": name,
                    "firstresult": marker is not None and bool(marker.get("firstresult")),
                }
            )
    return {"count": len(hooks), "hooks": hooks}


@router.get("/meta/providers")
def meta_providers() -> dict[str, Any]:
    from sqlseed.generators import registry as gen_registry

    available = ["base", "faker"]
    if getattr(gen_registry, "HAS_MIMESIS", False):
        available.append("mimesis")
    return {"available": available, "default_chain": ["mimesis", "faker", "base"]}


# Curated locale list (faker-style codes — the lingua franca across providers:
# MimesisProvider.set_locale maps these to mimesis short codes internally).
# Keep in sync with the locale_map in mimesis_provider.py.
SUPPORTED_LOCALES: list[dict[str, str]] = [
    {"code": "zh_CN", "label": "简体中文（中国）"},
    {"code": "en_US", "label": "English (US)"},
    {"code": "en_GB", "label": "English (UK)"},
    {"code": "zh_TW", "label": "繁體中文（台灣）"},
    {"code": "ja_JP", "label": "日本語"},
    {"code": "ko_KR", "label": "한국어"},
    {"code": "de_DE", "label": "Deutsch"},
    {"code": "fr_FR", "label": "Français"},
    {"code": "es_ES", "label": "Español"},
    {"code": "pt_BR", "label": "Português (Brasil)"},
    {"code": "ru_RU", "label": "Русский"},
    {"code": "it_IT", "label": "Italiano"},
]

# File suffixes recognized as local database files (SQLite family).
DB_FILE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".db3"}


@router.get("/meta/locales")
def meta_locales() -> dict[str, Any]:
    return {"locales": SUPPORTED_LOCALES, "default": "en_US"}


@router.get("/meta/dialects")
def meta_dialects() -> dict[str, Any]:
    """Connection kinds the UI offers (core supports SQLite + PostgreSQL today)."""
    return {
        "kinds": [
            {"id": "sqlite", "label": "本地数据库文件", "hint": "SQLite 文件（.db / .sqlite / .sqlite3）"},
            {"id": "postgresql", "label": "PostgreSQL", "hint": "字段化填写连接参数"},
            {"id": "url", "label": "自定义 URL", "hint": "任意 SQLAlchemy URL（为未来数据库预留）"},
        ]
    }


@router.get("/fs/browse")
def fs_browse(path: str | None = None, all_files: bool = False) -> dict[str, Any]:
    """List a local directory for the file picker modal.

    The UI server runs on the user's own machine (127.0.0.1), so server-side
    browsing is what makes a real "choose file" button possible — browsers
    never expose absolute paths from ``<input type="file">``.
    """
    from pathlib import Path

    home = Path.home()
    target = Path(path).expanduser() if path else home
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {target}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {target}")
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue  # hidden files add noise; local tools rarely need them
            is_db = child.suffix.lower() in DB_FILE_SUFFIXES
            if child.is_file() and not all_files and not is_db:
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "is_db": is_db,
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"permission denied: {target}") from exc
    return {"path": str(target), "parent": str(target.parent), "home": str(home), "entries": entries}


@router.get("/meta/ai")
def meta_ai() -> dict[str, Any]:
    try:
        from sqlseed_ai.config import AIConfig
    except ImportError:
        return {"available": False, "reason": "sqlseed-ai is not installed (pip install -e ./plugins/sqlseed-web[ai])"}
    cfg = AIConfig.from_env()
    return {
        "available": True,
        "backend": cfg.backend.value,
        "model": cfg.resolve_model(),
        "api_key_present": bool(cfg.resolve_api_key()),
        "tool_calling_protocol": cfg.resolve_tool_calling_protocol(),
    }


# --------------------------------------------------------------------------
# AI config panel (在线/本地大模型 in-UI switching, no env edits / restarts)
# --------------------------------------------------------------------------

AI_BACKENDS: list[dict[str, str]] = [
    {"id": "google_ai_studio", "label": "Google AI Studio（在线）", "needs_key": "1", "needs_url": "0"},
    {"id": "openai_compat", "label": "OpenAI 兼容服务（在线/自建）", "needs_key": "1", "needs_url": "1"},
    {"id": "ollama", "label": "Ollama（本地）", "needs_key": "0", "needs_url": "0"},
    {"id": "lm_studio", "label": "LM Studio（本地）", "needs_key": "0", "needs_url": "0"},
]


@router.get("/ai/config")
def ai_config_get() -> dict[str, Any]:
    """Current effective AI config: session override merged over env defaults."""
    try:
        from sqlseed_ai.config import AIConfig
    except ImportError:
        return {"available": False, "reason": "sqlseed-ai is not installed (pip install -e ./plugins/sqlseed-web[ai])"}
    override = state.get_ai_override()
    cfg = AIConfig.from_env().apply_overrides(
        api_key=override.get("api_key"),
        base_url=override.get("base_url"),
        model=override.get("model"),
    )
    if override.get("backend"):
        from sqlseed_ai.config import AIBackend

        try:
            cfg.backend = AIBackend(override["backend"])
        except ValueError:
            pass
    return {
        "available": True,
        "backends": AI_BACKENDS,
        "override": override,
        "effective": {
            "backend": cfg.backend.value,
            "model": cfg.resolve_model(),
            "base_url": cfg.base_url,
            "api_key_present": bool(cfg.resolve_api_key()),
        },
    }


@router.post("/ai/config")
def ai_config_set(req: AIConfigRequest) -> dict[str, Any]:
    """Store session-level AI overrides (backend/model/key/base_url)."""
    state.set_ai_override(req.model_dump())
    return ai_config_get()


@router.post("/ai/test-connection")
def ai_test_connection() -> dict[str, Any]:
    """Ping the effective AI backend and return a friendly status.

    Ollama/LM Studio need NO API key — a reachable local server is enough.
    This endpoint makes that explicit in the UI instead of a bare 503.
    The probe URL is ``{base_url}/models`` (OpenAI-compatible list endpoint;
    all four backends serve it — probing the bare Ollama host's ``/models``
    returns 404 and once made a healthy server look dead).
    """
    try:
        from sqlseed_ai.config import AIConfig
    except ImportError:
        return {"available": False, "reason": "sqlseed-ai is not installed (pip install -e ./plugins/sqlseed-web[ai])"}
    override = state.get_ai_override()
    cfg = AIConfig.from_env().apply_overrides(
        api_key=override.get("api_key"),
        base_url=override.get("base_url"),
        model=override.get("model"),
    )
    if override.get("backend"):
        from sqlseed_ai.config import AIBackend

        try:
            cfg.backend = AIBackend(override["backend"])
        except ValueError:
            pass
    backend = cfg.backend.value
    result: dict[str, Any] = {"available": True, "backend": backend, "models": []}
    try:
        import httpx

        base = cfg.resolve_base_url()
        probe_url = base.rstrip("/") + "/models"
        if backend in ("ollama", "lm_studio"):
            # Local servers: reachability is the whole story; no key needed.
            resp = httpx.get(probe_url, timeout=5)
            result["ok"] = resp.status_code == 200
            if result["ok"]:
                try:
                    result["models"] = [str(m.get("id")) for m in resp.json().get("data", []) if m.get("id")]
                except (ValueError, AttributeError):
                    pass
                model_hint = f"可用模型：{', '.join(result['models'])}" if result["models"] else "未列出模型"
                result["message"] = f"本地服务可达（{base}）。无需 API Key。{model_hint}"
            else:
                result["message"] = f"本地服务响应异常：HTTP {resp.status_code}"
        else:
            key = cfg.resolve_api_key()
            if not key:
                result["ok"] = False
                result["message"] = (
                    "在线后端需要 API Key：请在 AI 配置面板填写，或设置 GOOGLE_API_KEY / OPENAI_API_KEY。"
                )
            else:
                resp = httpx.get(probe_url, headers={"Authorization": f"Bearer {key}"}, timeout=8)
                result["ok"] = resp.status_code == 200
                result["message"] = (
                    "在线后端连通且 Key 有效。"
                    if result["ok"]
                    else f"在线后端拒绝：HTTP {resp.status_code}（检查 Key / Base URL）。"
                )
    except Exception as exc:  # noqa: BLE001 — connectivity probe
        result["ok"] = False
        result["message"] = f"无法连接 {backend}：{exc}"
        if backend == "ollama":
            result["message"] += "（本地需先运行 `ollama serve`，默认 http://localhost:11434；无需任何密钥）"
    return result


@router.get("/meta/info")
def meta_info() -> dict[str, Any]:
    import sqlseed

    return {
        "sqlseed_version": getattr(sqlseed, "__version__", "unknown"),
        "generators": len(GeneratorDispatchMixin.GENERATOR_MAP),
    }


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------


@router.post("/connections")
def connect_db(req: ConnectRequest) -> dict[str, Any]:
    if bool(req.db_path) == bool(req.url):
        raise HTTPException(status_code=422, detail="provide exactly one of db_path / url")
    target = req.db_path or req.url
    if target is None:  # unreachable; narrows the type for mypy strict
        raise HTTPException(status_code=422, detail="empty connection target")
    conn: Any = None
    try:
        conn = state.add_connection(target, provider=req.provider, locale=req.locale)
        orch = conn.orchestrator
        tables = orch.get_table_names()
    except Exception as exc:  # noqa: BLE001 — surface connect errors as 4xx/5xx
        if conn is not None:
            state.close_connection(conn.conn_id)
        raise HTTPException(status_code=400, detail=f"connection failed: {exc}") from exc
    return {
        "conn_id": conn.conn_id,
        "target": target,
        "provider": conn.provider,
        "locale": conn.locale,
        "tables": [
            {
                "name": t,
                "row_count": orch.get_row_count(t),
                "column_count": len(orch.get_column_names(t)),
                "foreign_keys": len(orch.get_foreign_keys(t)),
            }
            for t in tables
        ],
    }


@router.get("/connections")
def list_connections() -> dict[str, Any]:
    return {"connections": state.list_connections()}


@router.delete("/connections/{conn_id}")
def close_db(conn_id: str) -> dict[str, Any]:
    try:
        state.close_connection(conn_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"closed": conn_id}


@router.get("/jobs")
def jobs() -> dict[str, Any]:
    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "conn_id": j.conn_id,
                "kind": j.kind,
                "label": j.label,
                "status": j.status,
                "rows_inserted": j.rows_inserted,
                "error": j.error,
                "result": j.result,
            }
            for j in state.recent_jobs()
        ]
    }


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    try:
        job = state.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    live_rows = None
    if job.status == "running" and job.kind == "fill":
        try:
            live_rows = state.get_connection(job.conn_id).orchestrator.get_row_count(job.label)
        except Exception:  # noqa: BLE001 — progress is best-effort
            live_rows = None
    return {
        "job_id": job.job_id,
        "status": job.status,
        "rows_inserted": job.rows_inserted,
        "rows_before": job.rows_before,
        "live_rows": live_rows,
        "error": job.error,
        "result": job.result,
    }


# --------------------------------------------------------------------------
# Schema + mapping (the 9-level chain, observable)
# --------------------------------------------------------------------------


@router.get("/connections/{conn_id}/tables/{table}/schema")
def table_schema(conn_id: str, table: str) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        columns = _serialize(orch.get_column_info(table))
        fks = _serialize(orch.get_foreign_keys(table))
        skippable = sorted(orch.get_skippable_columns(table))
        row_count = orch.get_row_count(table)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"table": table, "row_count": row_count, "columns": columns, "foreign_keys": fks, "skippable": skippable}


@router.get("/connections/{conn_id}/topo-order")
def topo_order(conn_id: str, tables: str | None = None) -> dict[str, Any]:
    """FK-topological table order (referenced tables first) — the wizard's
    "表生成顺序" (Navicat parity). Defaults to all tables of the connection."""
    orch = _conn_or_404(conn_id)
    names = [t for t in (tables or "").split(",") if t] or orch.get_table_names()
    try:
        order = orch.get_topological_table_order(names)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tables": order}


@router.get("/connections/{conn_id}/tables/{table}/mapping")
def table_mapping(conn_id: str, table: str) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        specs = orch.get_column_mapping(table)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"table": table, "mapping": {col: _serialize(spec) for col, spec in specs.items()}}


@router.get("/connections/{conn_id}/tables/{table}/yaml-template")
def table_yaml_template(conn_id: str, table: str) -> dict[str, Any]:
    """Generate a fillable YAML skeleton from the inferred mapping."""
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        specs = orch.get_column_mapping(table)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    target = state.get_connection(conn_id).target
    columns: dict[str, Any] = {}
    for col, spec in specs.items():
        gen = spec.generator_name
        if gen in ("skip", "__enrich__"):
            continue
        entry: dict[str, Any] = {"generator": gen}
        if spec.params:
            entry["params"] = dict(spec.params)
        if spec.null_ratio:
            entry["null_ratio"] = spec.null_ratio
        columns[col] = entry
    config = {
        "db_path" if not target.startswith(("postgres", "mysql", "sqlite://")) else "url": target,
        "provider": state.get_connection(conn_id).provider,
        "tables": [{"name": table, "count": 100, "columns": [{"name": c, **v} for c, v in columns.items()]}],
    }
    return {"yaml": yaml.safe_dump(config, sort_keys=False, allow_unicode=True)}


# --------------------------------------------------------------------------
# Preview / fill / data
# --------------------------------------------------------------------------


@router.post("/connections/{conn_id}/preview")
def preview_rows(conn_id: str, req: PreviewRequest) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        rows = orch.preview_table(req.table, count=req.count, columns=req.columns, seed=req.seed)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"preview failed: {exc}") from exc
    return {"table": req.table, "rows": _serialize(rows)}


@router.post("/connections/{conn_id}/fill")
def start_fill(conn_id: str, req: FillRequest) -> dict[str, Any]:
    _conn_or_404(conn_id)
    job = state.create_job(conn_id, kind="fill", label=req.table)
    thread = threading.Thread(target=_run_fill_job, args=(conn_id, job.job_id, req), daemon=True)
    thread.start()
    return {"job_id": job.job_id, "table": req.table, "count": req.count}


@router.get("/connections/{conn_id}/tables/{table}/rows")
def table_rows(conn_id: str, table: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        total = orch.get_row_count(table)
        sql = f"SELECT * FROM {quote_identifier(table)} LIMIT ? OFFSET ?"
        rows = orch.query(sql, (limit, offset))
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"table": table, "total": total, "limit": limit, "offset": offset, "rows": _serialize(rows)}


class QueryRequest(BaseModel):
    sql: str


@router.post("/connections/{conn_id}/query")
def run_query(conn_id: str, req: QueryRequest) -> dict[str, Any]:
    """Read-only SQL console: SELECT statements only."""
    statement = (req.sql or "").strip().rstrip(";")
    if not statement.lower().startswith("select") or ";" in statement:
        raise HTTPException(status_code=422, detail="only single read-only SELECT statements are allowed")
    orch = _conn_or_404(conn_id)
    try:
        rows = orch.query(statement)
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": _serialize(rows)}


# --------------------------------------------------------------------------
# YAML round-trip (uses core load_config for validation parity with CLI)
# --------------------------------------------------------------------------


@router.post("/config/parse")
def config_parse(req: YamlRequest) -> dict[str, Any]:
    try:
        cfg = load_config_from_text(req.yaml)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — validation errors are user input
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"valid": True, "config": _serialize(config_to_dict(cfg))}


@router.post("/config/serialize")
def config_serialize(req: YamlRequest) -> dict[str, Any]:
    data = _yaml_to_config_dict(req.yaml)
    return {"yaml": yaml.safe_dump(data, sort_keys=False, allow_unicode=True)}


def load_config_from_text(yaml_text: str) -> Any:
    """Load a GeneratorConfig from YAML text via a temp file (core API is path-based)."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = Path(f.name)
    try:
        return load_config(str(path))
    finally:
        path.unlink(missing_ok=True)


def config_to_dict(cfg: Any) -> dict[str, Any]:
    """Convert a GeneratorConfig into a plain YAML-shaped dict."""
    data: dict[str, Any] = {}
    if getattr(cfg, "db_path", None):
        data["db_path"] = cfg.db_path
    if getattr(cfg, "url", None):
        data["url"] = cfg.url
    data["provider"] = str(getattr(cfg.provider, "value", cfg.provider))
    if getattr(cfg, "locale", None):
        data["locale"] = cfg.locale
    tables = []
    for t in cfg.tables or []:
        tdata: dict[str, Any] = {"name": t.name}
        if t.count is not None:
            tdata["count"] = t.count
        cols = []
        for c in t.columns or []:
            cdata: dict[str, Any] = {"name": c.name}
            if c.generator:
                cdata["generator"] = c.generator
            if c.params:
                cdata["params"] = dict(c.params)
            if c.null_ratio:
                cdata["null_ratio"] = c.null_ratio
            if c.provider:
                cdata["provider"] = str(getattr(c.provider, "value", c.provider))
            if c.derive_from:
                cdata["derive_from"] = c.derive_from
                cdata["expression"] = c.expression
            if c.constraints and (
                c.constraints.unique or c.constraints.min_value is not None or c.constraints.max_value is not None
            ):
                cons: dict[str, Any] = {}
                if c.constraints.unique:
                    cons["unique"] = True
                if c.constraints.min_value is not None:
                    cons["min_value"] = c.constraints.min_value
                if c.constraints.max_value is not None:
                    cons["max_value"] = c.constraints.max_value
                cdata["constraints"] = cons
            cols.append(cdata)
        if cols:
            tdata["columns"] = cols
        tables.append(tdata)
    data["tables"] = tables
    return data


# --------------------------------------------------------------------------
# Self-heal laboratory (Layers 2 / 3 / 5)
# --------------------------------------------------------------------------


def _require_sqlseed_ai() -> Any:
    try:
        from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS  # noqa: F401
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="sqlseed-ai is not installed (pip install -e ./plugins/sqlseed-ai)",
        ) from exc


def _build_snapshot(conn_id: str) -> Any:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    conn = state.get_connection(conn_id)
    if conn.target.startswith(("postgres", "mysql", "sqlite://")):
        return SchemaSnapshot(url=conn.target)
    return SchemaSnapshot(db_path=conn.target)


@router.post("/connections/{conn_id}/heal/validate")
def heal_validate(conn_id: str, req: HealValidateRequest) -> dict[str, Any]:
    _require_sqlseed_ai()
    _conn_or_404(conn_id)
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.validator.main import FastValidator

    config = _yaml_to_config_dict(req.yaml)
    conn = state.get_connection(conn_id)
    try:
        snapshot = _build_snapshot(conn_id)
        is_url = conn.target.startswith(("postgres", "mysql", "sqlite://"))
        resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
        validator = FastValidator(
            resolver,
            db_path=None if is_url else conn.target,
            url=conn.target if is_url else None,
        )
        result = validator.validate(config, snapshot, dialect=req.dialect)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — lab surface reports raw errors
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "is_clean": result.is_clean,
        "violation_count": len(result.violations),
        "violations": [_serialize(v) for v in result.violations],
        "column_groups": [_serialize(g) for g in result.column_groups],
        "schema_hash": snapshot.schema_hash,
    }


@router.post("/connections/{conn_id}/heal/repair")
def heal_repair(conn_id: str, req: YamlRequest) -> dict[str, Any]:
    _require_sqlseed_ai()
    _conn_or_404(conn_id)
    from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
    from sqlseed_ai.contracts.matrix import ContractResolver
    from sqlseed_ai.repair.pipeline import RepairPipeline

    config = _yaml_to_config_dict(req.yaml)
    conn = state.get_connection(conn_id)
    try:
        snapshot = _build_snapshot(conn_id)
        resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
        is_url = conn.target.startswith(("postgres", "mysql", "sqlite://"))
        pipeline = RepairPipeline(
            resolver,
            db_path=None if is_url else conn.target,
            url=conn.target if is_url else None,
        )
        config, repair_result = pipeline.run(config, snapshot)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — lab surface reports raw errors
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "fix_count": repair_result.fix_count,
        "applied_fixes": [_serialize(f) for f in repair_result.applied_fixes],
        "unfixable": [_serialize(v) for v in repair_result.unfixable],
        "repaired_yaml": yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
    }


def _run_auto_heal_job(conn_id: str, job_id: str, req: AutoHealRequest) -> None:
    """Background-thread body for the full auto-heal pipeline (Layer 5)."""
    job = state.get_job(job_id)
    conn = state.get_connection(conn_id)
    try:
        from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
        from sqlseed_ai.cli.ai_commands import _build_ai_config, _build_heal_orchestrator, _build_llm_client
        from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
        from sqlseed_ai.contracts.matrix import ContractResolver
        from sqlseed_ai.validator.main import FastValidator
        from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

        # Session AI override (UI panel) merged under per-request params.
        override = state.get_ai_override()
        ai_config = _build_ai_config(
            api_key=req.api_key or override.get("api_key"),
            base_url=req.base_url or override.get("base_url"),
            model=req.model or override.get("model"),
            timeout=req.timeout,
            log_llm=False,
        )
        backend_id = req.backend or override.get("backend")
        if backend_id:
            from sqlseed_ai.config import AIBackend

            ai_config.backend = AIBackend(backend_id)
        if not ai_config.resolve_api_key():
            raise RuntimeError(
                "AI API key not configured: set it in the AI config panel, or via "
                "SQLSEED_AI_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY, or switch to a "
                "local backend (Ollama / LM Studio) in the panel"
            )
        ai_config.model = ai_config.resolve_model()
        is_url = conn.target.startswith(("postgres", "mysql", "sqlite://"))
        db_path = None if is_url else conn.target
        url = conn.target if is_url else None
        resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
        validator = FastValidator(resolver, db_path=db_path, url=url)
        client = _build_llm_client(ai_config)
        prelim_snapshot = SchemaSnapshot(db_path=db_path, url=url)
        heal_orch = _build_heal_orchestrator(
            ai_config,
            client,
            prelim_snapshot,
            validator,
            schema_hash=prelim_snapshot.schema_hash,
            max_retries=3,
        )
        orch = AutoHealOrchestrator(
            db_path=db_path,
            url=url,
            heal_orchestrator=heal_orch,
            validator=validator,
            total_budget_seconds=req.budget_seconds,
            verbose=False,
        )
        yaml_str = orch.run()
        job.status = "done"
        job.result = {"yaml": yaml_str, "model": ai_config.model, "backend": ai_config.backend.value}
    except Exception as exc:  # noqa: BLE001 — job isolation boundary
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        logger.error("auto-heal job failed", job_id=job_id, error=job.error)
    finally:
        job.finished_at = time.time()


@router.post("/connections/{conn_id}/heal/auto")
def heal_auto(conn_id: str, req: AutoHealRequest) -> dict[str, Any]:
    _require_sqlseed_ai()
    _conn_or_404(conn_id)
    try:
        from sqlseed_ai.cli.ai_commands import _build_ai_config  # noqa: F401
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="sqlseed-ai is not installed") from exc
    job = state.create_job(conn_id, kind="auto_heal", label="auto-heal")
    thread = threading.Thread(target=_run_auto_heal_job, args=(conn_id, job.job_id, req), daemon=True)
    thread.start()
    return {"job_id": job.job_id}
