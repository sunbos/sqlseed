"""Fixed responses cross real parsing, merging and contract validation."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
import yaml
from openai.types.chat import ChatCompletion

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("sqlseed_ai")

from sqlseed_ai.config import AIConfig
from sqlseed_ai.contracts.builtin_violations import BUILTIN_VIOLATIONS
from sqlseed_ai.contracts.matrix import ContractResolver
from sqlseed_ai.healer.models import SubgraphTask
from sqlseed_ai.runtime import build_heal_orchestrator
from sqlseed_ai.validator.main import FastValidator
from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot


class FixedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def chat_completions_create(self, *, model: str, **kwargs: object) -> ChatCompletion:
        self.calls += 1
        return ChatCompletion.model_validate(
            {
                "id": "fixed",
                "created": 0,
                "model": model,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": next(self.responses),
                        },
                    }
                ],
            }
        )


@pytest.fixture
def pipeline(tmp_path: Path):
    path = tmp_path / "candidates.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items(value INTEGER NOT NULL, label TEXT)")
    snapshot = SchemaSnapshot(db_path=str(path))
    validator = FastValidator(ContractResolver(set(BUILTIN_VIOLATIONS), set()), db_path=str(path))
    config = {
        "provider": "faker",
        "tables": [
            {
                "name": "items",
                "count": 2,
                "columns": [
                    {"name": "value", "generator": "string"},
                    {"name": "label", "generator": "choice", "params": {"choices": ["keep"]}},
                ],
            }
        ],
    }
    violations = validator.validate(config, snapshot).violations
    assert violations
    return snapshot, validator, config, violations


@pytest.mark.parametrize("level", [1, 2, 3])
@pytest.mark.parametrize(
    "patch",
    [
        None,
        {"name": "value", "generator": "unknown_model_generator"},
        {"name": "value", "generator": "integer", "params": {"min_value": "oops"}},
        {"name": "value", "generator": "integer", "params": {"invented": 4}},
    ],
)
def test_invalid_model_candidate_degrades_without_accepting_or_crashing(pipeline, level: int, patch: object) -> None:
    snapshot, validator, config, violations = pipeline
    payload = patch if level == 2 else {"tables": None if patch is None else [{"name": "items", "columns": [patch]}]}
    prefix = {1: [], 2: [""], 3: ["not JSON"]}[level]
    client = FixedClient([*prefix, json.dumps(payload), json.dumps(payload)])
    healer = build_heal_orchestrator(AIConfig(model="fixed"), client, snapshot, validator, max_retries=1)
    result = healer.heal(SubgraphTask(task_id="items", tables=["items"]), violations, config)
    assert not result.success
    assert result.level_used == 4
    assert client.calls >= level - 1
    value, label = result.config["tables"][0]["columns"]
    assert value.get("generator") not in {"unknown_model_generator", "integer"}
    assert "oops" not in str(value.get("params", {}))
    assert label == config["tables"][0]["columns"][1]
    assert config["tables"][0]["columns"][0] == {"name": "value", "generator": "string"}


@pytest.mark.parametrize(
    "label",
    [
        {"name": "label", "generator": "string", "faker_method": "lexify", "native_params": {"text": "??"}},
        {"name": "label", "derive_from": "value", "expression": "str(value)"},
        {
            "name": "label",
            "generator": "choice",
            "params": {"choices": ["one", "two"]},
            "constraints": {"unique": True},
        },
    ],
)
def test_valid_candidate_preserves_native_derived_and_constraints(pipeline, label: dict) -> None:
    from pathlib import Path

    from sqlseed import fill_from_config

    snapshot, validator, config, violations = pipeline
    patch = {
        "tables": [
            {
                "name": "items",
                "columns": [
                    {"name": "value", "generator": "integer", "params": {"min_value": 7, "max_value": 7}},
                    label,
                ],
            }
        ]
    }
    client = FixedClient([json.dumps(patch)])
    healer = build_heal_orchestrator(AIConfig(model="fixed"), client, snapshot, validator, max_retries=1)
    result = healer.heal(SubgraphTask(task_id="items", tables=["items"]), violations, config)
    assert result.success
    assert result.level_used == 1
    assert result.config["tables"][0]["columns"] == patch["tables"][0]["columns"]
    assert validator.validate(result.config, snapshot).is_clean
    output = Path(snapshot.db_path).with_suffix(".yaml")
    output.write_text(yaml.safe_dump({"db_path": snapshot.db_path, **result.config}))
    written = fill_from_config(output)
    assert written[0].errors == [] and written[0].count == 2
    with sqlite3.connect(snapshot.db_path) as db:
        rows = db.execute("SELECT value, label FROM items").fetchall()
    assert [row[0] for row in rows] == [7, 7]
    if label.get("derive_from"):
        assert [row[1] for row in rows] == ["7", "7"]
    elif label.get("faker_method"):
        assert all(len(row[1]) == 2 for row in rows)
    else:
        assert {row[1] for row in rows} == {"one", "two"}
