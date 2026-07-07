"""Shared LLM client protocol + OpenAI-compatible adapter.

Extracted from ``llm_healer.py`` so all healers (Level1/2/3) can share
the same client abstraction without importing the soon-to-be-deleted
``llm_healer`` module.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Minimal protocol for chat-completion clients (openai-compatible)."""

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Create a chat completion (openai-compatible)."""
        ...


class OpenAICompatAdapter:
    """Adapter wrapping ``openai.OpenAI`` to satisfy the ``LLMClient`` protocol.

    The real OpenAI Python SDK exposes ``client.chat.completions.create(...)``
    (attribute chain), but healers call ``client.chat_completions_create(...)``
    (flat method). Without this adapter, every heal() call raises
    ``AttributeError: 'OpenAI' object has no attribute 'chat_completions_create'``.
    """

    def __init__(self, openai_client: Any) -> None:
        self._client = openai_client

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Forward to ``client.chat.completions.create``."""
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
