"""Local SQLite storage for credential-free drafts and immutable run snapshots.

Connections belong to one short operation, so HTTP and background worker threads
never share a SQLite connection. WAL and immediate write transactions coordinate
independent store instances as well as threads. Constructing a store is the
server-start recovery boundary; application code should use ``get_store()``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlseed_web.workbench_execution import normalize_execution

_SELECT_DRAFT = "SELECT payload FROM workspace_drafts WHERE id = ?"

if TYPE_CHECKING:
    from collections.abc import Iterator

_SCHEMA_VERSION = 1
_MAX_RECORD_BYTES = 2 * 1024 * 1024
_MAX_TABLES = 1000
_RUN_STATUSES = frozenset({"queued", "running", "done", "success", "error", "cancelled", "interrupted", "skipped"})
_RUN_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "tables",
        "progress",
        "rows_inserted",
        "error",
        "started_at",
        "finished_at",
        "row_counts_exact",
        "current_table",
        "result",
        "errors",
        "elapsed",
        "batch_count",
    }
)
_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+")
_PASSWORD_KEYS = frozenset({"password", "passwd", "pwd", "sslpassword"})
_STORES: dict[Path, WorkspaceStore] = {}
_STORE_LOCK = threading.Lock()


class RevisionConflictError(ValueError):
    """A draft changed since the caller's expected revision was read."""


RevisionConflict = RevisionConflictError


def _json_text(value: dict[str, Any]) -> str:
    """Encode a bounded JSON snapshot, rejecting non-finite or non-JSON data."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Workspace payload must contain valid JSON values") from exc
    if len(encoded.encode("utf-8")) > _MAX_RECORD_BYTES:
        raise ValueError("Workspace payload exceeds the 2 MiB size limit")
    pending: list[Any] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            _check_target(item)
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return encoded


def _decode(value: str) -> dict[str, Any]:
    """Read a JSON object from a workspace record."""
    result: dict[str, Any] = json.loads(value)
    if not isinstance(result, dict):
        # Corrupt persisted records use RuntimeError under the runtime validation contract.
        raise RuntimeError("Invalid workspace record: expected a JSON object")  # noqa: TRY004
    return result


def _text(payload: dict[str, Any], key: str, limit: int = 512) -> str:
    """Require a nonempty bounded string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{key} must be a nonempty string of at most {limit} characters")
    return value


