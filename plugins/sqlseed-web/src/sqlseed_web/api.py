"""HTTP API for sqlseed-web.

Routers (all mounted under ``/api``):

- ``/api/meta``      — introspection: generators + param signatures, hooks,
                       providers, AI backend status. The "acceptance cockpit"
                       surface: counts must match the code (36 generators,
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

import importlib
import inspect
from contextlib import closing
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import StatementError
from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier, validate_table_name
from sqlseed.config.loader import load_config
from sqlseed.config.models import GeneratorConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._dispatch import GeneratorDispatchMixin

from sqlseed_web.ai_settings import SettingsRequest, credential_snapshot, resolve_settings, set_session_preferences
from sqlseed_web.operation_errors import generation_errors
from sqlseed_web.runtime_lifecycle import start_background
from sqlseed_web.settings_environment import ai_import_failure, provider_availability, require_ai_available
from sqlseed_web.state import ConnectionBusyError, UnknownConnectionError, state

if TYPE_CHECKING:
    import httpx

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
    transform: str | None = None
    enrich: bool = False


class FillRequest(BaseModel):
    table: str
    count: int = 1000
    columns: dict[str, Any] | None = None
    seed: int | None = None
    batch_size: int = 5000
    clear_before: bool = False
    enrich: bool = False
    transform: str | None = None


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


def _error_detail(exc: Exception) -> str:
    """Describe a failure without SQLAlchemy's SQL and parameter dump."""
    if isinstance(exc, StatementError) and exc.orig is not None:
        return str(exc.orig)
    return str(exc)


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
        return bytes.decode(value, "utf-8", errors="replace")
    return value


def _yaml_to_config_dict(yaml_text: str) -> dict[str, Any]:
    """Parse YAML into a plain dict; empty input -> empty dict."""
    if not (text := (yaml_text or "").strip()):
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
    with state.job_completion(job_id):
        job = state.get_job(job_id)
        orch: DataOrchestrator | None = None
        try:
            with state.connection_operation(conn_id, job_id=job_id) as conn:
                orch = conn.orchestrator
                job.rows_before = orch.get_row_count(req.table)
                result = orch.fill_table(
                    req.table,
                    count=req.count,
                    columns=req.columns,
                    seed=req.seed,
                    batch_size=req.batch_size,
                    clear_before=req.clear_before,
                    enrich=req.enrich,
                    transform=req.transform,
                )
                payload = {
                    "rows_inserted": result.count,
                    "elapsed": result.elapsed,
                    "rows_per_second": result.rows_per_second,
                    "errors": result.errors,
                    "table": req.table,
                    "row_count_after": orch.get_row_count(req.table),
                }
            state.complete_job(
                job_id,
                result=payload,
                rows_inserted=result.count,
                error="\n".join(result.errors) if result.errors else None,
            )
        except generation_errors(orch, additional=(UnknownConnectionError, ImportError)) as exc:
            error = f"{type(exc).__name__}: {_error_detail(exc)}"
            state.complete_job(job_id, error=error)
            logger.error("fill job failed", job_id=job_id, error=error)


# --------------------------------------------------------------------------
# Meta: generators / hooks / providers / AI — the acceptance cockpit
# --------------------------------------------------------------------------


def _generator_param_schema() -> dict[str, list[str]]:
    """Param names per generator, from ``BaseProvider._gen_*`` signatures."""
    from sqlseed.generators.base_provider import BaseProvider

    provider = BaseProvider()
    schema: dict[str, list[str]] = {}
    for name in GeneratorDispatchMixin.GENERATOR_MAP:
        if (method := getattr(provider, f"_gen_{name}", None)) is None:
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
    statuses = provider_availability()
    return {
        "available": [name for name, facts in statuses.items() if facts["available"]],
        "default_chain": ["mimesis", "faker", "base"],
        "statuses": statuses,
    }


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


