"""AI MCP must reserve stdout for JSON-RPC throughout a real agent fill."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import TYPE_CHECKING

import pytest

from tests.sqlite_helpers import sqlite_connection

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("sqlseed_ai")
pytest.importorskip("mcp")


class _FixedCompletionHandler(BaseHTTPRequestHandler):
    """Serve only a deterministic LLM response; schema and fill remain real."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        config = {
            "name": "items",
            "columns": [{"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}}],
        }
        body = json.dumps(
            {
                "id": "stdio-regression",
                "object": "chat.completion",
                "created": 0,
                "model": "stdio-test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(config)},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object, **kwargs: object) -> None:
        """Keep the test HTTP server silent."""


async def _exercise_stdio(db_path: Path, env: dict[str, str]) -> str:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from sqlseed_ai.mcp import main; main()",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_task = asyncio.create_task(process.stderr.read())

    async def exchange(request: dict[str, object]) -> dict[str, object]:
        process.stdin.write((json.dumps(request) + "\n").encode())
        await process.stdin.drain()
        line = await asyncio.wait_for(process.stdout.readline(), timeout=20)
        assert line.lstrip().startswith(b"{"), f"Non-protocol stdout: {line!r}"
        response = json.loads(line)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == request["id"]
        return response

    try:
        initialized = await exchange(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-regression", "version": "1"},
                },
            }
        )
        assert initialized["result"]["serverInfo"]["name"] == "sqlseed-ai"
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')

        for request_id, target in ((2, "invalid_path_no_extension"), (3, str(db_path))):
            response = await exchange(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": "sqlseed_gemma4_agent_fill",
                        "arguments": {"db_path": target, "table_name": "items", "count": 3, "max_retries": 0},
                    },
                }
            )
            tool_result = response["result"]
            assert not tool_result.get("isError", False)
            payload = json.loads(tool_result["content"][0]["text"])
            if request_id == 2:
                assert "Invalid database target" in payload["error"]
            else:
                assert payload["count"] == 3
                assert payload["errors"] == []
                assert payload["table_name"] == "items"
                assert payload["ai_config"]["columns"][0]["params"] == {"min_value": 7, "max_value": 7}
        process.stdin.close()
        await asyncio.wait_for(process.wait(), timeout=10)
        assert process.returncode == 0
        assert await process.stdout.read() == b""
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        stderr = (await stderr_task).decode()
    return stderr


def test_agent_fill_reserves_stdio_for_protocol(tmp_path: Path) -> None:
    """Real MCP requests insert the suggested values with all logging on stderr."""
    pytest.importorskip("rich")
    db_path = tmp_path / "mcp.db"
    with sqlite_connection(db_path) as connection:
        connection.execute("CREATE TABLE items (value INTEGER NOT NULL CHECK (value = 7))")

    with ThreadingHTTPServer(("127.0.0.1", 0), _FixedCompletionHandler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR", "PYTHONPATH", "LANG", "LC_ALL", "TMPDIR"}
        }
        env.update(
            SQLSEED_AI_BACKEND="openai_compat",
            SQLSEED_AI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
            SQLSEED_AI_API_KEY="stdio-test-key",
            SQLSEED_AI_MODEL="stdio-test-model",
            SQLSEED_AI_TOOL_CALLING_PROTOCOL="none",
            SQLSEED_CACHE_DIR=str(tmp_path / "cache"),
            SQLSEED_LOG_LEVEL="DEBUG",
            NO_PROXY="127.0.0.1",
        )
        try:
            stderr = asyncio.run(_exercise_stdio(db_path, env))
        finally:
            server.shutdown()
            thread.join(timeout=5)

    assert "Agent fill failed" in stderr
    assert "Creating OpenAI client" in stderr
    assert "Agent fill completed" in stderr
    with sqlite_connection(db_path) as connection:
        assert connection.execute("SELECT value FROM items").fetchall() == [(7,), (7,), (7,)]