def _check_target(value: str) -> None:
    """Reject credentials in display labels and target identity strings."""
    for match in _URL_PATTERN.finditer(value):
        try:
            parsed = urlsplit(match.group())
            password = unquote(parsed.password or "")
            query_passwords = [item for key, item in parse_qsl(parsed.query) if key.lower() in _PASSWORD_KEYS]
        except ValueError as exc:
            raise ValueError("Invalid target label; use a credential-free label") from exc
        if any(secret and set(secret) != {"*"} for secret in (password, *query_passwords)):
            raise ValueError("Connection passwords must be removed from workspace payloads")


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the common immutable, credential-free configuration snapshot."""
    document = payload.get("document")
    if not isinstance(document, dict):
        # Payload validation uses ValueError, which the HTTP boundary handles consistently.
        raise ValueError("document must be a configuration object")  # noqa: TRY004
    if {"db_path", "url"}.intersection(document):
        raise ValueError("Remove connection fields db_path and url from the stored document")
    target_key = _text(payload, "target_key", 4096)
    target_label = _text(payload, "target_label", 4096)
    _check_target(target_key)
    _check_target(target_label)
    return {
        "target_key": target_key,
        "target_label": target_label,
        "document": document,
        "schema_hash": _text(payload, "schema_hash"),
    }


def _validate_run_table(table: Any) -> str:
    if not isinstance(table, dict):
        # Payload validation uses ValueError, which the HTTP boundary handles consistently.
        raise ValueError("Each run table must be an object")  # noqa: TRY004
    count = table.get("count", table.get("requested_count"))
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("Run table count must be a nonnegative integer")
    table_status = table.get("status", "queued")
    if not isinstance(table_status, str) or table_status not in _RUN_STATUSES | {"not_run"}:
        raise ValueError("Unknown run table status")
    return _text(table, "name")


def _validate_run(record: dict[str, Any]) -> None:
    """Validate bounded run status and table progress before persistence."""
    status = record.get("status")
    if not isinstance(status, str) or status not in _RUN_STATUSES:
        raise ValueError("Unknown run status")
    tables = record.get("tables")
    if not isinstance(tables, list) or len(tables) > _MAX_TABLES:
        raise ValueError(f"tables must be a list of at most {_MAX_TABLES} entries")
    names: set[str] = set()
    for table in tables:
        if (name := _validate_run_table(table)) in names:
            raise ValueError("Run table names must be unique")
        names.add(name)
    for progress in (record, *tables):
        inserted = progress.get("rows_inserted", 0)
        if inserted is not None and (isinstance(inserted, bool) or not isinstance(inserted, int) or inserted < 0):
            raise ValueError("rows_inserted must be a nonnegative integer or null")


def _set_run_identity(record: dict[str, Any], payload: dict[str, Any]) -> None:
    """Validate immutable run identifiers and timestamps independently of progress."""
    run_id = payload.get("id", str(uuid.uuid4()))
    _text({"id": run_id}, "id", 128)
    revision = payload.get("revision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1):
        raise ValueError("revision must be a positive integer or null")
    if (draft_id := payload.get("draft_id")) is not None:
        _text({"draft_id": draft_id}, "draft_id", 128)
    created_at = payload.get("created_at", time.time())
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)) or created_at < 0:
        raise ValueError("created_at must be a nonnegative timestamp")
    record.update(id=run_id, draft_id=draft_id, revision=revision, created_at=created_at)


def _run_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate execution and metadata before a run enters the store transaction."""
    record = _snapshot(payload)
    record["execution"] = normalize_execution(payload.get("execution"))
    plan_hash = payload.get("plan_hash", "")
    if not isinstance(plan_hash, str) or (plan_hash and not re.fullmatch(r"[a-f0-9]{64}", plan_hash)):
        raise ValueError("plan_hash must be a SHA-256 digest or empty")
    if record["execution"]["mode"] == "replace_selected" and not plan_hash:
        raise ValueError("replacement execution requires an immutable plan_hash")
    record["plan_hash"] = plan_hash
    _set_run_identity(record, payload)
    for key in ("name", "config_hash"):
        if key in payload:
            record[key] = _text(payload, key)
    if "order" in payload:
        order = payload["order"]
        if not isinstance(order, list) or len(order) > _MAX_TABLES or any(not isinstance(name, str) for name in order):
            raise ValueError("order must be a bounded list of table names")
        record["order"] = order
    record.update(status="queued", tables=[], rows_inserted=0, error=None, started_at=None, finished_at=None)
    record.update({key: value for key, value in payload.items() if key in _RUN_MUTABLE_FIELDS})
    _validate_run(record)
    return record


