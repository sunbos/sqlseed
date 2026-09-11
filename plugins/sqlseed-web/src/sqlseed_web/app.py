"""FastAPI application factory and server entry point."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlseed_web.plugin_management import ManagementService, PluginManager, _loopback, guard_request
from sqlseed_web.plugin_management import router as plugin_router
from sqlseed_web.settings_environment import router as settings_router

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    *,
    manage_plugins: bool = False,
    management_service: ManagementService | None = None,
    supervised_worker: bool = False,
) -> FastAPI:
    """Build the sqlseed-web application (API + static frontend)."""
    manager: ManagementService = management_service or PluginManager(enabled=manage_plugins)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if isinstance(manager, PluginManager):
            manager.start()
        try:
            yield
        finally:
            if isinstance(manager, PluginManager):
                manager.stop()

    app = FastAPI(
        title="sqlseed-web",
        version="0.1.0",
        description="Web workbench and acceptance cockpit for the sqlseed test-data toolkit.",
        lifespan=lifespan,
    )
    app.state.plugin_manager = manager
    app.state.metadata_only = manage_plugins
    if supervised_worker and not manage_plugins:
        from sqlseed_web.runtime_lifecycle import RuntimeAdmissionMiddleware

        app.add_middleware(RuntimeAdmissionMiddleware)

    # no-cache for the ES-module frontend: this app has no build pipeline or
    # asset hashing, so browser-cached stale JS silently breaks new deploys
    # (modules were observed serving 304-fresh while a cached sibling served
    # old code). Always revalidate against the server instead.
    @app.middleware("http")
    async def _no_cache_static(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    @app.middleware("http")
    async def _maintenance_admission(request: Request, call_next: Any) -> Any:
        path = request.url.path
        management_path = path.startswith("/api/settings/plugins/")
        if path.startswith("/api/") and not management_path and not manage_plugins:
            hosts, origins = request.headers.getlist("host"), request.headers.getlist("origin")
            expected = f"{request.url.scheme}://{hosts[0]}" if len(hosts) == 1 else None
            forbidden = expected is None or len(origins) > 1 or bool(origins and origins[0] != expected)
            forbidden = forbidden or request.headers.get("sec-fetch-site") == "cross-site"
            # The default launcher owns a loopback listener. Do not let a DNS
            # rebinding Host turn it into an attacker's apparently same-origin API.
            # External ASGI deployments retain their own Host/proxy policy.
            server = request.scope.get("server")
            if supervised_worker and server and _loopback(server[0]):
                try:
                    host = urlsplit(f"http://{hosts[0]}") if len(hosts) == 1 else None
                    forbidden = forbidden or host is None or not _loopback(host.hostname or "")
                    if host is not None:
                        forbidden = forbidden or bool(
                            host.username or host.password or host.path or host.query or host.fragment
                        )
                        _ = host.port
                except ValueError:
                    forbidden = True
            if forbidden:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": {"code": "cross_origin_forbidden", "message": "业务请求必须来自当前工作台页面。"}
                    },
                )
        if (
            manage_plugins
            and path.startswith("/api/")
            and not (management_path or path in {"/api/settings/environment", "/api/health"})
        ):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": "plugin_maintenance",
                        "message": (
                            "组件操作进行中，业务服务将自动恢复。"
                            if supervised_worker
                            else "当前服务处于插件维护模式；请正常重启 Web 后使用工作台。"
                        ),
                    }
                },
            )
        if management_path or manage_plugins:
            try:
                guard_request(request, manager)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        response = await call_next(request)
        if management_path or manage_plugins:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(RequestValidationError)
    async def settings_validation_error(request: Any, exc: RequestValidationError) -> Any:
        # FastAPI includes rejected inputs in its default validation response;
        # passwords and credential-bearing invalid URLs must never be echoed.
        if request.url.path in {"/api/workbench/ai/config", "/api/workbench/ai/test"}:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "invalid_ai_settings",
                        "message": "AI 设置字段无效；Base URL 必须是无认证信息的 HTTP(S) 地址。",
                    }
                },
            )
        return await request_validation_exception_handler(request, exc)

    app.include_router(settings_router)
    app.include_router(plugin_router)
    if not manage_plugins:
        from sqlseed_web.api import router
        from sqlseed_web.workbench import router as workbench_router
        from sqlseed_web.workbench_ai import router as workbench_ai_router
        from sqlseed_web.workbench_data import router as workbench_data_router

        app.include_router(router)
        app.include_router(workbench_router)
        app.include_router(workbench_ai_router)
        app.include_router(workbench_data_router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", response_model=None)
    def index() -> FileResponse | HTMLResponse:
        if manage_plugins:
            marker = (
                'data-plugin-supervised-maintenance="true"' if supervised_worker else 'data-plugin-maintenance="true"'
            )
            return HTMLResponse(
                (_STATIC_DIR / "index.html")
                .read_text(encoding="utf-8")
                .replace(
                    "<html",
                    f"<html {marker}",
                    1,
                )
            )
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    """Run the dev server (``sqlseed-web`` console script)."""
    import uvicorn

    parser = argparse.ArgumentParser(description="Start the local sqlseed Web workbench.")
    parser.add_argument(
        "--manage-plugins", action="store_true", help="Start plugin maintenance only; disable database and AI APIs."
    )
    args = parser.parse_args()
    if args.manage_plugins:
        uvicorn.run(create_app(manage_plugins=True), host="127.0.0.1", port=8630, log_level="info")
    else:
        from sqlseed_web.supervisor import run_supervised

        run_supervised()
