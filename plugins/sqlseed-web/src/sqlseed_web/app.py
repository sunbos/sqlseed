"""Public ASGI factory and console entry point for the Web workbench."""

from __future__ import annotations

import argparse

from sqlseed_web._application import create_app

__all__ = ["create_app", "main"]


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
