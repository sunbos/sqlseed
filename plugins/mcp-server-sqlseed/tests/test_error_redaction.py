"""Both core MCP error shapes and their stderr diagnostics hide URL credentials."""

from __future__ import annotations

import subprocess
import sys


def test_core_mcp_malformed_url_is_redacted_in_results_and_logs() -> None:
    script = """
from mcp_server_sqlseed.server import sqlseed_generate_yaml, sqlseed_execute_fill
target='sqlite://audit-user:synthetic-userinfo@host/db?password=synthetic-query'
for fn in (sqlseed_generate_yaml, sqlseed_execute_fill):
    result=fn(target, 'items')
    message=result if isinstance(result,str) else result['error']
    assert 'Invalid database URL' in message
    assert 'synthetic-userinfo' not in message and 'synthetic-query' not in message
    print(message)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=True)
    assert "Failed to generate YAML" in result.stderr
    assert "Failed to execute fill" in result.stderr
    assert "synthetic-userinfo" not in result.stdout + result.stderr
    assert "synthetic-query" not in result.stdout + result.stderr
