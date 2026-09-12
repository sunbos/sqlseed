"""Bounded parsing of malformed status constraints in final configuration repair."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("sqlseed_ai")


@pytest.mark.parametrize("pattern", ["condition", "null"])
def test_long_status_clause_rejection_has_bounded_runtime(pattern: str) -> None:
    program = """
import sys
import time
from sqlseed_ai.auto_heal.orchestrator import AutoHealOrchestrator
from sqlseed_ai.validator.schema_snapshot import TableMeta
word = "x" * 100_000
if sys.argv[1] == "condition":
    expression = word + "! OR finished IS NULL"
else:
    expression = word + " = 'off' AND finished IS NOT NULL OR active=1"
meta = TableMeta("items", [], {}, [{"type": "check", "expression": expression}])
orchestrator = AutoHealOrchestrator(heal_orchestrator=None, validator=None)
started = time.monotonic()
result = orchestrator._collect_status_null_triggers(meta)
if time.monotonic() - started > 2:
    raise RuntimeError("Rejecting a malformed status clause exceeded the parsing budget")
if result != {}:
    raise RuntimeError("Malformed status clause inferred an unexpected null rule")
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, pattern], capture_output=True, text=True, timeout=15, check=False
    )
    assert completed.returncode == 0, completed.stderr
