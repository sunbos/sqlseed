"""Smoke-test installed Core/Web wheels without importing the source checkout.

Run in a fresh virtualenv after installing all five distributions, or Core/Web
with --without-optional-components. All data and settings are temporary; this
check never installs packages or calls an AI model.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sysconfig
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Callable


def require(condition: bool, message: str) -> None:
    """Fail the smoke check with an actionable error."""
    if not condition:
        raise RuntimeError(message)


def _wait_for_run(read_json: Callable[[str], Any], run_id: str) -> Any:
    """Poll a single run using its encoded identifier and a bounded deadline."""
    path = f"/api/workbench/runs/{quote(run_id, safe='')}"
    deadline = time.monotonic() + 15
    while True:
        run = read_json(path)
        if run["status"] not in {"queued", "running"}:
            return run
        require(time.monotonic() < deadline, "Workbench generation did not finish")
        time.sleep(0.02)


def main() -> None:
    """Verify installed data generation and an isolated HTTP worker."""
    import sqlseed_web
    from sqlseed_web.supervisor import Supervisor

    import sqlseed

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-optional-components", action="store_true")
    options = parser.parse_args()
    installed_root = Path(sysconfig.get_path("purelib")).resolve()
    for module in (sqlseed, sqlseed_web):
        require(
            Path(module.__file__).resolve().is_relative_to(installed_root),
            f"{module.__name__} must be imported from an installed wheel, not an editable checkout",
        )

    with tempfile.TemporaryDirectory(prefix="sqlseed-wheel-smoke-") as directory:
        root = Path(directory)
        os.environ["SQLSEED_WEB_WORKSPACE_PATH"] = str(root / "workspace.sqlite3")
        os.environ["SQLSEED_WEB_SETTINGS_PATH"] = str(root / "settings.json")
        database = root / "sample.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            connection.execute("CREATE TABLE web_users(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        result = sqlseed.fill(str(database), table="users", count=5, provider="base", skip_ai=True)
        require(result.count == 5 and not result.errors, f"Wheel generation failed: {result}")
        with closing(sqlite3.connect(database)) as connection:
            original_rows = connection.execute("SELECT id, name FROM users ORDER BY id").fetchall()

        supervisor = Supervisor(port=0)
        try:
            supervisor.start()
            base = f"http://127.0.0.1:{supervisor.port}"

            def request(path: str, payload: dict[str, Any] | None = None, origin: str | None = None):
                data = json.dumps(payload).encode() if payload is not None else None
                headers = {"Content-Type": "application/json"} if data else {}
                if origin:
                    headers["Origin"] = origin
                return urlopen(Request(base + path, data=data, headers=headers), timeout=15)

            with request("/") as response:
                require(response.headers["X-Frame-Options"] == "DENY", "Missing framing protection")
                require("sqlseed" in response.read().decode(), "Missing application page")
            with request("/static/js/app.js") as response:
                require(response.status == 200 and len(response.read()) > 500, "Missing Web assets")
            with request("/api/connections", {"db_path": str(database), "provider": "base"}, base) as response:
                require(response.status == 200, "Same-origin connection failed")
                conn_id = json.load(response)["conn_id"]
            try:
                with request("/api/connections", origin="https://untrusted.example"):
                    raise RuntimeError("Cross-origin request was accepted")
            except HTTPError as exc:
                require(exc.code == 403, f"Unexpected cross-origin status: {exc.code}")
            with request("/api/settings/environment") as response:
                environment = json.load(response)
            components = {package["id"]: package["status"] for package in environment["packages"]}
            require(
                all(components.get(component) == "available" for component in ("core", "web")),
                f"An installed component failed to load: {components}",
            )
            optional_status = "not_installed" if options.without_optional_components else "available"
            require(
                all(components.get(component) == optional_status for component in ("ai", "cli", "mcp")),
                f"Unexpected optional component state: {components}",
            )
            with request("/api/workbench/ai/config") as response:
                ai = json.load(response)
                require(
                    ai["available"] is (not options.without_optional_components), "AI capability state is incorrect"
                )

            def read_json(path: str, payload: dict[str, Any] | None = None) -> Any:
                with request(path, payload, base) as response:
                    return json.load(response)

            schema = read_json(f"/api/workbench/connections/{quote(conn_id, safe='')}/schema")
            draft = read_json(
                "/api/workbench/drafts",
                {
                    "conn_id": conn_id,
                    "name": "Installed wheel workbench check",
                    "schema_hash": schema["schema_hash"],
                    "document": {"provider": "base", "tables": [{"name": "web_users", "count": 5}]},
                },
            )
            inputs = {
                "conn_id": conn_id,
                "schema_hash": draft["schema_hash"],
                "document": draft["document"],
                "count": 3,
            }
            checked = read_json("/api/workbench/check", inputs)
            preview = read_json("/api/workbench/preview", inputs)
            require(checked["ok"] and preview["ok"], f"Workbench validation failed: {checked}, {preview}")
            require(len(preview["samples"]["web_users"]) == 3, "Workbench preview returned the wrong row count")
            with closing(sqlite3.connect(database)) as connection:
                require(connection.execute("SELECT count(*) FROM web_users").fetchone()[0] == 0, "Preview wrote data")
            started = read_json(
                "/api/workbench/runs",
                {
                    "conn_id": conn_id,
                    "draft_id": draft["id"],
                    "revision": draft["revision"],
                    "schema_hash": draft["schema_hash"],
                    "config_hash": checked["config_hash"],
                },
            )
            run = _wait_for_run(read_json, started["id"])
            require(run["status"] == "done" and run["rows_inserted"] == 5, f"Workbench generation failed: {run}")
            with closing(sqlite3.connect(database)) as connection:
                count = connection.execute("SELECT count(*) FROM users").fetchone()[0]
                require(count == 5, "Reading the workbench changed generated data")
                require(
                    connection.execute("SELECT id, name FROM users ORDER BY id").fetchall() == original_rows,
                    "Workbench operations changed the existing Core-generated rows",
                )
                web_count = connection.execute("SELECT count(*) FROM web_users").fetchone()[0]
                require(web_count == 5, "Workbench generation did not persist the expected rows")
            print(
                json.dumps(
                    {
                        "wheel_imports": True,
                        "rows": count,
                        "web_rows": web_count,
                        "web": "ready",
                        "components": components,
                    }
                )
            )
        finally:
            supervisor.stop()


if __name__ == "__main__":
    main()
