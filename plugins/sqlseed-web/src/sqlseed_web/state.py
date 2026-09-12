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

import getpass
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlseed._utils.logger import get_logger
from sqlseed.core.orchestrator import DataOrchestrator

from sqlseed_web.sqlite_target import sqlite_target

logger = get_logger(__name__)


class ConnectionBusyError(RuntimeError):
    """A connection cannot be closed while a job or operation is using it."""


class UnknownConnectionError(KeyError):
    """A connection identifier is absent or was closed before an operation."""


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
        self._operation_owners: dict[str, int] = {}
        self._global_lock = threading.Lock()
        # In-session AI config overrides (UI 内 AI 配置面板). Empty values mean
        # "fall back to environment" — the panel lets users switch online/
        # local backends without editing env vars or restarting the server.
        self._ai_override: dict[str, str] = {}

    # ---- AI config override -------------------------------------------------

    def set_ai_override(self, values: dict[str, str | None]) -> None:
        with self._global_lock:
            self._ai_override = {k: v for k, v in (values or {}).items() if v}

    def get_ai_override(self) -> dict[str, str]:
        with self._global_lock:
            return dict(self._ai_override)

    # ---- connections ----------------------------------------------------

    def add_connection(
        self, target: str, provider: str = "mimesis", locale: str = "en_US", *, connection_id: str | None = None
    ) -> Connection:
        """Create and register a DataOrchestrator for the given target."""
        if connection_id is not None and not connection_id:
            raise ValueError("connection ID must not be empty")
        conn_id = connection_id if connection_id is not None else uuid.uuid4().hex[:12]
        # Reject unsupported SQLite identities before opening a database or
        # registering a session that grouping/admission could not identify.
        sqlite_target(target, conn_id)
        orch = DataOrchestrator(target, provider_name=provider, locale=locale)
        conn = Connection(conn_id=conn_id, target=target, provider=provider, locale=locale, orchestrator=orch)
        with self._global_lock:
            if conn_id in self._conns:
                orch.close()
                raise ValueError("connection ID is already registered")
            self._conns[conn_id] = conn
            self._conn_locks[conn_id] = threading.Lock()
        return conn

    def get_connection(self, conn_id: str) -> Connection:
        """Return a registered connection or reject an expired identifier."""
        with self._global_lock:
            if (conn := self._conns.get(conn_id)) is None:
                raise UnknownConnectionError(f"unknown connection: {conn_id}")
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
        with self._global_lock:
            connections = list(self._conns.values())
        for c in connections:
            group_key = _normalize_target(c.target, c.conn_id)
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
        """Close an idle connection atomically with respect to job creation."""
        with self._global_lock:
            if any(j.conn_id == conn_id and j.status == "running" for j in self._jobs.values()):
                raise ConnectionBusyError("当前连接有任务正在运行，请等待任务完成后再断开。")
            lock = self._conn_locks.get(conn_id)
            if lock is not None and not lock.acquire(blocking=False):
                raise ConnectionBusyError("当前连接正在处理请求，请等待完成后再断开。")
            conn = self._conns.pop(conn_id, None)
            self._conn_locks.pop(conn_id, None)
        try:
            if conn is not None:
                conn.orchestrator.close()
        finally:
            if lock is not None:
                lock.release()

    def connection_lock(self, conn_id: str) -> threading.Lock:
        """Return the serialization lock for a live connection."""
        with self._global_lock:
            return self._conn_locks[conn_id]

    @contextmanager
    def connection_operation(
        self, conn_id: str, *, job_id: str | None = None, write: bool = False
    ) -> Iterator[Connection]:
        """Admit one operation immediately; never queue interactive HTTP workers.

        A reserved background worker supplies its own job ID. Other requests
        cannot steal the gap between reservation and worker startup. Reentry
        also fails promptly instead of deadlocking the non-reentrant lock.
        """
        with self._global_lock:
            if (conn := self._conns.get(conn_id)) is None:
                raise UnknownConnectionError(f"unknown connection: {conn_id}")
            if job_id is not None:
                job = self._jobs.get(job_id)
                if job is None or job.conn_id != conn_id or job.status != "running":
                    raise UnknownConnectionError(f"unknown running job: {job_id}")
            self._check_job_admission(conn, write=write, job_id=job_id)
            lock = self._conn_locks[conn_id]
            if not lock.acquire(blocking=False):
                raise ConnectionBusyError("当前连接正在处理请求，请等待完成后重试。")
            self._operation_owners[conn_id] = threading.get_ident()
        try:
            yield conn
        finally:
            with self._global_lock:
                self._operation_owners.pop(conn_id, None)
                lock.release()

    def _check_job_admission(self, conn: Connection, *, write: bool, job_id: str | None = None) -> None:
        """Check reservations while the caller holds the short registry lock."""
        target = _write_target(conn)
        for job in self._jobs.values():
            if job.status != "running" or job.job_id == job_id:
                continue
            if job.conn_id == conn.conn_id:
                raise ConnectionBusyError("当前连接有任务正在运行，请等待完成后重试。")
            other = self._conns.get(job.conn_id)
            if write and job.kind in {"fill", "workbench"} and other and _write_target(other) & target:
                raise ConnectionBusyError("此数据库已有生成任务正在运行，请查看运行记录并等待完成。")

    # ---- jobs -----------------------------------------------------------

    def create_job(self, conn_id: str, kind: str, label: str) -> Job:
        """Reserve a live connection for a job before its worker is started."""
        with self._global_lock:
            if (conn := self._conns.get(conn_id)) is None:
                raise UnknownConnectionError(f"unknown connection: {conn_id}")
            self._check_job_admission(conn, write=kind in {"fill", "workbench"})
            if self._conn_locks[conn_id].locked() and self._operation_owners.get(conn_id) != threading.get_ident():
                raise ConnectionBusyError("当前连接正在处理请求，请等待完成后再生成。")
            job = Job(job_id=uuid.uuid4().hex[:12], conn_id=conn_id, kind=kind, label=label, started_at=time.time())
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Job:
        """Return a job to its worker; HTTP readers should use a snapshot."""
        with self._global_lock:
            if (job := self._jobs.get(job_id)) is None:
                raise KeyError(f"unknown job: {job_id}")
            return job

    def complete_job(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        rows_inserted: int = 0,
    ) -> None:
        """Publish all terminal fields together, with status assigned last."""
        with self._global_lock:
            job = self._jobs[job_id]
            if result is not None:
                job.result = result
            job.rows_inserted = rows_inserted
            job.error = error
            job.finished_at = time.time()
            job.status = "error" if error else "done"

    @contextmanager
    def job_completion(self, job_id: str) -> Iterator[None]:
        """A worker must publish a terminal state even when a programming error escapes."""
        try:
            yield
        finally:
            with self._global_lock:
                job = self._jobs[job_id]
                if job.status == "running":
                    job.error = "后台任务意外终止，请检查服务日志后重试。"
                    job.finished_at = time.time()
                    job.status = "error"

    def job_snapshot(self, job_id: str) -> Job:
        """Read terminal state and its result from the same publication."""
        with self._global_lock:
            if (job := self._jobs.get(job_id)) is None:
                raise KeyError(f"unknown job: {job_id}")
            return replace(job, result=dict(job.result))

    def recent_jobs(self, limit: int = 20) -> list[Job]:
        """Return consistent snapshots of the newest jobs first."""
        with self._global_lock:
            return [replace(job, result=dict(job.result)) for job in list(self._jobs.values())[-limit:][::-1]]


