"""Shared SQLite target identity using the adapter's actual DBAPI URI semantics."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import url2pathname

from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.engine import Dialect
from sqlseed.database._connection_url import connection_url

from sqlseed_web.messages import message as tr


@cache
def _macos_libc() -> ctypes.CDLL:
    """Bind Darwin realpath once with its native pointer signature."""
    library = ctypes.CDLL(None, use_errno=True)
    library.realpath.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char)]
    library.realpath.restype = ctypes.c_void_p
    return library


def _canonical_file_path(filename: str) -> str:
    """Resolve macOS filesystem spellings without folding distinct filenames."""
    path = Path(filename).resolve()
    if sys.platform != "darwin":
        return str(path)
    # Unlike Python's realpath, Darwin libc reads each component's actual
    # filesystem name. It neither scans directories nor opens the database;
    # closing an extra database descriptor would release active POSIX locks.
    # Darwin sys/syslimits.h defines PATH_MAX=1024. Passing our own buffer
    # avoids libc-allocated memory and retains ownership on every error path.
    buffer = ctypes.create_string_buffer(1024)
    if _macos_libc().realpath(os.fsencode(path), buffer):
        return os.fsdecode(buffer.value)
    if (error := ctypes.get_errno()) in {errno.ENOENT, errno.ENOTDIR}:
        # Identity lookup must not create a missing database; existing callers
        # retain their own create/no-create policy when opening it later.
        return str(path)
    # realpath's partial output on failure is not a valid target identity.
    raise OSError(error, os.strerror(error), str(path))


@dataclass(frozen=True)
class SQLiteTarget:
    """A file, a named shared memory database, or one private connection."""

    kind: Literal["sqlite", "sqlite-memory", "sqlite-shared-memory"]
    value: str

    @property
    def key(self) -> str:
        """Retain existing admission keys while sharing their interpretation."""
        return self.value if self.kind == "sqlite" else f"{self.kind}:{self.value}"

    @property
    def label(self) -> str:
        if self.kind == "sqlite":
            return self.value
        if self.kind == "sqlite-shared-memory":
            return tr("backend.sqlite_target.sqlite_shared_memory", p1=self.value)
        return "SQLite :memory:"


def _sqlite_uri_parts(filename: str) -> tuple[str, dict[str, list[str]]]:
    """Decode URI components only after rejecting SQLite/Python parsing ambiguities."""
    # urlsplit strips these raw controls, whereas SQLite retains them.
    # Require percent encoding rather than identifying a different file.
    if any(control in filename for control in "\t\r\n"):
        raise ValueError(tr("backend.sqlite_target.sqlite_uri_contains_raw_control_characters_percent"))
    uri = urlsplit(filename)
    try:
        filename = unquote(uri.path, errors="strict")
        query = parse_qs(uri.query, keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as exc:
        # Replacement decoding would collapse distinct byte filenames.
        raise ValueError(tr("backend.sqlite_target.sqlite_uri_contains_invalid_utf_8_encoding")) from exc
    # SQLite truncates URI strings at decoded NUL; Python does not. An
    # apparent file target can otherwise become a memory database or VFS.
    if "\x00" in filename or any("\x00" in text for key, values in query.items() for text in (key, *values)):
        raise ValueError(tr("backend.sqlite_target.sqlite_uri_does_not_support_nul_characters"))
    if "vfs" in query:
        raise ValueError(tr("backend.sqlite_target.web_does_not_support_custom_sqlite_vfs"))
    return filename, query


def sqlite_target(target: str, conn_id: str) -> SQLiteTarget | None:
    """Resolve only SQLite; do not confuse URI options with ordinary filenames.

    The core adapter uses the same literal-path/SQLite URL parser. SQLAlchemy
    separates sqlite3 options (uri, timeout, etc.) from SQLite filename options;
    interpreting ``url.database`` alone therefore describes the wrong target.
    Memory names are literal SQLite names, not filesystem paths. Private memory
    and temporary databases must remain scoped to the registered connection.
    """
    url = connection_url(target)
    if url.get_backend_name() != "sqlite":
        return None
    dialect: Dialect = SQLiteDialect_pysqlite()
    args, options = dialect.create_connect_args(url)
    if (filename := str(args[0])) in {"", ":memory:"}:
        return SQLiteTarget("sqlite-memory", conn_id)
    if options.get("uri") and filename.startswith("file:"):
        filename, query = _sqlite_uri_parts(filename)
        if not filename:
            return SQLiteTarget("sqlite-memory", conn_id)
        if filename == ":memory:" or query.get("mode") == ["memory"]:
            if query.get("cache") == ["shared"]:
                return SQLiteTarget("sqlite-shared-memory", filename)
            return SQLiteTarget("sqlite-memory", conn_id)
        # Convert URI drive syntax (/C:/...) to a native Windows filename.
        # Re-encode the validated text so literal percent sequences are not
        # decoded twice by url2pathname; keep drive colons visible to it.
        filename = url2pathname(quote(filename, safe="/:"))
    return SQLiteTarget("sqlite", _canonical_file_path(filename))


def existing_sqlite_connection_target(target: str, conn_id: str) -> str:
    """Open a selected SQLite file without creating it if it disappears.

    Keep the caller's target for identity and display; this URI is only the
    orchestrator's connection transport. Non-file targets retain their existing
    semantics, and explicit SQLite read-only options must stay read-only.
    """
    resolved = sqlite_target(target, conn_id)
    if resolved is None or resolved.kind != "sqlite":
        return target
    path = Path(resolved.value)
    if not path.is_file():
        raise ValueError(tr("backend.sqlite_target.the_database_file_does_not_exist_or"))
    url = connection_url(target)
    dialect: Dialect = SQLiteDialect_pysqlite()
    _, options = dialect.create_connect_args(url)
    # Unknown query arguments on a non-URI SQLite URL were previously ignored;
    # do not activate them merely because we now need SQLite's no-create mode.
    query = (
        dict(url.query) if options.get("uri") else {key: value for key, value in url.query.items() if key in options}
    )
    query["uri"] = "true"
    if "mode" not in query or query["mode"] == "rwc":
        query["mode"] = "rw"
    # URL.render_as_string percent-encodes database names on SQLAlchemy 2.1,
    # while the shared adapter parser deliberately preserves SQLite URI text.
    # Encode the filename once with as_uri(), then only serialize its options.
    return f"{url.drivername}:///{path.as_uri()}?{urlencode(query, doseq=True)}"
