"""FastAPI application factory and server entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlseed._utils.logger import get_logger

from sqlseed_ui.api import router

logger = get_logger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Build the sqlseed-ui application (API + static frontend)."""
    app = FastAPI(
        title="sqlseed-ui",
        version="0.1.0",
        description="Web workbench and acceptance cockpit for the sqlseed test-data toolkit.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    """Run the dev server (``sqlseed-ui`` console script)."""
    import uvicorn

    uvicorn.run(
        "sqlseed_ui.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8630,
        log_level="info",
    )
