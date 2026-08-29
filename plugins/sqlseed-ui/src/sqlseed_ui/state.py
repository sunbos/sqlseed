"""In-memory state: connection registry and background job tracker.

The UI backend is intentionally stateful: each opened database holds one
long-lived ``DataOrchestrator`` (lazy-connected), and fills run as
background jobs so the HTTP layer never blocks on large generations.

Thread-safety model:
- One global lock guards the connection/job dicts (short critical sections).
- One per-connection lock serializes fills: a single DataOrchestrator is
  not safe for concurrent ``fill_table`` calls (shared PRAGMA state,
  shared pool, SQLite single-writer).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed.core.orchestrator import DataOrchestrator

logger = get_logger(__name__)


@dataclass
class Job:
    """A background job (fill or auto-heal) tracked for the UI."""

    job_id: str
    conn_id: str
    kind: str  # "fill" | "auto_heal"
    label: str
    status: str = "running"  # running | done | error
    started_at: float = 0.0
    finished_at: float = 0.0
    rows_before: int = 0
    rows_inserted: int = 0
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Connection:
    """A registered database connection with its orchestrator."""

    conn_id: str
    target: str  # SQLite file path or SQLAlchemy URL
    provider: str
    locale: str
    orchestrator: DataOrchestrator


class UIState:
    """Registry of connections and jobs for the lifetime of the server."""

    def __init__(self) -> None:
        self._conns: dict[str, Connection] = {}
        self._jobs: dict[str, Job] = {}
        self._conn_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    # ---- connections ----------------------------------------------------

    def add_connection(self, target: str, provider: str = "mimesis", locale: str = "en_US") -> Connection:
        """Create and register a DataOrchestrator for the given target."""
        conn_id = uuid.uuid4().hex[:12]
        orch = DataOrchestrator(target, provider_name=provider, locale=locale)
        conn = Connection(conn_id=conn_id, target=target, provider=provider, locale=locale, orchestrator=orch)
        with self._global_lock:
            self._conns[conn_id] = conn
            self._conn_locks[conn_id] = threading.Lock()
        return conn

    def get_connection(self, conn_id: str) -> Connection:
        conn = self._conns.get(conn_id)
        if conn is None:
            raise KeyError(f"unknown connection: {conn_id}")
        return conn

    def list_connections(self) -> list[dict[str, Any]]:
        """List connections with same-target grouping metadata.

        Multiple connections to the same DB file are legal (SQLite allows
        concurrent readers + serialized writers) but visually confusing.
        Each entry gets a stable ``group_key`` (normalized target) and a
        1-based ``group_index``; the frontend renders the first connection
        of a group as the primary and the rest as parallel connections.
        """
        counts: dict[str, int] = {}
        entries: list[dict[str, Any]] = []
        for c in self._conns.values():
            group_key = _normalize_target(c.target)
            counts[group_key] = counts.get(group_key, 0) + 1
            entries.append(
                {
                    "conn_id": c.conn_id,
                    "target": c.target,
                    "provider": c.provider,
                    "locale": c.locale,
                    "group_key": group_key,
                    "group_index": counts[group_key],
                }
            )
        # Annotate group size so the UI can show "1/3" style labels.
        totals: dict[str, int] = {}
        for e in entries:
            totals[e["group_key"]] = totals.get(e["group_key"], 0) + 1
        for e in entries:
            e["group_size"] = totals[e["group_key"]]
        return entries

    def close_connection(self, conn_id: str) -> None:
        with self._global_lock:
            conn = self._conns.pop(conn_id, None)
            self._conn_locks.pop(conn_id, None)
        if conn is not None:
            conn.orchestrator.close()

    def connection_lock(self, conn_id: str) -> threading.Lock:
        return self._conn_locks[conn_id]

    # ---- jobs -----------------------------------------------------------

    def create_job(self, conn_id: str, kind: str, label: str) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:12], conn_id=conn_id, kind=kind, label=label)
        with self._global_lock:
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown job: {job_id}")
        return job

    def recent_jobs(self, limit: int = 20) -> list[Job]:
        return list(self._jobs.values())[-limit:][::-1]


def _normalize_target(target: str) -> str:
    """Normalize a connection target into a grouping key.

    The same database opened as ``/abs/path.db`` vs ``sqlite:////abs/path.db``
    vs ``~/x/../abs/path.db`` is one physical file — group them together.
    Non-URL targets are resolved to absolute paths; URL targets keep the
    URL minus its password component (same DB, different credentials, is
    still the same write target for grouping purposes).
    """
    from pathlib import Path

    if "://" in target:
        scheme, rest = target.split("://", 1)
        if "@" in rest:
            creds, hostpart = rest.rsplit("@", 1)
            rest = f"***:{hostpart}"
        # A sqlite:/// URL points at a plain file — normalize to the bare
        # absolute path so it groups with connections opened by file path.
        if scheme in ("sqlite", "sqlite+pysqlite"):
            path_part = rest.split("?", 1)[0]
            try:
                return str(Path(path_part).expanduser().resolve())
            except (OSError, ValueError):
                return path_part
        return f"{scheme}://{rest}"
    try:
        return str(Path(target).expanduser().resolve())
    except (OSError, ValueError):
        return target


# Module-level singleton shared by all routers.
state = UIState()
