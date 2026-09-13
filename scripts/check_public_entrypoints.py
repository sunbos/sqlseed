"""Verify installed five-package metadata and real CLI/MCP executable behavior."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sqlite3
import subprocess
import sysconfig
import tempfile
from contextlib import AsyncExitStack, asynccontextmanager, closing
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


CLI_COMMANDS = {"fill", "preview", "inspect", "init", "replay", "ai-suggest", "ai-analyze", "auto-heal"}


def require(ok: bool, message: str) -> None:
    """Fail on broken installed behavior instead of reporting a partial success."""
    if not ok:
        raise RuntimeError(message)


def count_rows(database: Path, table: str) -> int:
    """Read the row count from the actual temporary database."""
    from sqlseed._utils.sql_safe import quote_identifier

    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0]


def console_path(name: str) -> str:
    """Resolve a console executable inside the current Python environment."""
    filename = f"{name}.exe" if os.name == "nt" else name
    return str(Path(sysconfig.get_path("scripts")) / filename)


def child_environment(root: Path) -> dict[str, str]:
    """Keep subprocesses independent of checkout paths and real AI credentials."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SQLSEED_AI_")
        and key not in {"GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "PYTHONPATH"}
    }
    environment["SQLSEED_CACHE_DIR"] = str(root / "cache")
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def check_cli(database: Path, root: Path) -> None:
    """Exercise packaged console entry points and inspect real persisted rows."""
    commands = [
        ["--help"],
        ["fill", str(database), "-t", "cli_rows", "-n", "7", "--provider", "base", "--no-ai"],
        ["preview", str(database), "-t", "cli_rows", "-n", "3", "--provider", "base"],
        ["inspect", str(database), "-t", "cli_rows", "--show-mapping"],
    ]
    environment = child_environment(root)
    for arguments in commands:
        # This checks the installed executable wrapper, beyond CLI unit tests.
        result = subprocess.run(
            [console_path("sqlseed"), *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(result.returncode == 0, f"CLI {arguments} failed: {result.stdout}\n{result.stderr}")
        if arguments == ["--help"]:
            require(
                all(command in result.stdout for command in CLI_COMMANDS), "CLI help is missing base or AI commands"
            )
        else:
            require(count_rows(database, "cli_rows") == 7, "CLI fill/preview persisted an incorrect row count")
            require(count_rows(database, "mcp_rows") == 0, "CLI touched an unrelated table")


@asynccontextmanager
async def mcp_session(command: str, environment: dict[str, str]) -> AsyncIterator[ClientSession]:
    """Initialize a real stdio MCP session and release its process on every exit."""
    async with AsyncExitStack() as stack:
        streams = await stack.enter_async_context(stdio_client(StdioServerParameters(command=command, env=environment)))
        session = await stack.enter_async_context(ClientSession(*streams))
        await session.initialize()
        yield session


async def check_core_tools(session: ClientSession, database: Path) -> None:
    """Generate YAML and fill five rows over the core MCP protocol."""
    names = {item.name for item in (await session.list_tools()).tools}
    require(names == {"sqlseed_generate_yaml", "sqlseed_execute_fill"}, f"Wrong core MCP tools: {names}")
    generated = await session.call_tool("sqlseed_generate_yaml", {"db_path": str(database), "table_name": "mcp_rows"})
    require(not generated.isError, f"YAML tool failed: {generated}")
    yaml_config = "\n".join(item.text for item in generated.content if item.type == "text")
    document = yaml.safe_load(yaml_config)
    require(
        isinstance(document, dict) and any(table.get("name") == "mcp_rows" for table in document.get("tables", [])),
        "MCP did not generate a YAML configuration for the requested table",
    )
    result = await session.call_tool(
        "sqlseed_execute_fill",
        {"db_path": str(database), "table_name": "mcp_rows", "count": 5, "yaml_config": yaml_config},
    )
    require(not result.isError, f"MCP protocol execution failed: {result}")
    if (value := result.structuredContent) is None:
        value = json.loads(next(item.text for item in result.content if item.type == "text"))
    require(
        isinstance(value, dict) and value.get("count") == 5 and not value.get("errors") and "error" not in value,
        f"Wrong MCP result: {value}",
    )
    require(count_rows(database, "mcp_rows") == 5, "MCP did not write five real rows")
    require(count_rows(database, "cli_rows") == 7, "MCP modified unrelated table")


async def check_mcp(database: Path, root: Path) -> None:
    """Exercise installed MCP executables without making model requests."""
    environment = child_environment(root)
    async with mcp_session(console_path("mcp-server-sqlseed"), environment) as session:
        await check_core_tools(session, database)
    async with mcp_session(console_path("mcp-server-sqlseed-ai"), environment) as session:
        names = {item.name for item in (await session.list_tools()).tools}
        expected = {
            "sqlseed_ai_generate_yaml",
            "sqlseed_gemma4_analyze",
            "sqlseed_gemma4_agent_fill",
            "sqlseed_list_gemma_models",
        }
        require(names == expected, f"Wrong AI MCP tools: {names}")


def check_installed_versions(expected_version: str) -> None:
    """Reject mixed versions or modules loaded from a source checkout."""
    modules = {
        "sqlseed": "sqlseed",
        "sqlseed-cli": "sqlseed_cli",
        "sqlseed-ai": "sqlseed_ai",
        "mcp-server-sqlseed": "mcp_server_sqlseed",
        "sqlseed-web": "sqlseed_web",
    }
    purelib = Path(sysconfig.get_path("purelib")).resolve()
    for distribution, module_name in modules.items():
        require(metadata.version(distribution) == expected_version, f"Wrong installed version: {distribution}")
        module = importlib.import_module(module_name)
        require(Path(module.__file__).resolve().is_relative_to(purelib), f"Imported checkout: {module_name}")
    require(
        not any(ep.group == "console_scripts" for ep in metadata.distribution("sqlseed").entry_points),
        "Core still owns CLI script",
    )


def main() -> None:
    """Verify installed versions, CLI SQLite behavior and both MCP entry points."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Expected version of every installed sqlseed distribution")
    expected_version = parser.parse_args().version
    for key in tuple(os.environ):
        if key.startswith("SQLSEED_AI_") or key in {"GOOGLE_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"}:
            os.environ.pop(key)
    check_installed_versions(expected_version)
    from sqlseed._utils.sql_safe import quote_identifier

    with tempfile.TemporaryDirectory(prefix="sqlseed-pypi-entrypoints-") as directory:
        root = Path(directory)
        database = root / "entrypoints.db"
        os.environ["SQLSEED_CACHE_DIR"] = str(root / "cache")
        with closing(sqlite3.connect(database)) as connection:
            for table in ("cli_rows", "mcp_rows"):
                connection.execute(
                    f"CREATE TABLE {quote_identifier(table)}(id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
        check_cli(database, root)
        asyncio.run(asyncio.wait_for(check_mcp(database, root), timeout=60))
    print(
        json.dumps(
            {
                "five_packages": expected_version,
                "site_packages_only": True,
                "cli_sqlite_rows": 7,
                "mcp_sqlite_rows": 5,
                "ai_mcp_discovery": "passed",
                "real_llm_inference": "not_run",
            }
        )
    )


if __name__ == "__main__":
    main()
