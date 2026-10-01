"""Shared response handling for real HTTP protocol test servers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler


def send_json_response(handler: BaseHTTPRequestHandler, payload: object) -> None:
    """Send a complete JSON response over the fixture's real HTTP connection."""
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def quiet_http_log(_handler: BaseHTTPRequestHandler, *args: object, **kwargs: object) -> None:
    """Keep HTTP fixture access logs out of captured protocol output."""
