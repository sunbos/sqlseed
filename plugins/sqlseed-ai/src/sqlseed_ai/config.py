from __future__ import annotations

import os

from pydantic import BaseModel, Field


class AIConfig(BaseModel):
    api_key: str | None = None
    model: str = "gpt-4o"
    base_url: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)

    @classmethod
    def from_env(cls) -> AIConfig:
        api_key = os.environ.get("SQLSEED_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("SQLSEED_AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        model = os.environ.get("SQLSEED_AI_MODEL", "gpt-4o")
        return cls(api_key=api_key, base_url=base_url, model=model)