def _normalize_target(target: str, conn_id: str = "") -> str:
    """Normalize a connection target into a grouping key.

    SQLite filenames follow DBAPI URI semantics, shared memory uses its name,
    and private memory uses the registered connection id. Network grouping is
    display-only; PostgreSQL write admission separately resolves URL endpoints.
    """
    if (sqlite := sqlite_target(target, conn_id)) is not None:
        return sqlite.key
    scheme, rest = target.split("://", 1)
    if "@" in rest:
        _, hostpart = rest.rsplit("@", 1)
        rest = f"***:{hostpart}"
    return f"{scheme}://{rest}"


def _write_target(conn: Connection) -> frozenset[str]:
    """Normalize known targets without claiming DNS/proxy/service resolution.

    PostgreSQL multihost URLs reserve each possible endpoint; credentials and
    driver/SSL options do not change the write target. SQLite URI filenames
    must use DBAPI semantics, including named shared-memory databases.
    """
    if (sqlite := sqlite_target(conn.target, conn.conn_id)) is not None:
        return frozenset({sqlite.key})
    url = make_url(conn.target)
    if url.get_backend_name() == "postgresql":
        return _postgres_write_targets(url)
    return frozenset({_normalize_target(conn.target)})


def _postgres_endpoint_keys(host: str, address: str, port: str, database: str) -> set[str]:
    keys: set[str] = set()
    # Socket paths are case sensitive; DNS hostnames are not. Missing
    # host/service remains an unresolved local endpoint, never a DNS lookup.
    for endpoint in {host, address} - {""} or {"<default>"}:
        endpoint = str(Path(endpoint).resolve()) if endpoint.startswith("/") else endpoint.lower()
        keys.add(json.dumps(["postgresql", endpoint, int(port or "5432"), database]))
    return keys


def _postgres_write_targets(url: URL) -> frozenset[str]:
    """Use SQLAlchemy's libpq argument rules, including query host overrides."""
    dialect = url.set(drivername="postgresql+psycopg2").get_dialect()()
    _, options = dialect.create_connect_args(url)
    user = options.get("user") or os.environ.get("PGUSER") or getpass.getuser()
    database = options.get("dbname") or os.environ.get("PGDATABASE") or user
    hosts = str(options.get("host") or os.environ.get("PGHOST") or "").split(",")
    ports = str(options.get("port") or os.environ.get("PGPORT") or "5432").split(",")
    addresses = str(options.get("hostaddr") or os.environ.get("PGHOSTADDR") or "").split(",")
    keys: set[str] = set()
    for index in range(max(len(hosts), len(addresses))):
        host = hosts[index] if index < len(hosts) else ""
        address = addresses[index] if index < len(addresses) else ""
        port = ports[index] if index < len(ports) else ports[0]
        keys.update(_postgres_endpoint_keys(host, address, port, database))
    return frozenset(keys)


# Module-level singleton shared by all routers.
state = UIState()
