"""Shared SQLite target identity using the adapter's actual DBAPI URI semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import url2pathname

from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.engine import Dialect
from sqlseed.database._connection_url import connection_url


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
            return f"SQLite 共享内存：{self.value}"
        return "SQLite :memory:"


def _sqlite_uri_parts(filename: str) -> tuple[str, dict[str, list[str]]]:
    """Decode URI components only after rejecting SQLite/Python parsing ambiguities."""
    # urlsplit strips these raw controls, whereas SQLite retains them.
    # Require percent encoding rather than identifying a different file.
    if any(control in filename for control in "\t\r\n"):
        raise ValueError("SQLite URI 含原始控制字符；请对文件名中的 TAB、CR、LF 使用百分号编码")
    uri = urlsplit(filename)
    try:
        filename = unquote(uri.path, errors="strict")
        query = parse_qs(uri.query, keep_blank_values=True, errors="strict")
    except UnicodeDecodeError as exc:
        # Replacement decoding would collapse distinct byte filenames.
        raise ValueError("SQLite URI 使用了无效 UTF-8 编码；请使用有效 UTF-8 文件名和参数") from exc
    # SQLite truncates URI strings at decoded NUL; Python does not. An
    # apparent file target can otherwise become a memory database or VFS.
    if "\x00" in filename or any("\x00" in text for key, values in query.items() for text in (key, *values)):
        raise ValueError("SQLite URI 不支持 NUL 字符；请检查路径和查询参数中的百分号编码")
    if "vfs" in query:
        raise ValueError("Web 暂不支持 SQLite 自定义 VFS；请使用默认 VFS 的文件或内存连接")
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
    return SQLiteTarget("sqlite", str(Path(filename).resolve()))


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
        raise ValueError("数据库文件不存在或不是普通文件；请选择已有的 SQLite 数据库文件。")
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
