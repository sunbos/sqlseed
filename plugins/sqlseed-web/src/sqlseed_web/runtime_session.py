"""Transfer live connection settings across managed workers through memory only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from sqlseed_web.sqlite_target import sqlite_target
from sqlseed_web.state import Connection, state


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


def restore_session(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Reopen each target with the original ID; report sanitized partial failures."""
    restored = 0
    failures: list[dict[str, str]] = []
    for item in snapshot.get("connections", []):
        conn: Connection | None = None
        try:
            target = sqlite_target(item["target"], item["conn_id"])
            if target is not None and (target.kind != "sqlite" or not Path(target.value).is_file()):
                raise ValueError("The original file-backed database is unavailable")
            conn = state.add_connection(
                item["target"], provider=item["provider"], locale=item["locale"], connection_id=item["conn_id"]
            )
            # The registry constructor is lazy. Exercise the same opening path
            # as POST /connections before reporting a successfully restored ID.
            conn.orchestrator.get_table_names()
            restored += 1
        except Exception:  # noqa: BLE001
            # One driver failure must not prevent restoring the remaining connections.
            if conn is not None:
                try:
                    state.close_connection(conn.conn_id)
                except Exception:  # noqa: BLE001, S110
                    # Best-effort cleanup; the sanitized connection failure is reported below.
                    pass
            failures.append(
                {
                    "conn_id": str(item.get("conn_id", "")),
                    "message": "无法恢复此连接，请检查数据库可访问性并重新连接。",
                }
            )
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
