from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


# ── Gemma 4 model registry ──────────────────────────────────────────
class GemmaModel(str, Enum):
    """Supported Gemma 4 model variants.

    Enum values use the canonical Google AI Studio format (gemma-4-xxb-it).
    Use to_backend_id() to convert to platform-specific model IDs.

    Model ID formats by platform (verified 2026-06-13):
      Google AI Studio: gemma-4-xxb-it        (only 26B-A4B and 31B)
      LM Studio:        google/gemma-4-xxb    (all 5 variants)
      Ollama:           gemma4:xxb            (all 5 variants; default tag = e4b)
      OpenRouter:       google/gemma-4-xxb-it (E2B/E4B/26B/31B; 12B not available)

    See: https://ai.google.dev/gemma/docs/core
    """

    GEMMA_4_E2B = "gemma-4-e2b-it"
    GEMMA_4_E4B = "gemma-4-e4b-it"
    GEMMA_4_12B = "gemma-4-12b-it"
    GEMMA_4_26B_A4B = "gemma-4-26b-a4b-it"
    GEMMA_4_31B = "gemma-4-31b-it"

    @property
    def display_name(self) -> str:
        names = {
            "gemma-4-e2b-it": "Gemma 4 E2B (2B Effective, Edge)",
            "gemma-4-e4b-it": "Gemma 4 E4B (4B Effective, Edge)",
            "gemma-4-12b-it": "Gemma 4 12B Unified (Laptop)",
            "gemma-4-26b-a4b-it": "Gemma 4 26B A4B MoE (Recommended)",
            "gemma-4-31b-it": "Gemma 4 31B Dense",
        }
        return names.get(self.value, self.value)

    @property
    def is_local_only(self) -> bool:
        """Whether this model is only available on local backends (LM Studio, Ollama).

        Gemma 4 12B is designed for local/edge deployment and is not hosted
        by Google AI Studio or available on OpenRouter.
        """
        return self == GemmaModel.GEMMA_4_12B

    def to_backend_id(self, backend: AIBackend) -> str:
        """Convert canonical model ID to platform-specific model ID.

        Each platform uses a different model ID format:
          Google AI Studio: gemma-4-e4b-it
          LM Studio:        google/gemma-4-e4b
          Ollama:           gemma4:e4b
          OpenRouter:       google/gemma-4-e4b-it  (add :free for free tier)
        """
        # Extract the core variant from canonical ID (e.g., "e4b" from "gemma-4-e4b-it")
        core = self.value.replace("gemma-4-", "").replace("-it", "")

        if backend == AIBackend.GOOGLE_AI_STUDIO:
            return self.value  # Canonical format: gemma-4-e4b-it
        if backend == AIBackend.LM_STUDIO:
            return f"google/gemma-4-{core}"  # e.g., google/gemma-4-e4b
        if backend == AIBackend.OLLAMA:
            # Ollama uses "gemma4" prefix with colon separator
            # Special case: 26b-a4b → 26b (Ollama omits the "a4b" qualifier)
            if core == "26b-a4b":
                return "gemma4:26b"
            return f"gemma4:{core}"  # e.g., gemma4:e4b
        # OpenRouter and other OpenAI-compatible backends
        return f"google/{self.value}"  # e.g., google/gemma-4-e4b-it


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

DEFAULT_GEMMA_MODEL = GemmaModel.GEMMA_4_26B_A4B

_BACKEND_MAP: dict[str, AIBackend] = {
    "lm_studio": AIBackend.LM_STUDIO,
    "ollama": AIBackend.OLLAMA,
    "openai_compat": AIBackend.OPENAI_COMPAT,
    "google_ai_studio": AIBackend.GOOGLE_AI_STUDIO,
}

_URL_PATTERNS: tuple[tuple[str, AIBackend], ...] = (
    ("generativelanguage.googleapis.com", AIBackend.GOOGLE_AI_STUDIO),
    ("127.0.0.1:1234", AIBackend.LM_STUDIO),
    ("localhost:1234", AIBackend.LM_STUDIO),
    ("localhost:11434", AIBackend.OLLAMA),
    ("127.0.0.1:11434", AIBackend.OLLAMA),
)


def _resolve_backend(backend_str: str, base_url: str | None) -> AIBackend:
    """Resolve AI backend from explicit string or base_url inference."""
    if backend_str in _BACKEND_MAP:
        return _BACKEND_MAP[backend_str]
    if base_url:
        for pattern, backend in _URL_PATTERNS:
            if pattern in base_url:
                return backend
    return AIBackend.GOOGLE_AI_STUDIO


class AIConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    backend: AIBackend = AIBackend.GOOGLE_AI_STUDIO
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=0, ge=0)  # 0 means auto-resolve based on backend
    timeout: float = Field(default=0.0, ge=0)  # 0 means auto-resolve based on backend

    # Non-serialized cache for inference speed probe results
    _speed_probe_cache: tuple[float, dict[str, Any]] | None = PrivateAttr(default=None)
    # Non-serialized cache for all local models detection (avoids repeated HTTP calls)
    _all_models_cache: tuple[float, list[str]] | None = PrivateAttr(default=None)

    @classmethod
    def from_env(cls) -> AIConfig:
        api_key = (
            os.environ.get("SQLSEED_AI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )
        base_url = os.environ.get("SQLSEED_AI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None
        model = os.environ.get("SQLSEED_AI_MODEL") or None
        backend_str = os.environ.get("SQLSEED_AI_BACKEND", "").lower()
        timeout_str = os.environ.get("SQLSEED_AI_TIMEOUT")
        timeout = float(timeout_str) if timeout_str else 0.0  # 0 = auto-resolve

        # Resolve backend
        backend = _resolve_backend(backend_str, base_url)

        return cls(api_key=api_key, base_url=base_url, model=model, backend=backend, timeout=timeout)

    def resolve_model(self) -> str:
        if self.model is not None:
            return self.model

        # Select default model based on backend
        if self.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            # For local inference, try to auto-detect available models
            detected = self._detect_local_model()
            if detected:
                self.model = detected
                logger.info("Auto-detected local model", model=self.model, backend=self.backend.value)
                return self.model
            # Fallback to compact model for local inference (platform-specific ID)
            self.model = GemmaModel.GEMMA_4_E4B.to_backend_id(self.backend)
            logger.info("Using compact Gemma 4 model for local inference", model=self.model)
        else:
            # Default to the recommended Gemma 4 model for cloud backends
            self.model = DEFAULT_GEMMA_MODEL.to_backend_id(self.backend)
            logger.info("Using default Gemma 4 model", model=self.model)

        return self.model

    def _detect_local_model(self) -> str | None:
        """Try to auto-detect the first available model from local backend.

        Results are cached for 2 minutes to avoid repeated HTTP requests
        during fallback chains (each call would otherwise block up to 5s).
        """
        models = self._detect_all_local_models()
        return models[0] if models else None

    def _detect_all_local_models(self) -> list[str]:
        """Detect all available models from local backend.

        Results are cached for 2 minutes to avoid repeated HTTP requests.
        Returns a list of model IDs (may be empty).
        """
        # Return cached result if detected recently (within 2 minutes)
        if self._all_models_cache is not None:
            cached_time, cached_result = self._all_models_cache
            if time.monotonic() - cached_time < 120:  # 2 minutes
                return cached_result

        try:
            if self.backend == AIBackend.LM_STUDIO:
                url = LM_STUDIO_BASE_URL + "/models"
            elif self.backend == AIBackend.OLLAMA:
                url = OLLAMA_BASE_URL + "/models"
            else:
                return []

            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
                self._all_models_cache = (time.monotonic(), models)
                return models
        except (OSError, ValueError, KeyError):
            logger.debug("Could not auto-detect local models", backend=self.backend.value)

        # Cache negative result too, to avoid hammering a dead endpoint
        self._all_models_cache = (time.monotonic(), [])
        return []

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
            # OpenAI-compatible backends (e.g., OpenRouter) require explicit base_url
            raise ValueError(
                "OPENAI_COMPAT backend requires SQLSEED_AI_BASE_URL to be set. Example: https://openrouter.ai/api/v1"
            )

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
            os.environ.get("SQLSEED_AI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        )

    def resolve_max_tokens(self) -> int:
        """Resolve max_tokens based on backend and model size.

        Local models (LM Studio, Ollama) are much slower at inference,
        so we use a smaller max_tokens to keep response times reasonable.

        Key insight: Gemma 4 E2B/E4B are reasoning models. With
        reasoning_effort=none, they only produce content tokens (no CoT).
        A budget of 768 covers up to ~30-column tables while keeping
        response time manageable on slow local hardware.

        NOTE: This is a pure function — it does not modify self.max_tokens.
        """
        if self.max_tokens > 0:
            return self.max_tokens  # User explicitly set a value

        # Auto-resolve based on backend (do not modify self.max_tokens)
        if self.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            model_str = (self.model or "").lower()
            if "e2b" in model_str or "e4b" in model_str:
                return 768  # With reasoning_effort=none: ~200-600 content tokens
            if "12b" in model_str:
                return 1024
            return 2048

        # Cloud backends: use larger max_tokens
        return 4096

    def is_small_local_model(self) -> bool:
        """Check if the current model is a small local model (E2B/E4B).

        Small models on local hardware have very high TTFT with streaming,
        so non-streaming + ultra-compact prompts are preferred.
        """
        if self.backend not in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            return False
        return self.is_reasoning_model()

    def is_reasoning_model(self) -> bool:
        """Check if the current model uses chain-of-thought reasoning.

        Gemma 4 E2B/E4B are reasoning models that emit reasoning_content
        separately from the actual output content. This consumes extra tokens
        and time. Setting reasoning_effort=none disables CoT for faster output.

        Matches both canonical IDs (gemma-4-e4b-it) and LM Studio IDs
        (google/gemma-4-e4b).
        """
        model_str = (self.model or "").lower()
        # Match "e2b" or "e4b" anywhere in the model ID
        # Handles: gemma-4-e4b-it, google/gemma-4-e4b, gemma-4-e2b-it, etc.
        return bool(re.search(r"\be[24]b\b", model_str))

    def should_use_streaming(self) -> bool:
        """Whether to use streaming API calls.

        Small local models (E2B/E4B) have extremely high TTFT with streaming
        (50-75s) vs non-streaming (10-15s), so streaming is counterproductive.
        Larger local models (12B+) and cloud backends benefit from streaming.
        """
        return not self.is_small_local_model()

    def should_use_ultra_compact(self) -> bool:
        """Whether to use ultra-compact prompts by default.

        Small local models benefit from ultra-compact prompts to reduce
        prompt tokens and thus prefill time (TTFT).
        """
        return self.is_small_local_model()

    def resolve_timeout(self) -> float:
        """Resolve timeout based on backend and model size.

        When timeout=0 (auto-resolve), uses sensible defaults per backend.
        When user explicitly sets a timeout (via CLI --timeout or env var),
        we respect it as long as it's at least 30s (to avoid instant failures).

        This is a pure function — it does not modify self.timeout.
        """
        # User explicitly set a timeout
        if self.timeout > 0:
            return max(self.timeout, 30.0)

        # Auto-resolve defaults
        if self.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            if self.is_reasoning_model():
                return 300.0  # 5 minutes for local reasoning models
            return 120.0  # 2 minutes for other local models
        return 60.0  # 1 minute for cloud backends

    def apply_overrides(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
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

    def probe_inference_speed(self) -> dict[str, Any] | None:
        """Probe the local backend's inference speed with a tiny request.

        Returns a dict with speed info, or None if the backend is not local
        or the probe fails. This helps auto-tune parameters like max_tokens
        and prompt compactness based on actual hardware capability.

        The probe sends a 10-token request and measures tokens/second.
        Results are cached for 5 minutes to avoid repeated probing.
        """
        if self.backend not in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            return None

        # Return cached result if probed recently (within 5 minutes)
        if self._speed_probe_cache is not None:
            cached_time, cached_result = self._speed_probe_cache
            if time.monotonic() - cached_time < 300:  # 5 minutes
                return cached_result

        model = self.model or self.resolve_model()
        base_url = self.resolve_base_url()

        try:
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 10,
                "temperature": 0.1,
                "stream": False,
            }

            # Disable reasoning for the probe itself to avoid wasting time
            # on chain-of-thought tokens during speed measurement
            if self.is_reasoning_model():
                payload["reasoning_effort"] = "none"

            data = json.dumps(payload).encode()

            url = f"{base_url}/chat/completions"
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            start = time.monotonic()
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
            elapsed = time.monotonic() - start

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            total_tokens = prompt_tokens + completion_tokens

            speed = total_tokens / elapsed if elapsed > 0 else 0

            info = {
                "model": model,
                "tokens_per_second": round(speed, 1),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_tokens,
                "elapsed_seconds": round(elapsed, 1),
                "is_slow": speed < 10,  # <10 tok/s is considered slow
            }

            logger.info(
                "Inference speed probe",
                model=model,
                tokens_per_second=info["tokens_per_second"],
                elapsed=info["elapsed_seconds"],
                is_slow=info["is_slow"],
            )

            # Cache the result
            self._speed_probe_cache = (time.monotonic(), info)

            return info

        except (OSError, ValueError, RuntimeError) as e:
            logger.debug("Inference speed probe failed", error=str(e))
            return None

    def to_openai_kwargs(self) -> dict[str, Any]:
        """Build keyword arguments for the OpenAI client constructor."""
        base_url = self.resolve_base_url()
        api_key = self.resolve_api_key()
        return {
            "api_key": api_key or "",
            "base_url": base_url,
            "timeout": self.resolve_timeout(),
        }
