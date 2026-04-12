from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    api_key: str | None = None
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
