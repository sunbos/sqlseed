"""sqlseed-web: web UI for the sqlseed test-data generation toolkit.

A FastAPI application that wraps ``DataOrchestrator`` and the sqlseed-ai
self-healing subsystem (Layers 1-5) with an HTTP API and a dependency-free
static frontend. It serves two purposes:

1. A visual workbench (schema browsing, column-config editing, preview,
   fill execution, data viewing, YAML round-tripping).
2. An acceptance cockpit for the project itself: every core feature
   (9-level mapping, constraint solving, contract validation, repair
   strategies, auto-heal pipeline) is exposed as an observable endpoint,
   making regressions visible without writing scripts.
"""

from __future__ import annotations

__version__ = "0.1.0"


def main() -> None:
    """Console-script entry point (``sqlseed-web``)."""
    from sqlseed_web.app import main as run_server

    run_server()
