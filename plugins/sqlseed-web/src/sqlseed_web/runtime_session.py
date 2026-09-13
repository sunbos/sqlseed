"""Transfer live connection settings across managed workers through memory only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlseed._utils.logger import get_logger

from sqlseed_web.operation_errors import generation_errors
from sqlseed_web.sqlite_target import sqlite_target
from sqlseed_web.state import Connection, state

logger = get_logger(__name__)


def export_session() -> dict[str, Any]:
    """Snapshot an idle worker; memory databases cannot survive its replacement."""
    connections = []
    for item in state.list_connections():
        target = sqlite_target(item["target"], item["conn_id"])
        if target is not None and target.kind != "sqlite":
            raise HTTPException(
                409,
                detail={
                    "code": "plugin_session_not_restorable",
                    "message": "当前连接包含 SQLite 内存数据库，更新插件会丢失内存数据；请先保存数据并断开该连接。",
                },
            )
        connections.append({key: item[key] for key in ("conn_id", "target", "provider", "locale")})
    return {"connections": connections, "ai_override": state.get_ai_override()}


def _restore_connection(item: Any) -> None:
    """Validate and open one saved connection, unregistering unsuccessful opens."""
    conn: Connection | None = None
    opened = False
    try:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key] for key in ("target", "conn_id", "provider", "locale")
        ):
            raise ValueError("Invalid saved connection settings")
        target = sqlite_target(item["target"], item["conn_id"])
        if target is not None and (target.kind != "sqlite" or not Path(target.value).is_file()):
            raise ValueError("The original file-backed database is unavailable")
        conn = state.add_connection(
            item["target"], provider=item["provider"], locale=item["locale"], connection_id=item["conn_id"]
        )
        # Registry construction is lazy: exercise the actual opening path.
        conn.orchestrator.get_table_names()
        opened = True
    except generation_errors(conn.orchestrator if conn is not None else None, additional=(KeyError,)) as exc:
        raise ValueError("Saved connection could not be restored") from exc
    finally:
        if conn is not None and not opened:
            try:
                state.close_connection(conn.conn_id)
            except generation_errors(conn.orchestrator, additional=(KeyError,)):
                # The registry removes ownership before disposing the adapter.
                logger.warning("Restored connection adapter cleanup failed", conn_id=conn.conn_id)


def restore_session(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Reopen each target with the original ID; report sanitized partial failures."""
    restored = 0
    failures: list[dict[str, str]] = []
    items = snapshot.get("connections", [])
    if not isinstance(items, list):
        raise TypeError("Session connections must be a list")
    for item in items:
        try:
            _restore_connection(item)
        except ValueError:
            failures.append(
                {
                    "conn_id": str(item.get("conn_id", "")) if isinstance(item, dict) else "",
                    "message": "无法恢复此连接，请检查数据库可访问性并重新连接。",
                }
            )
        else:
            restored += 1
    override = snapshot.get("ai_override", {})
    valid_override = isinstance(override, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in override.items()
    )
    if valid_override:
        # Includes credential-service binding and explicit environment-key
        # suppression markers. Never write these values to settings files.
        state.set_ai_override(override)
    return {"restored_connections": restored, "failed_connections": failures, "ai_session_restored": valid_override}


def close_session() -> None:
    """Close registered idle connections after runtime admission has paused."""
    for item in state.list_connections():
        state.close_connection(item["conn_id"])