@router.get(
    "/fs/browse",
    responses={
        400: {"description": HTTPStatus(400).phrase},
        403: {"description": HTTPStatus(403).phrase},
        404: {"description": HTTPStatus(404).phrase},
    },
)
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
    """Effective AI status: env defaults merged with the session-level override.

    The wizard's readiness check and the meta page both consume this —
    reporting env-only state here made the UI contradict the AI panel
    after an in-session backend switch.
    """
    try:
        cfg = resolve_settings(state)[0]
    except ImportError:
        return ai_import_failure()
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

# 下拉展示顺序 = 通用程度：OpenAI 兼容协议最通用（vLLM / OpenRouter / 自建网关
# 都能接，且是 AIConfig 的默认后端），Google AI Studio 次之，本地后端殿后。
# heal 页会在此之上把「当前生效」的后端再提到第一位（见 heal.js）。
AI_BACKENDS: list[dict[str, str]] = [
    {"id": "openai_compat", "label": "OpenAI 兼容服务（在线/自建）", "needs_key": "1", "needs_url": "1"},
    {"id": "google_ai_studio", "label": "Google AI Studio（在线）", "needs_key": "1", "needs_url": "0"},
    {"id": "ollama", "label": "Ollama", "needs_key": "0", "needs_url": "0"},
    {"id": "lm_studio", "label": "LM Studio", "needs_key": "0", "needs_url": "0"},
]


@router.get("/ai/config")
def ai_config_get() -> dict[str, Any]:
    """Current effective AI config: session override merged over env defaults."""
    try:
        cfg = resolve_settings(state)[0]
    except ImportError:
        return ai_import_failure()
    return {
        "available": True,
        "backends": AI_BACKENDS,
        "override": {
            key: value for key, value in state.get_ai_override().items() if key in {"backend", "model", "base_url"}
        },
        "effective": {
            "backend": cfg.backend.value,
            "model": cfg.resolve_model(),
            "base_url": cfg.base_url,
            "api_key_present": bool(cfg.resolve_api_key()),
        },
    }


@router.post("/ai/config", responses={422: {"description": HTTPStatus(422).phrase}})
def ai_config_set(req: AIConfigRequest) -> dict[str, Any]:
    """Store session-level AI overrides (backend/model/key/base_url)."""
    # An empty legacy request still resets only the in-memory overrides.
    if not req.model_fields_set:
        state.set_ai_override({})
    else:
        try:
            set_session_preferences(state, req.model_dump(exclude_unset=True))
        except ImportError:
            return ai_config_get()
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, detail="AI 配置字段无效，请检查后端与 HTTP(S) 地址。") from exc
    return ai_config_get()


def _local_ai_probe_result(result: dict[str, Any], response: httpx.Response, base: str) -> None:
    """Describe local reachability, preserving a successful probe with malformed model metadata."""
    result["ok"] = response.status_code == 200
    if result["ok"]:
        try:
            result["models"] = [str(model.get("id")) for model in response.json().get("data", []) if model.get("id")]
        except (ValueError, AttributeError):
            pass
        model_hint = f"可用模型：{', '.join(result['models'])}" if result["models"] else "未列出模型"
        result["message"] = f"本地服务可达（{base}）。无需 API Key。{model_hint}"
    else:
        result["message"] = f"本地服务响应异常：HTTP {response.status_code}"


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
        cfg = resolve_settings(state)[0]
        import httpx
    except ImportError:
        return ai_import_failure()
    backend = cfg.backend.value
    result: dict[str, Any] = {"available": True, "backend": backend, "models": []}
    try:
        base = cfg.resolve_base_url()
        probe_url = base.rstrip("/") + "/models"
        if backend in {"ollama", "lm_studio"}:
            # Local servers: reachability is the whole story; no key needed.
            resp = httpx.get(probe_url, timeout=5)
            _local_ai_probe_result(result, resp, base)
        elif not (key := cfg.resolve_api_key()):
            result["ok"] = False
            result["message"] = "在线后端需要 API Key：请在 AI 配置面板填写，或设置 GOOGLE_API_KEY / OPENAI_API_KEY。"
        else:
            resp = httpx.get(probe_url, headers={"Authorization": f"Bearer {key}"}, timeout=8)
            result["ok"] = resp.status_code == 200
            result["message"] = (
                "在线后端连通且 Key 有效。"
                if result["ok"]
                else f"在线后端拒绝：HTTP {resp.status_code}（检查 Key / Base URL）。"
            )
    except (httpx.HTTPError, OSError, ValueError, RuntimeError):
        result["ok"] = False
        result["message"] = "无法连接 AI 服务，请检查地址、认证和服务状态。"
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


