from __future__ import annotations

from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    db_path: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
