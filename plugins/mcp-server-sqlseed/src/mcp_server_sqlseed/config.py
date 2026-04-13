from __future__ import annotations

from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    db_path: str | None = None
    host: str = "localhost"
    port: int = 8000