@router.post(
    "/connections",
    responses={400: {"description": HTTPStatus(400).phrase}, 422: {"description": HTTPStatus(422).phrase}},
)
def connect_db(req: ConnectRequest) -> dict[str, Any]:
    if bool(req.db_path) == bool(req.url):
        raise HTTPException(status_code=422, detail="provide exactly one of db_path / url")
    if (target := req.db_path or req.url) is None:  # unreachable; narrows the type for mypy strict
        raise HTTPException(status_code=422, detail="empty connection target")
    conn: Any = None
    try:
        conn = state.add_connection(target, provider=req.provider, locale=req.locale)
        orch = conn.orchestrator
        tables = orch.get_table_names()
    except Exception as exc:
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


@router.get(
    "/connections/{conn_id}/tables",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def list_tables(conn_id: str) -> dict[str, Any]:
    """Table summary for an existing connection.

    Exists so the frontend can restore its state after a page reload: the
    connection object survives server-side, but the browser's module-level
    ``store`` (connId/target/tables) is wiped, and the wizard needs the table
    list to rebuild its tree. Shape mirrors the POST /connections response.
    """
    orch = _conn_or_404(conn_id)
    try:
        return {
            "conn_id": conn_id,
            "target": state.get_connection(conn_id).target,
            "tables": [
                {
                    "name": t,
                    "row_count": orch.get_row_count(t),
                    "column_count": len(orch.get_column_names(t)),
                    "foreign_keys": len(orch.get_foreign_keys(t)),
                }
                for t in orch.get_table_names()
            ],
        }
    except HTTPException:
        raise
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc


@router.get("/connections")
def list_connections() -> dict[str, Any]:
    return {"connections": state.list_connections()}


@router.delete(
    "/connections/{conn_id}",
    responses={404: {"description": HTTPStatus(404).phrase}, 409: {"description": HTTPStatus(409).phrase}},
)
def close_db(conn_id: str) -> dict[str, Any]:
    try:
        state.close_connection(conn_id)
    except ConnectionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.get("/jobs/{job_id}", responses={404: {"description": HTTPStatus(404).phrase}})
def job_status(job_id: str) -> dict[str, Any]:
    try:
        job = state.job_snapshot(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    live_rows = None
    if job.status == "running" and job.kind == "fill":
        orch = None
        try:
            orch = state.get_connection(job.conn_id).orchestrator
            live_rows = orch.get_row_count(job.label)
        except generation_errors(orch, additional=(UnknownConnectionError,)):
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


@router.get(
    "/connections/{conn_id}/tables/{table}/schema",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def table_schema(conn_id: str, table: str) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        if not (columns := _serialize(orch.get_column_info(table))):
            raise ValueError(f"Table '{table}' does not exist")
        fks = _serialize(orch.get_foreign_keys(table))
        skippable = sorted(orch.get_skippable_columns(table))
        # 数据库硬唯一约束列（主键/唯一索引/UNIQUE 约束）——前端属性面板
        # 用它把「设置唯一」锁定为必开，避免用户配出必 IntegrityError 的组合。
        unique_columns = sorted(orch._schema.detect_unique_columns(table))
        row_count = orch.get_row_count(table)
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
    return {
        "table": table,
        "row_count": row_count,
        "columns": columns,
        "foreign_keys": fks,
        "skippable": skippable,
        "unique_columns": unique_columns,
    }


@router.get(
    "/connections/{conn_id}/topo-order",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def topo_order(conn_id: str, tables: str | None = None) -> dict[str, Any]:
    """FK-topological table order (referenced tables first) — the wizard's
    "表生成顺序" (参考工具 parity). Defaults to all tables of the connection."""
    orch = _conn_or_404(conn_id)
    names = [t for t in (tables or "").split(",") if t] or orch.get_table_names()
    try:
        order = orch.get_topological_table_order(names)
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
    return {"tables": order}


@router.get(
    "/connections/{conn_id}/tables/{table}/mapping",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def table_mapping(conn_id: str, table: str) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        specs = orch.get_column_mapping(table)
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
    return {"table": table, "mapping": {col: _serialize(spec) for col, spec in specs.items()}}


@router.get(
    "/connections/{conn_id}/tables/{table}/yaml-template",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def table_yaml_template(conn_id: str, table: str) -> dict[str, Any]:
    """Generate a fillable YAML skeleton from the inferred mapping."""
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        specs = orch.get_column_mapping(table)
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
    target = state.get_connection(conn_id).target
    columns: dict[str, Any] = {}
    for col, spec in specs.items():
        if (gen := spec.generator_name) in {"skip", "__enrich__"}:
            continue
        entry: dict[str, Any] = {"generator": gen}
        if spec.params:
            entry["params"] = dict(spec.params)
        if spec.null_ratio:
            entry["null_ratio"] = spec.null_ratio
        columns[col] = entry
    config = {
        "url" if "://" in target else "db_path": target,
        "provider": state.get_connection(conn_id).provider,
        "tables": [{"name": table, "count": 100, "columns": [{"name": c, **v} for c, v in columns.items()]}],
    }
    return {"yaml": yaml.safe_dump(config, sort_keys=False, allow_unicode=True)}


# --------------------------------------------------------------------------
# Preview / fill / data
# --------------------------------------------------------------------------


@router.post(
    "/connections/{conn_id}/preview",
    responses={
        400: {"description": HTTPStatus(400).phrase},
        404: {"description": HTTPStatus(404).phrase},
        409: {"description": HTTPStatus(409).phrase},
    },
)
def preview_rows(conn_id: str, req: PreviewRequest) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        with state.connection_operation(conn_id) as conn:
            rows = conn.orchestrator.preview_table(
                req.table,
                count=req.count,
                columns=req.columns,
                seed=req.seed,
                transform=req.transform,
                enrich=req.enrich,
            )
    except UnknownConnectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=f"preview failed: {_error_detail(exc)}") from exc
    return {"table": req.table, "rows": _serialize(rows)}


@router.post(
    "/connections/{conn_id}/fill",
    responses={
        404: {"description": HTTPStatus(404).phrase},
        409: {"description": HTTPStatus(409).phrase},
        503: {"description": HTTPStatus(503).phrase},
    },
)
def start_fill(conn_id: str, req: FillRequest) -> dict[str, Any]:
    _conn_or_404(conn_id)
    try:
        with state.connection_operation(conn_id, write=True):
            job = state.create_job(conn_id, kind="fill", label=req.table)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        start_background(target=_run_fill_job, args=(conn_id, job.job_id, req), category="job")
    except Exception as exc:
        state.complete_job(job.job_id, error=_error_detail(exc))
        raise HTTPException(status_code=503, detail="无法启动生成任务，请重试。") from exc
    return {"job_id": job.job_id, "table": req.table, "count": req.count}


@router.get(
    "/connections/{conn_id}/tables/{table}/rows",
    responses={400: {"description": HTTPStatus(400).phrase}, 404: {"description": HTTPStatus(404).phrase}},
)
def table_rows(conn_id: str, table: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    orch = _conn_or_404(conn_id)
    try:
        validate_table_name(table)
        total = orch.get_row_count(table)
        sql = f"SELECT * FROM {quote_identifier(table)} LIMIT ? OFFSET ?"
        rows = orch.query(sql, (limit, offset))
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
    return {"table": table, "total": total, "limit": limit, "offset": offset, "rows": _serialize(rows)}


class QueryRequest(BaseModel):
    sql: str


@router.post(
    "/connections/{conn_id}/query",
    responses={
        400: {"description": HTTPStatus(400).phrase},
        404: {"description": HTTPStatus(404).phrase},
        422: {"description": HTTPStatus(422).phrase},
    },
)
def run_query(conn_id: str, req: QueryRequest) -> dict[str, Any]:
    """Read-only SQL console: SELECT statements only."""
    statement = (req.sql or "").strip().rstrip(";")
    if not statement.lower().startswith("select") or ";" in statement:
        raise HTTPException(status_code=422, detail="only single read-only SELECT statements are allowed")
    orch = _conn_or_404(conn_id)
    try:
        rows = orch.query(statement)
    except generation_errors(orch) as exc:
        raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc
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
    except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
        return {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"valid": True, "config": _serialize(config_to_dict(cfg))}


@router.post("/config/serialize", responses={422: {"description": HTTPStatus(422).phrase}})
def config_serialize(req: YamlRequest) -> dict[str, Any]:
    data = _yaml_to_config_dict(req.yaml)
    return {"yaml": yaml.safe_dump(data, sort_keys=False, allow_unicode=True)}


def load_config_from_text(yaml_text: str) -> GeneratorConfig:
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


def config_to_dict(cfg: GeneratorConfig) -> dict[str, Any]:
    """Preserve every validated field in a JSON-safe YAML-shaped mapping."""
    return cfg.model_dump(mode="json", exclude_none=True)


# --------------------------------------------------------------------------
# Self-heal laboratory (Layers 2 / 3 / 5)
# --------------------------------------------------------------------------


def _require_ai_export(module_name: str, export_name: str) -> None:
    module = importlib.import_module(module_name)
    try:
        getattr(module, export_name)
    except AttributeError as exc:
        raise ImportError(f"Required AI export is unavailable: {module_name}.{export_name}") from exc


def _require_sqlseed_ai() -> None:
    try:
        require_ai_available()
        _require_ai_export("sqlseed_ai.contracts.builtin_violations", "BUILTIN_VIOLATIONS")
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=ai_import_failure(),
        ) from exc


def _build_snapshot(conn_id: str) -> Any:
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

    conn = state.get_connection(conn_id)
    if "://" in conn.target:
        return SchemaSnapshot(url=conn.target)
    return SchemaSnapshot(db_path=conn.target)


@router.post(
    "/connections/{conn_id}/heal/validate",
    responses={
        404: {"description": HTTPStatus(404).phrase},
        422: {"description": HTTPStatus(422).phrase},
        503: {"description": HTTPStatus(503).phrase},
    },
)
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
        is_url = "://" in conn.target
        resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
        validator = FastValidator(
            resolver,
            db_path=None if is_url else conn.target,
            url=conn.target if is_url else None,
        )
        result = validator.validate(config, snapshot, dialect=req.dialect)
    except HTTPException:
        raise
    except generation_errors(conn.orchestrator) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "is_clean": result.is_clean,
        "violation_count": len(result.violations),
        "violations": [_serialize(v) for v in result.violations],
        "column_groups": [_serialize(g) for g in result.column_groups],
        "schema_hash": snapshot.schema_hash,
    }


@router.post(
    "/connections/{conn_id}/heal/repair",
    responses={
        404: {"description": HTTPStatus(404).phrase},
        422: {"description": HTTPStatus(422).phrase},
        503: {"description": HTTPStatus(503).phrase},
    },
)
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
        is_url = "://" in conn.target
        pipeline = RepairPipeline(
            resolver,
            db_path=None if is_url else conn.target,
            url=conn.target if is_url else None,
        )
        config, repair_result = pipeline.run(config, snapshot)
    except HTTPException:
        raise
    except generation_errors(conn.orchestrator) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "fix_count": repair_result.fix_count,
        "applied_fixes": [_serialize(f) for f in repair_result.applied_fixes],
        "unfixable": [_serialize(v) for v in repair_result.unfixable],
        "repaired_yaml": yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
    }


class _CountingLLMClient:
    """Proxy over the LLM client that counts ``chat_completions_create`` calls.

    The auto-heal pipeline is deterministic-first (clean subgraphs skip
    the LLM layer entirely), so a run can finish without calling the LLM.
    The count is reported as ``job.result.llm_calls`` to make that visible.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0

    def chat_completions_create(self, **kwargs: Any) -> Any:
        self.calls += 1
        return self._inner.chat_completions_create(**kwargs)

    def __getattr__(self, name: str) -> Any:
        # Passthrough so the proxy satisfies the full LLMClient surface.
        return getattr(self._inner, name)


def _run_auto_heal_job(conn_id: str, job_id: str, req: AutoHealRequest) -> None:
    """Background-thread body for the full auto-heal pipeline (Layer 5)."""
    with state.job_completion(job_id):
        database_orch: DataOrchestrator | None = None
        ai_errors: tuple[type[Exception], ...] = (ImportError,)
        try:
            conn = state.get_connection(conn_id)
            database_orch = conn.orchestrator
            from sqlseed_ai._client import APIError
            from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
            from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
            from sqlseed_ai.contracts.matrix import ContractResolver
            from sqlseed_ai.runtime import build_ai_config, build_heal_orchestrator, build_llm_client
            from sqlseed_ai.validator.main import FastValidator
            from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

            ai_errors += (APIError,)
            # Request overrides may change service; bind authentication before the
            # shared runtime builder can fall back to an environment credential.
            current, _ = resolve_settings(state)
            request_settings = SettingsRequest.model_validate(
                {
                    "backend": req.backend or current.backend.value,
                    "model": req.model or current.model or "",
                    "base_url": req.base_url or current.base_url or "",
                    "api_key": req.api_key or "",
                }
            )
            scoped, _ = resolve_settings(state, request_settings)
            ai_config = build_ai_config(
                api_key=scoped.api_key,
                base_url=scoped.base_url,
                model=scoped.model,
                timeout=req.timeout,
                log_llm=False,
            )
            ai_config.backend = scoped.backend
            ai_config.api_key = scoped.api_key
            ai_config.base_url = scoped.base_url
            ai_config.model = scoped.model
            ai_config = credential_snapshot(ai_config)
            if not ai_config.resolve_api_key():
                raise RuntimeError(
                    "AI API key not configured: set it in the AI config panel, or via "
                    "SQLSEED_AI_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY, or switch to a "
                    "local backend (Ollama / LM Studio) in the panel"
                )
            ai_config.model = ai_config.resolve_model()
            is_url = "://" in conn.target
            db_path = None if is_url else conn.target
            url = conn.target if is_url else None
            resolver = ContractResolver(set(BUILTIN_VIOLATIONS), set())
            validator = FastValidator(resolver, db_path=db_path, url=url)
            # Count LLM invocations: the pipeline is deterministic-first — clean
            # subgraphs skip Layer 4 entirely, so a run may finish WITHOUT any
            # LLM call. Surfacing the count answers "did the AI actually run?".
            with closing(build_llm_client(ai_config)) as owned_client:
                client = _CountingLLMClient(owned_client)
                prelim_snapshot = SchemaSnapshot(db_path=db_path, url=url)
                heal_orch = build_heal_orchestrator(
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
            state.complete_job(
                job_id,
                result={
                    "yaml": yaml_str,
                    "model": ai_config.model,
                    "backend": ai_config.backend.value,
                    "llm_calls": client.calls,
                },
            )
        except generation_errors(database_orch, additional=(UnknownConnectionError,) + ai_errors) as exc:
            error = f"{type(exc).__name__}: {_error_detail(exc)}"
            state.complete_job(job_id, error=error)
            logger.error("auto-heal job failed", job_id=job_id, error=error)


@router.post(
    "/connections/{conn_id}/heal/auto",
    responses={
        404: {"description": HTTPStatus(404).phrase},
        409: {"description": HTTPStatus(409).phrase},
        503: {"description": HTTPStatus(503).phrase},
    },
)
def heal_auto(conn_id: str, req: AutoHealRequest) -> dict[str, Any]:
    _require_sqlseed_ai()
    _conn_or_404(conn_id)
    try:
        _require_ai_export("sqlseed_ai.runtime", "build_ai_config")
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=ai_import_failure()) from exc
    try:
        job = state.create_job(conn_id, kind="auto_heal", label="auto-heal")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        start_background(target=_run_auto_heal_job, args=(conn_id, job.job_id, req), category="job")
    except Exception as exc:
        state.complete_job(job.job_id, error=_error_detail(exc))
        raise HTTPException(status_code=503, detail="无法启动分析任务，请重试。") from exc
    return {"job_id": job.job_id}