class WorkspaceStore:
    """Persist Web workspace metadata at ``path`` without opening user databases."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        """Open one connection, optionally starting a serialized write transaction."""
        db = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        """Create versioned tables and recover records left by an earlier server."""
        with self._connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
        with self._connection(write=True) as db:
            if (version := db.execute("PRAGMA user_version").fetchone()[0]) not in (0, _SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported workspace schema version {version}; expected {_SCHEMA_VERSION}")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workspace_drafts ("
                "id TEXT PRIMARY KEY, revision INTEGER NOT NULL, target_key TEXT NOT NULL, "
                "updated_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS workspace_drafts_target ON workspace_drafts(target_key, updated_at)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workspace_runs ("
                "id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS workspace_runs_created ON workspace_runs(created_at)")
            db.execute("PRAGMA user_version = 1")
            unfinished = db.execute("SELECT payload FROM workspace_runs WHERE status IN ('queued', 'running')")
            for row in unfinished.fetchall():
                record = _decode(row[0])
                record.update(
                    status="interrupted",
                    finished_at=time.time(),
                    row_counts_exact=False,
                    error="Service restarted before completion; recorded inserted row counts may be incomplete.",
                )
                for table in record["tables"]:
                    if table.get("status", "queued") in {"queued", "running"}:
                        table["status"] = "interrupted"
                db.execute(
                    "UPDATE workspace_runs SET status = ?, payload = ? WHERE id = ?",
                    ("interrupted", _json_text(record), record["id"]),
                )

    def save_draft(
        self,
        payload: dict[str, Any],
        *,
        draft_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Create a draft or atomically replace the caller's expected revision."""
        record = {**_snapshot(payload), "name": _text(payload, "name")}
        view_state = payload.get("view_state", {})
        if not isinstance(view_state, dict):
            # Payload validation uses ValueError, which the HTTP boundary handles consistently.
            raise ValueError("view_state must be an object")  # noqa: TRY004
        record["view_state"] = view_state
        with self._connection(write=True) as db:
            revision = 1
            if draft_id is not None:
                old = db.execute("SELECT revision FROM workspace_drafts WHERE id = ?", (draft_id,)).fetchone()
                if old is None:
                    raise KeyError(draft_id)
                if isinstance(expected_revision, bool) or expected_revision != old[0]:
                    raise RevisionConflict(f"Draft revision conflict: expected {expected_revision}, current {old[0]}")
                revision = old[0] + 1
            elif expected_revision is not None:
                raise ValueError("expected_revision is only valid when updating an existing draft")
            record.update(id=draft_id or str(uuid.uuid4()), revision=revision, updated_at=time.time())
            encoded = _json_text(record)
            if draft_id is None:
                db.execute(
                    "INSERT INTO workspace_drafts (id, revision, target_key, updated_at, payload) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (record["id"], revision, record["target_key"], record["updated_at"], encoded),
                )
            else:
                db.execute(
                    "UPDATE workspace_drafts SET revision = ?, target_key = ?, updated_at = ?, payload = ? "
                    "WHERE id = ?",
                    (revision, record["target_key"], record["updated_at"], encoded, draft_id),
                )
        return _decode(encoded)

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        """Return a detached draft snapshot, raising KeyError for an unknown id."""
        with self._connection() as db:
            row = db.execute(_SELECT_DRAFT, (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return _decode(row[0])

    def list_drafts(self, target_key: str | None = None) -> list[dict[str, Any]]:
        """List newest drafts first, optionally filtering by stable target identity."""
        with self._connection() as db:
            rows = db.execute(
                "SELECT payload FROM workspace_drafts WHERE (? IS NULL OR target_key = ?) "
                "ORDER BY updated_at DESC, rowid DESC",
                (target_key, target_key),
            ).fetchall()
        return [_decode(row[0]) for row in rows]

    @staticmethod
    def _draft_at_revision(db: sqlite3.Connection, draft_id: str, expected_revision: int) -> dict[str, Any]:
        """Read the displayed draft inside its caller's serialized write transaction."""
        if (row := db.execute(_SELECT_DRAFT, (draft_id,)).fetchone()) is None:
            raise KeyError(draft_id)
        record = _decode(row[0])
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision != record["revision"]
        ):
            raise RevisionConflict("配置已被更新，请刷新列表后重试")
        return record

    def rename_draft(self, draft_id: str, name: str, *, expected_revision: int) -> dict[str, Any]:
        """Rename metadata without rewriting the saved document or requiring its target."""
        clean_name = _text({"name": name}, "name", 200).strip()
        with self._connection(write=True) as db:
            record = self._draft_at_revision(db, draft_id, expected_revision)
            record.update(name=clean_name, revision=record["revision"] + 1, updated_at=time.time())
            encoded = _json_text(record)
            db.execute(
                "UPDATE workspace_drafts SET revision = ?, updated_at = ?, payload = ? WHERE id = ?",
                (record["revision"], record["updated_at"], encoded, draft_id),
            )
        return _decode(encoded)

    def copy_draft(self, draft_id: str, name: str, *, expected_revision: int) -> dict[str, Any]:
        """Copy the exact reviewed revision into a new independent configuration."""
        clean_name = _text({"name": name}, "name", 200).strip()
        with self._connection(write=True) as db:
            record = self._draft_at_revision(db, draft_id, expected_revision)
            record.update(id=str(uuid.uuid4()), name=clean_name, revision=1, updated_at=time.time())
            encoded = _json_text(record)
            db.execute(
                "INSERT INTO workspace_drafts (id, revision, target_key, updated_at, payload) VALUES (?, ?, ?, ?, ?)",
                (record["id"], 1, record["target_key"], record["updated_at"], encoded),
            )
        return _decode(encoded)

    def delete_draft(self, draft_id: str, *, expected_revision: int) -> dict[str, Any]:
        """Remove one current configuration; accepted runs retain their independent snapshots."""
        with self._connection(write=True) as db:
            record = self._draft_at_revision(db, draft_id, expected_revision)
            db.execute("DELETE FROM workspace_drafts WHERE id = ?", (draft_id,))
        return {"id": draft_id, "revision": record["revision"], "deleted": True}

    def create_run(self, payload: dict[str, Any], *, require_current_draft: bool = False) -> dict[str, Any]:
        """Create a unique run containing its complete, immutable configuration."""
        record = _run_snapshot(payload)
        run_id, draft_id, created_at = record["id"], record["draft_id"], record["created_at"]
        encoded = _json_text(record)
        try:
            with self._connection(write=True) as db:
                if require_current_draft:
                    if (row := db.execute(_SELECT_DRAFT, (draft_id,)).fetchone()) is None:
                        raise KeyError(draft_id)
                    draft = _decode(row[0])
                    snapshot_fields = ("revision", "document", "schema_hash", "target_key")
                    if any(draft[key] != record[key] for key in snapshot_fields):
                        raise RevisionConflictError("Draft changed while validating the run; save and check it again")
                db.execute(
                    "INSERT INTO workspace_runs (id, status, created_at, payload) VALUES (?, ?, ?, ?)",
                    (run_id, record["status"], created_at, encoded),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Run already exists: {run_id}") from exc
        return _decode(encoded)

    def update_run(self, run_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Atomically change run progress while preserving the original snapshot."""
        if set(changes).difference(_RUN_MUTABLE_FIELDS):
            raise ValueError("Cannot update immutable run snapshot fields")
        with self._connection(write=True) as db:
            if (row := db.execute("SELECT payload FROM workspace_runs WHERE id = ?", (run_id,)).fetchone()) is None:
                raise KeyError(run_id)
            record = _decode(row[0])
            original_tables = [
                (table["name"], table.get("count", table.get("requested_count"))) for table in record["tables"]
            ]
            record.update(changes)
            _validate_run(record)
            updated_tables = [
                (table["name"], table.get("count", table.get("requested_count"))) for table in record["tables"]
            ]
            if updated_tables != original_tables:
                raise ValueError("Cannot change immutable run table names or counts")
            encoded = _json_text(record)
            db.execute(
                "UPDATE workspace_runs SET status = ?, payload = ? WHERE id = ?",
                (record["status"], encoded, run_id),
            )
        return _decode(encoded)

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return a detached run snapshot, raising KeyError for an unknown id."""
        with self._connection() as db:
            row = db.execute("SELECT payload FROM workspace_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _decode(row[0])

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List the latest runs with a bounded result count."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 500:
            raise ValueError("limit must be an integer between 0 and 500")
        with self._connection() as db:
            rows = db.execute(
                "SELECT payload FROM workspace_runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_decode(row[0]) for row in rows]


def _default_path() -> Path:
    """Choose user application storage without relying on the working directory."""
    if sys.platform == "darwin":
        directory = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        directory = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return directory / "sqlseed" / "workspace.sqlite3"


def get_store() -> WorkspaceStore:
    """Lazily initialize and reuse one store per configured workspace path."""
    configured = os.environ.get("SQLSEED_WEB_WORKSPACE_PATH")
    path = (Path(configured) if configured else _default_path()).expanduser().resolve()
    with _STORE_LOCK:
        if path not in _STORES:
            _STORES[path] = WorkspaceStore(path)
        return _STORES[path]
