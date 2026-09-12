"""Bounded reads of current database records, independent of generation state."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlseed._utils.paths import validate_table_name
from sqlseed._utils.sql_safe import quote_identifier
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

from sqlseed_web.state import ConnectionBusyError, UnknownConnectionError, state
from sqlseed_web.workbench_schema import _refresh_inspector, _target_identity
from sqlseed_web.workbench_store import get_store

router = APIRouter(prefix="/api/workbench", tags=["workbench-data"])


@contextmanager
def _read_errors() -> Iterator[None]:
    """Keep driver exceptions, connection credentials and record values private."""
    try:
        yield
    except HTTPException:
        raise
    except ConnectionBusyError as exc:
        raise HTTPException(
            409, detail={"code": "connection_busy", "message": "当前连接正在处理请求，请稍后重试。"}
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            404, detail={"code": "not_found", "message": "连接或运行记录已不存在，请刷新后重试。"}
        ) from exc
    except Exception as exc:
        raise HTTPException(
            422,
            detail={"code": "data_read_failed", "message": "读取数据失败，请检查连接、表结构和读取权限后重试。"},
        ) from exc


def _read_rows(
    adapter: SQLAlchemyAdapter, table: str, order_by: list[str], limit: int, offset: int
) -> list[dict[str, Any]]:
    """Use the adapter's native parameter contract and release the pooled cursor."""
    dialect = adapter.dialect.name
    placeholder = {"sqlite": "?", "postgresql": "%s"}[dialect]
    sql = f"SELECT * FROM {quote_identifier(table)}"
    if order_by:
        sql += " ORDER BY " + ", ".join(quote_identifier(column) for column in order_by)
    # PostgreSQL DBAPI format/pyformat drivers parse percent signs even inside
    # quoted names when parameters are supplied; literal percent signs double.
    if dialect == "postgresql":
        sql = sql.replace("%", "%%")
    sql += f" LIMIT {placeholder} OFFSET {placeholder}"
    with closing(adapter.execute(sql, (limit, offset))) as cursor:
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


@router.get(
    "/connections/{conn_id}/tables/{table:path}/data",
    responses={
        403: {"description": HTTPStatus(403).phrase},
        404: {"description": HTTPStatus(404).phrase},
        409: {"description": HTTPStatus(409).phrase},
        422: {"description": HTTPStatus(422).phrase},
    },
)
def table_data(
    conn_id: str,
    table: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    run_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, Any]:
    """Read a current page; a run links the target and scope, never an insert delta."""
    with _read_errors(), state.connection_operation(conn_id) as conn:
        target_key, target_label = _target_identity(conn)
        if run_id is not None:
            run = get_store().get_run(run_id)
            if run["target_key"] != target_key:
                raise HTTPException(
                    409,
                    detail={"code": "target_mismatch", "message": "当前连接与运行记录的数据库不一致，请重新选择连接。"},
                )
            if table not in {item["name"] for item in run["tables"]}:
                raise HTTPException(
                    403, detail={"code": "table_outside_run", "message": "该表不属于这条运行记录的生成范围。"}
                )
        conn.orchestrator.get_table_names()  # Ensure the existing adapter is connected.
        adapter = conn.orchestrator.database_adapter
        if not isinstance(adapter, SQLAlchemyAdapter):
            # An unsupported runtime adapter follows the existing RuntimeError API contract.
            raise RuntimeError("Data browsing requires a SQLAlchemyAdapter connection")  # noqa: TRY004
        _refresh_inspector(conn, adapter)
        names = adapter.get_table_names()
        if table not in names:
            raise HTTPException(
                404, detail={"code": "table_not_found", "message": "该表已不存在，请重新读取数据库结构。"}
            )
        validate_table_name(table, names)
        columns = [asdict(column) for column in adapter.get_column_info(table)]
        order_by = adapter.get_primary_keys(table)
        rows = _read_rows(adapter, table, order_by, limit, offset)
        total = adapter.get_row_count(table)
        result: dict[str, Any] = jsonable_encoder(
            {
                "table": table,
                "target_key": target_key,
                "target_label": target_label,
                "dialect": adapter.dialect.name,
                "columns": columns,
                "rows": rows,
                "total": total,
                "limit": limit,
                "offset": offset,
                "order_by": order_by,
                "read_at": datetime.now(timezone.utc).isoformat(),
            },
            custom_encoder={
                bytes: lambda value: "0x" + value.hex(),
                memoryview: lambda value: "0x" + value.hex(),
                Decimal: str,
                # JSON/browser numbers cannot represent these values faithfully.
                int: lambda value: str(value) if abs(value) > 2**53 - 1 else value,
                float: lambda value: str(value) if not math.isfinite(value) else value,
            },
        )
        return result


@router.get(
    "/runs/{run_id}/data-connections",
    responses={
        404: {"description": HTTPStatus(404).phrase},
        409: {"description": HTTPStatus(409).phrase},
        422: {"description": HTTPStatus(422).phrase},
    },
)
def run_data_connections(run_id: str) -> dict[str, Any]:
    """Match registered target identities without connecting or reflecting any DB."""
    with _read_errors():
        run = get_store().get_run(run_id)
        connections = []
        for item in state.list_connections():
            try:
                # Registry access takes its short lock. Identity uses immutable
                # target metadata, so a busy database remains a valid candidate.
                conn = state.get_connection(item["conn_id"])
            except UnknownConnectionError:
                continue
            target_key, target_label = _target_identity(conn)
            if target_key == run["target_key"]:
                connections.append({"conn_id": conn.conn_id, "target_label": target_label})
        return {"connections": connections, "target_key": run["target_key"], "target_label": run["target_label"]}
