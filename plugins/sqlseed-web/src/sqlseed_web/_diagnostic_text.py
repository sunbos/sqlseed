"""Redact plain diagnostic text without depending on message presentation."""

from __future__ import annotations

import re
from urllib.parse import unquote

from sqlseed._utils.redaction import redact_url_credentials

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


def diagnostic_text(message: str) -> str:
    """Bound and redact credentials and SQL parameter dumps in plain text."""
    message = message.split("\n[SQL:", 1)[0].split("\n[parameters:", 1)[0]
    message = redact_url_credentials(message).replace("://***:***@", "://***@")
    return _redact_query_credentials(message)[:2000]
