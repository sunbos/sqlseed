"""Redact URL credentials in diagnostics without changing connection targets."""

from __future__ import annotations

import re
from urllib.parse import unquote

_URL_START = re.compile(r"(?<![a-zA-Z0-9+.-])[a-zA-Z][a-zA-Z0-9+.-]*://")
# SQLAlchemy accepts raw '/', '?', '#', and spaces inside passwords. Only
# '@' terminates the password; restricting this to RFC authority characters
# would expose credentials from targets the database layer actually accepts.
_AUTHORITY_HEAD = re.compile(r"[^:/@]*[:/@]")
_QUERY_KEY = re.compile(r"[?&]([^=?&#\s]+)=")
_SECRET_KEYS = frozenset({"password", "passwd", "pwd", "sslpassword", "secret", "token", "api_key", "access_token"})


def redact_url_credentials(message: str, *, whole_url: bool = False) -> str:
    """Keep hosts, paths and diagnostics while hiding URL userinfo and secrets.

    Matching text instead of parsing one URL also handles malformed targets and
    multiple URLs embedded in an exception. Percent-encoded credential values
    remain opaque; encoded query parameter names are recognized as well.
    Query values may contain raw whitespace, quotes and '#', so only an '&'
    terminates a credential value. Ambiguous free text is redacted conservatively:
    a scheme inside a password must not expose the part before that scheme.
    ``whole_url`` identifies known target fields and is retained for callers.
    """
    starts = list(_URL_START.finditer(message))
    ats = [match.start() for match in re.finditer("@", message)]
    at_index = 0
    pieces = []
    previous = 0
    for scheme in starts:
        if scheme.start() < previous:
            continue
        pieces.append(message[previous : scheme.end()])
        previous = scheme.end()
        head = _AUTHORITY_HEAD.match(message, previous)
        if head is None or head[0].endswith("/"):
            continue
        while at_index < len(ats) and ats[at_index] < head.end() - 1:
            at_index += 1
        if at_index < len(ats):
            pieces.append("***:***@")
            previous = ats[at_index] + 1
    pieces.append(message[previous:])
    message = "".join(pieces)

    pieces = []
    previous = 0
    for key in _QUERY_KEY.finditer(message):
        if key.start() < previous or unquote(key[1]).casefold() not in _SECRET_KEYS:
            continue
        pieces.append(message[previous : key.end()])
        pieces.append("***")
        end = message.find("&", key.end())
        previous = end if end >= 0 else len(message)
    pieces.append(message[previous:])
    return "".join(pieces)
