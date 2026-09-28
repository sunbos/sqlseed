"""Smoke-test installed Core/Web wheels without importing the source checkout.

Run in a fresh virtualenv after installing all five distributions, or Core/Web
with --without-optional-components. All data and settings are temporary; this
check never installs packages or calls an AI model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sysconfig
import tempfile
import time
from contextlib import closing
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Callable


CHECK_PATH = "/api/workbench/check"


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


def _check_language_assets(request: Callable[..., Any], package: Path) -> int:
    """Fetch installed language assets through HTTP and validate both catalogs."""
    static = package / "static"
    resources = sorted(path for path in (static / "js" / "i18n").rglob("*") if path.suffix in {".js", ".json"})
    require(bool(resources), "The installed wheel is missing UI language modules")
    language_root = (static / "js" / "i18n").resolve()
    for module in (static / "js").rglob("*.js"):
        source = module.read_text(encoding="utf-8")
        imports = re.findall(r"(?:from\s+|import\s+)[\"']([^\"']+)[\"']", source)
        imports += re.findall(r"new URL\([\"']([^\"']+)[\"'],\s*import\.meta\.url\)", source)
        for imported in imports:
            target = (module.parent / imported).resolve()
            if target.is_relative_to(language_root):
                require(target.is_file(), f"Missing imported UI language module: {imported}")
    files = [static / "js" / "i18n.js", *resources, static / "i18n" / "backend-messages.json"]
    for asset in files:
        require(asset.is_file(), f"Missing language resource: {asset.relative_to(static)}")
        route = "/static/" + asset.relative_to(static).as_posix()
        with request(route) as response:
            require(response.read() == asset.read_bytes(), f"Installed HTTP language resource differs: {route}")
            require(response.headers["Cache-Control"] == "no-cache", f"Language resource is not revalidated: {route}")
    backend = json.loads(files[-1].read_text(encoding="utf-8"))
    require(
        isinstance(backend, dict)
        and bool(backend)
        and all(
            key.startswith("backend.")
            and isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(text, str) and text for text in pair)
            for key, pair in backend.items()
        ),
        "The installed backend catalog must contain Chinese and English messages",
    )
    return len(files)


def _check_language_contract(request: Callable[..., Any], schema: dict[str, Any], conn_id: str, origin: str) -> None:
    """UI language must not change database facts, configuration or API diagnostics."""
    with request(f"/api/workbench/connections/{quote(conn_id, safe='')}/schema", language="en") as response:
        require(json.load(response) == schema, "UI language changed the database schema or its hash")
    empty_plan = {
        "conn_id": conn_id,
        "schema_hash": schema["schema_hash"],
        "document": {"provider": "base", "locale": "zh_CN", "tables": []},
    }
    with request(CHECK_PATH, empty_plan, origin, "en") as response:
        english_check = json.load(response)
    with request(CHECK_PATH, empty_plan, origin, "zh-CN") as response:
        chinese_check = json.load(response)
    require(english_check == chinese_check, "UI language changed the generation configuration or check hash")
    issue = english_check["issues"][0]
    with request("/static/i18n/backend-messages.json") as response:
        backend_catalog = json.load(response)
    pair = backend_catalog[issue["message_key"]]
    rendered = [template.format_map(issue["message_params"]) for template in pair]
    require(rendered[0] == issue["message"] and rendered[0] != rendered[1], "Issue lost its bilingual descriptor")


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
    require(sqlseed_web.__version__ == version("sqlseed-web"), "Web version differs from installed metadata")

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

            def request(
                path: str,
                payload: dict[str, Any] | None = None,
                origin: str | None = None,
                language: str | None = None,
            ):
                data = json.dumps(payload).encode() if payload is not None else None
                headers = {"Content-Type": "application/json"} if data else {}
                if origin:
                    headers["Origin"] = origin
                if language:
                    headers["Accept-Language"] = language
                return urlopen(Request(base + path, data=data, headers=headers), timeout=15)

            with request("/") as response:
                require(response.headers["X-Frame-Options"] == "DENY", "Missing framing protection")
                require("sqlseed" in response.read().decode(), "Missing application page")
            with request("/static/js/app.js") as response:
                require(response.status == 200 and len(response.read()) > 500, "Missing Web assets")
            language_assets = _check_language_assets(request, Path(sqlseed_web.__file__).parent)
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
            _check_language_contract(request, schema, conn_id, base)
            draft = read_json(
                "/api/workbench/drafts",
                {
                    "conn_id": conn_id,
                    "name": "Installed wheel workbench check",
                    "schema_hash": schema["schema_hash"],
                    "document": {"provider": "base", "locale": "zh_CN", "tables": [{"name": "web_users", "count": 5}]},
                },
            )
            require(draft["document"]["locale"] == "zh_CN", "UI language changed the data generation locale")
            inputs = {
                "conn_id": conn_id,
                "schema_hash": draft["schema_hash"],
                "document": draft["document"],
                "count": 3,
            }
            checked = read_json(CHECK_PATH, inputs)
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
                        "language_assets": language_assets,
                        "bilingual_issue": True,
                        "language_preserves_config": True,
                    }
                )
            )
        finally:
            supervisor.stop()


if __name__ == "__main__":
    main()
