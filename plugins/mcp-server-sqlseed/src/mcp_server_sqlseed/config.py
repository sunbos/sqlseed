"""Configuration model for the MCP server."""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class MCPServerConfig(BaseModel):
    """Configuration for the MCP server instance."""

    # Reserved for future use; server.py currently uses host/port only
    db_path: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate that the port is in the valid TCP range (1-65535)."""
        if not 1 <= v <= 65535:
            raise ValueError(f"port must be 1-65535, got {v}")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate that the host is non-empty after stripping whitespace."""
        if not v.strip():
            raise ValueError("host must be non-empty")
        return v
