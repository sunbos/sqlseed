"""Shared workbench requests and parent-child plans exercised through real APIs."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from sqlseed_web import workbench_ai


def generator_suggestion(table: str, column: str, generator: str, **params: Any) -> dict[str, Any]:
    return {"table": table, "column": column, "generator": generator, "params": params}


def suggestion_response(
    client: TestClient,
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    suggestions: list[dict[str, Any]],
    *,
    messages: list[Any] | None = None,
) -> httpx.Response:
    def reply(prompt: Any, **kwargs: Any) -> dict[str, Any]:
        if messages is not None:
            messages.extend(prompt)
        return {"suggestions": suggestions}

    monkeypatch.setattr(workbench_ai, "_call_model", reply)
    response = client.post("/api/workbench/ai/suggest", json=payload)
    assert response.status_code == 200, response.text
    return response


def parent_child_document(provider: str, *, child_batch_size: int | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "locale": "zh_CN",
        "optimize_pragma": False,
        "tables": [
            {
                "name": "children",
                "count": 4,
                **({"batch_size": child_batch_size} if child_batch_size is not None else {}),
                "seed": 0,
                "columns": [
                    {"name": "amount", "generator": "integer", "params": {"min_value": 7, "max_value": 7}},
                    {"name": "doubled", "derive_from": "amount", "expression": "value * 2"},
                ],
            },
            {"name": "parents", "count": 3, "columns": [{"name": "code", "generator": "uuid"}]},
        ],
    }
