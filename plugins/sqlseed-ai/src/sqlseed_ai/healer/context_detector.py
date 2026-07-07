"""ContextWindowDetector — dynamic model context window detection.

Spec reference: Section 3.2.

Detection priority:
  1. ``AIConfig.max_context_tokens`` (user explicit configuration)
  2. Model mapping table (common models)
  3. Conservative default (4096)
"""

from __future__ import annotations

from sqlseed_ai.config import AIConfig

# Known model context window sizes (in tokens).
# Used when AIConfig.max_context_tokens is None.
_MODEL_CONTEXT_MAP: dict[str, int] = {
    "gemma-4-e2b": 8192,
    "gemma-4-e4b": 8192,
    "gemma-2b": 8192,
    "gemma-7b": 8192,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-3.5-turbo": 4096,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "deepseek-chat": 32768,
    "deepseek-r1": 65536,
    "llama-3-8b": 8192,
    "llama-3-70b": 8192,
    "qwen2-7b": 32768,
    "qwen2-72b": 32768,
    "mistral-7b": 32768,
    "mixtral-8x7b": 32768,
}

# Conservative default when model is unknown.
_DEFAULT_CONTEXT_WINDOW = 4096

# Pre-judgment threshold: skip Level 1 if token estimate exceeds this
# fraction of the context window.
_SKIP_LEVEL1_THRESHOLD = 0.60


class ContextWindowDetector:
    """Detect model context window size and estimate prompt token counts."""

    def __init__(self, ai_config: AIConfig, *, model: str = "") -> None:
        self._config = ai_config
        self._model = (model or "").lower()

    def get_context_window(self) -> int:
        """Get model context window size (tokens).

        Priority: AIConfig.max_context_tokens → model map → default 4096.
        """
        if self._config.max_context_tokens is not None:
            return self._config.max_context_tokens
        for key, size in _MODEL_CONTEXT_MAP.items():
            if key in self._model:
                return size
        return _DEFAULT_CONTEXT_WINDOW

    def estimate_tokens(self, prompt: str) -> int:
        """Estimate token count for a prompt (rough: chars / 4)."""
        return max(1, len(prompt) // 4)

    def should_skip_level1(self, prompt: str) -> bool:
        """Pre-judge: return True if tokens > 60% of context window."""
        tokens = self.estimate_tokens(prompt)
        threshold = self.get_context_window() * _SKIP_LEVEL1_THRESHOLD
        return tokens > threshold
