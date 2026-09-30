"""Keep browser diagnostics separate from credential-bearing runtime targets."""

from __future__ import annotations

import re
from urllib.parse import unquote

from sqlalchemy.exc import StatementError
from sqlseed.database._connection_url import connection_url

from sqlseed_web._diagnostic_text import CREDENTIAL_KEY_PATTERN, diagnostic_text
from sqlseed_web.messages import Message, key_error_message


def public_error(exc: Exception) -> str:
    """Avoid exposing connection credentials or SQLAlchemy parameter dumps."""
    if len(exc.args) == 1 and isinstance(exc.args[0], Message):
        annotated = key_error_message(exc.args[0]) if isinstance(exc, KeyError) else exc.args[0]
        if len(annotated) <= 2000:
            return annotated
    message = str(exc.orig) if isinstance(exc, StatementError) and exc.orig is not None else str(exc)
    return diagnostic_text(message)


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
