"""HTTP contracts for the persistent, offline generation workbench."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from sqlseed_web.state import ConnectionBusyError, state
from sqlseed_web.workbench_runtime import (
    WorkbenchError,
    check_document,
    export_document,
    normalize_document,
    parse_document,
    plan_execution,
    public_error,
    start_run,
)
from sqlseed_web.workbench_schema import _target_identity, generator_catalog, inspect_connection
from sqlseed_web.workbench_store import RevisionConflict, get_store

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conn_id: str
    document: dict[str, Any]


class DraftRequest(DocumentRequest):
    name: str = Field(min_length=1, max_length=200)
    schema_hash: str
    view_state: dict[str, Any] = Field(default_factory=dict)


class DraftUpdateRequest(DraftRequest):
    revision: int = Field(ge=1)


class DraftNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    name: str = Field(min_length=1, max_length=200)


class CheckRequest(DocumentRequest):
    schema_hash: str
    count: int = Field(default=3, ge=1, le=100)


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conn_id: str
    text: str = Field(max_length=2 * 1024 * 1024)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conn_id: str
    draft_id: str
    revision: int = Field(ge=1)
    schema_hash: str
    config_hash: str
    execution: dict[str, Any] | None = None
    plan_hash: str = Field(default="", max_length=128)


@contextmanager
def _request_errors() -> Iterator[None]:
    try:
        yield
    except HTTPException:
        raise
    except WorkbenchError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": public_error(exc)}) from exc
    except ConnectionBusyError as exc:
        raise HTTPException(409, detail={"code": "connection_busy", "message": public_error(exc)}) from exc
    except RevisionConflict as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": public_error(exc)}) from exc
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "not_found", "message": public_error(exc)}) from exc
    except Exception as exc:
        raise HTTPException(422, detail={"code": "request_failed", "message": public_error(exc)}) from exc


@router.get("/connections/{conn_id}/schema")
def connection_schema(conn_id: str) -> dict[str, Any]:
    with _request_errors(), state.connection_operation(conn_id) as conn:
        return inspect_connection(conn)


@router.get("/generators")
def generators() -> dict[str, Any]:
    with _request_errors():
        return generator_catalog()


@router.get("/drafts")
def list_drafts(conn_id: str | None = None) -> list[dict[str, Any]]:
    with _request_errors():
        target_key = None
        if conn_id:
            # Filtering saved metadata needs only connection identity, not a
            # live schema scan or the orchestrator's generation lock.
            conn = state.get_connection(conn_id)
            target_key, _ = _target_identity(conn)
        return get_store().list_drafts(target_key=target_key)


def _save_draft(body: DraftRequest, draft_id: str | None = None, revision: int | None = None) -> dict[str, Any]:
    with _request_errors(), state.connection_operation(body.conn_id) as conn:
        schema = inspect_connection(conn)
        if schema["schema_hash"] != body.schema_hash:
            raise WorkbenchError("schema 已变化，请刷新后保存", code="schema_changed", status=409)
        return get_store().save_draft(
            {
                "name": body.name.strip(),
                "document": normalize_document(conn, body.document),
                "schema_hash": body.schema_hash,
                "view_state": body.view_state,
                "target_key": schema["target_key"],
                "target_label": schema["target_label"],
            },
            draft_id=draft_id,
            expected_revision=revision,
        )


@router.post("/drafts")
def create_draft(body: DraftRequest) -> dict[str, Any]:
    return _save_draft(body)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    with _request_errors():
        return get_store().get_draft(draft_id)


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: str, body: DraftUpdateRequest) -> dict[str, Any]:
    return _save_draft(body, draft_id, body.revision)


@router.patch("/drafts/{draft_id}")
def rename_draft(draft_id: str, body: DraftNameRequest) -> dict[str, Any]:
    with _request_errors():
        return get_store().rename_draft(draft_id, body.name, expected_revision=body.revision)


@router.post("/drafts/{draft_id}/copy")
def copy_draft(draft_id: str, body: DraftNameRequest) -> dict[str, Any]:
    with _request_errors():
        return get_store().copy_draft(draft_id, body.name, expected_revision=body.revision)


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str, revision: int = Query(ge=1)) -> dict[str, Any]:
    with _request_errors():
        return get_store().delete_draft(draft_id, expected_revision=revision)


@router.get("/drafts/{draft_id}/export")
def export_draft(draft_id: str) -> dict[str, Any]:
    """Export the saved document without reopening a business database."""
    with _request_errors():
        record = get_store().get_draft(draft_id)
        return {
            "id": record["id"],
            "name": record["name"],
            "revision": record["revision"],
            "json": record["document"],
            "yaml": yaml.safe_dump(record["document"], sort_keys=False, allow_unicode=True),
        }


@router.post("/parse")
def parse(body: ParseRequest) -> dict[str, Any]:
    with _request_errors(), state.connection_operation(body.conn_id) as conn:
        return {"document": parse_document(conn, body.text)}


@router.post("/export")
def export(body: DocumentRequest) -> dict[str, Any]:
    with _request_errors(), state.connection_operation(body.conn_id) as conn:
        return export_document(conn, body.document)


def _check(body: CheckRequest, *, include_preview: bool) -> dict[str, Any]:
    with _request_errors(), state.connection_operation(body.conn_id) as conn:
        result = check_document(conn, body.document, body.schema_hash, count=body.count, preview=include_preview)
        encoded: dict[str, Any] = jsonable_encoder(result, custom_encoder={bytes: lambda value: value.hex()})
        return encoded


@router.post("/check")
def check(body: CheckRequest) -> dict[str, Any]:
    return _check(body, include_preview=False)


@router.post("/preview")
def preview(body: CheckRequest) -> dict[str, Any]:
    return _check(body, include_preview=True)


@router.post("/execution-plan")
def execution_plan(body: RunRequest) -> dict[str, Any]:
    with _request_errors():
        return plan_execution(
            body.conn_id,
            body.draft_id,
            body.revision,
            body.schema_hash,
            body.config_hash,
            execution=body.execution,
            registry=state,
            store=get_store(),
        )


@router.post("/runs", status_code=202)
def create_run(body: RunRequest) -> dict[str, Any]:
    with _request_errors():
        return start_run(
            body.conn_id,
            body.draft_id,
            body.revision,
            body.schema_hash,
            body.config_hash,
            execution=body.execution,
            plan_hash=body.plan_hash,
            registry=state,
            store=get_store(),
        )


@router.get("/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    with _request_errors():
        return get_store().list_runs(limit=limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with _request_errors():
        return get_store().get_run(run_id)
