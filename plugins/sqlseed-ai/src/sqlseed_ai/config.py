from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

# ── Gemma 4 model registry ──────────────────────────────────────────
class GemmaModel(str, Enum):
    """Supported Gemma 4 model variants."""

    GEMMA_4_2B = "gemma-4-2b-it"
    GEMMA_4_4B = "gemma-4-4b-it"
    GEMMA_4_26B = "gemma-4-26b-it"
    GEMMA_4_31B = "gemma-4-31b-it"

    @property
    def display_name(self) -> str:
        names = {
            "gemma-4-2b-it": "Gemma 4 2B (Edge)",
            "gemma-4-4b-it": "Gemma 4 4B (Edge)",
            "gemma-4-26b-it": "Gemma 4 26B MoE (Recommended)",
            "gemma-4-31b-it": "Gemma 4 31B Dense",
        }
        return names.get(self.value, self.value)


# ── Backend providers ────────────────────────────────────────────────
class AIBackend(str, Enum):
    """LLM backend provider."""

    GOOGLE_AI_STUDIO = "google_ai_studio"
    LM_STUDIO = "lm_studio"
    OLLAMA = "ollama"
    OPENAI_COMPAT = "openai_compat"  # generic OpenAI-compatible endpoint


# ── Default URLs ─────────────────────────────────────────────────────
GOOGLE_AI_STUDIO_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

DEFAULT_GEMMA_MODEL = GemmaModel.GEMMA_4_26B


class AIConfig(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    backend: AIBackend = AIBackend.GOOGLE_AI_STUDIO
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    timeout: float = Field(default=60.0, gt=0)

    @classmethod
    def from_env(cls) -> AIConfig:
        api_key = (
            os.environ.get("SQLSEED_AI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        base_url = (
            os.environ.get("SQLSEED_AI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or None
        )
        model = os.environ.get("SQLSEED_AI_MODEL") or None
        backend_str = os.environ.get("SQLSEED_AI_BACKEND", "").lower()
        timeout_str = os.environ.get("SQLSEED_AI_TIMEOUT")
        timeout = float(timeout_str) if timeout_str else 60.0

        # Resolve backend
        backend = AIBackend.GOOGLE_AI_STUDIO  # default
        if backend_str == "lm_studio":
            backend = AIBackend.LM_STUDIO
        elif backend_str == "ollama":
            backend = AIBackend.OLLAMA
        elif backend_str == "openai_compat":
            backend = AIBackend.OPENAI_COMPAT
        elif backend_str == "google_ai_studio" or (
            base_url and "generativelanguage.googleapis.com" in base_url
        ):
            backend = AIBackend.GOOGLE_AI_STUDIO
        elif base_url and ("127.0.0.1:1234" in base_url or "localhost:1234" in base_url):
            backend = AIBackend.LM_STUDIO
        elif base_url and ("localhost:11434" in base_url or "127.0.0.1:11434" in base_url):
            backend = AIBackend.OLLAMA

        return cls(api_key=api_key, base_url=base_url, model=model, backend=backend, timeout=timeout)

    def resolve_model(self) -> str:
        if self.model is not None:
            return self.model

        # Default to the recommended Gemma 4 model
        self.model = DEFAULT_GEMMA_MODEL.value
        logger.info("Using default Gemma 4 model", model=self.model)
        return self.model

    def resolve_base_url(self) -> str:
        """Resolve the API base URL based on backend selection."""
        if self.base_url is not None:
            return self.base_url

        if self.backend == AIBackend.GOOGLE_AI_STUDIO:
            self.base_url = GOOGLE_AI_STUDIO_BASE_URL
        elif self.backend == AIBackend.LM_STUDIO:
            self.base_url = LM_STUDIO_BASE_URL
        elif self.backend == AIBackend.OLLAMA:
            self.base_url = OLLAMA_BASE_URL
        else:
            # OpenAI-compatible: require explicit base_url
            self.base_url = GOOGLE_AI_STUDIO_BASE_URL

        return self.base_url

    def resolve_api_key(self) -> str | None:
        """Resolve API key based on backend."""
        if self.api_key:
            return self.api_key

        if self.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            # LM Studio and Ollama don't require an API key
            return "lm-studio" if self.backend == AIBackend.LM_STUDIO else "ollama"

        # Try environment variables
        return (
            os.environ.get("SQLSEED_AI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )

    def apply_overrides(
        self, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None,
        backend: AIBackend | None = None,
    ) -> AIConfig:
        if api_key:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url
        if model:
            self.model = model
        if backend:
            self.backend = backend
        return self

    def to_openai_kwargs(self) -> dict[str, Any]:
        """Build keyword arguments for the OpenAI client constructor."""
        base_url = self.resolve_base_url()
        api_key = self.resolve_api_key()
        return {
            "api_key": api_key or "",
            "base_url": base_url,
            "timeout": self.timeout,
        }
