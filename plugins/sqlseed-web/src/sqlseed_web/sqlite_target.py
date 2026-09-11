"""Shared SQLite target identity using the adapter's actual DBAPI URI semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote, unquote, urlsplit
from urllib.request import url2pathname

from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.engine import Dialect, make_url


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


def sqlite_target(target: str, conn_id: str) -> SQLiteTarget | None:
    """Resolve only SQLite; do not confuse URI options with ordinary filenames.

    The core adapter wraps non-URL strings in ``sqlite:///`` too. SQLAlchemy
    separates sqlite3 options (uri, timeout, etc.) from SQLite filename options;
    interpreting ``url.database`` alone therefore describes the wrong target.
    Memory names are literal SQLite names, not filesystem paths. Private memory
    and temporary databases must remain scoped to the registered connection.
    """
    url = make_url(target if "://" in target else f"sqlite:///{target}")
    if url.get_backend_name() != "sqlite":
        return None
    dialect: Dialect = SQLiteDialect_pysqlite()
    args, options = dialect.create_connect_args(url)
    filename = str(args[0])
    if filename in {"", ":memory:"}:
        return SQLiteTarget("sqlite-memory", conn_id)
    if options.get("uri") and filename.startswith("file:"):
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
