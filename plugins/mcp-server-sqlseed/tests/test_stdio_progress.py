"""Core progress output must not leak into the MCP stdio protocol stream."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from mcp_server_sqlseed.server import mcp

if TYPE_CHECKING:
    from pathlib import Path


def test_execute_fill_does_not_write_progress_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("rich")
    db_path = tmp_path / "mcp.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE items (value INTEGER)")

    result = asyncio.run(
        mcp.call_tool("sqlseed_execute_fill", {"db_path": str(db_path), "table_name": "items", "count": 3})
    )

    assert capsys.readouterr().out == ""
    # FastMCP versions may return content alone or (content, structured_content).
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    assert payload["count"] == 3
    assert payload["errors"] == []
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
