"""AI MCP diagnostic output must hide database credentials before any LLM call."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("sqlseed_ai")
pytest.importorskip("mcp")


def test_ai_mcp_malformed_url_is_redacted_in_results_and_logs() -> None:
    script = """
from sqlseed_ai.mcp import sqlseed_ai_generate_yaml, sqlseed_gemma4_analyze, sqlseed_gemma4_agent_fill
target='sqlite://audit-user:synthetic-userinfo@host/db?password=synthetic-query'
for fn in (sqlseed_ai_generate_yaml, sqlseed_gemma4_analyze, sqlseed_gemma4_agent_fill):
    result=fn(target, 'items')
    message=result if isinstance(result,str) else result['error']
    assert 'Invalid database URL' in message
    assert 'synthetic-userinfo' not in message and 'synthetic-query' not in message
    print(message)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30, check=True)
    assert "YAML generation error" in result.stderr
    assert "Gemma 4 analysis failed" in result.stderr
    assert "synthetic-userinfo" not in result.stdout + result.stderr
    assert "synthetic-query" not in result.stdout + result.stderr
