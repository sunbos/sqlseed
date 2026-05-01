from __future__ import annotations

import os

from pydantic import BaseModel, Field
from sqlseed_ai._model_selector import PREFERRED_FREE_MODELS, select_best_free_model

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class AIConfig(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = "https://openrouter.ai/api/v1"
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    timeout: float = Field(default=60.0, gt=0)

    @classmethod
    def from_env(cls) -> AIConfig:
        api_key = os.environ.get("SQLSEED_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        base_url = (
            os.environ.get("SQLSEED_AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://openrouter.ai/api/v1"
        )
        model = os.environ.get("SQLSEED_AI_MODEL") or None
        timeout_str = os.environ.get("SQLSEED_AI_TIMEOUT")
        timeout = float(timeout_str) if timeout_str else 60.0
        return cls(api_key=api_key, base_url=base_url, model=model, timeout=timeout)

    def resolve_model(self) -> str:
        if self.model is not None:
            return self.model

        if not self.api_key:
            fallback = PREFERRED_FREE_MODELS[0]
            self.model = fallback
            logger.info("No API key configured, using fallback model", model=fallback)
            return self.model

        self.model = select_best_free_model()
        logger.info("Auto-selected AI model", model=self.model)
        return self.model

    def apply_overrides(
        self, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None
    ) -> AIConfig:
        if api_key:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url
        if model:
            self.model = model
        return self
