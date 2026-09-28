"""Keep browser diagnostics separate from credential-bearing runtime targets."""

from __future__ import annotations

import re
from urllib.parse import unquote

from sqlalchemy.exc import StatementError
from sqlseed._utils.redaction import redact_url_credentials
from sqlseed.database._connection_url import connection_url

CREDENTIAL_KEY_PATTERN = r"password|passwd|pwd|secret|token|credential|key|passfile"


def _redact_query_credentials(message: str) -> str:
    """Consume each query field once, including incomplete keys containing '?'."""
    field_pattern = re.compile(r"[?&][^=&\s]*=?")
    # SQLAlchemy accepts whitespace and quote characters in query secrets;
    # treating those as diagnostic separators would reveal part of a value.
    value_pattern = re.compile(r"[^&]+")
    parts: list[str] = []
    cursor = copied = 0
    while field := field_pattern.search(message, cursor):
        cursor = field.end()
        key = field.group()
        if not key.endswith("=") or not re.search(CREDENTIAL_KEY_PATTERN, unquote(key), re.IGNORECASE):
            continue
        if (value := value_pattern.match(message, cursor)) is not None:
            parts.extend((message[copied:cursor], "***"))
            cursor = copied = value.end()
    return "".join(parts) + message[copied:]


def public_error(exc: Exception) -> str:
    """Avoid exposing connection credentials or SQLAlchemy parameter dumps."""
    from sqlseed_web.messages import Message, key_error_message

    if len(exc.args) == 1 and isinstance(exc.args[0], Message):
        annotated = key_error_message(exc.args[0]) if isinstance(exc, KeyError) else exc.args[0]
        if len(annotated) <= 2000:
            return annotated
    message = str(exc.orig) if isinstance(exc, StatementError) and exc.orig is not None else str(exc)
    message = message.split("\n[SQL:", 1)[0].split("\n[parameters:", 1)[0]
    message = redact_url_credentials(message).replace("://***:***@", "://***@")
    return _redact_query_credentials(message)[:2000]


def public_target(target: str) -> str:
    """Serialize a known whole target for display, never for reconnecting.

    Parse the whole URL so quoted or spaced query credentials are removed in
    full. Bare SQLite paths remain literal. Runtime and IPC retain the original.
    """
    if "://" not in target:
        return target
    url = connection_url(target)
    secret_keys = [key for key in url.query if re.search(CREDENTIAL_KEY_PATTERN, unquote(key), re.IGNORECASE)]
    if url.username is None and url.password is None and not secret_keys:
        return target
    return url._replace(username=None, password=None).difference_update_query(secret_keys).render_as_string()
