"""Schema analysis driven by Gemma 4 (and other OpenAI-compatible LLMs).

This package hosts :class:`SchemaAnalyzer`, the entry point used by the CLI,
MCP server, and refiner to turn a database table schema into a sqlseed JSON
configuration. The analyzer supports three prompt verbosity tiers (full,
compact, ultra-compact), Gemma 4 native function calling, JSON-mode fallback,
and automatic model fallback on timeout/connection errors.

The implementation is split across five mixin modules, each owning a single
concern:

* :mod:`._caller` — LLM invocation, model fallback chain, kwargs building.
* :mod:`._streaming` — streaming response collection and request dispatch.
* :mod:`._tool_calling` — Gemma 4 native function calling.
* :mod:`._context` — chat message and schema context construction.
* :mod:`._json_parser` — JSON response parsing and analysis entry points.

:class:`SchemaAnalyzer` composes all of the above via multiple inheritance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._caller import LLMCallerMixin, ProgressCallback
from ._context import ContextBuilderMixin
from ._json_parser import JsonParserMixin
from ._streaming import StreamingHandlerMixin
from ._tool_calling import ToolCallingMixin

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig

__all__ = ["ProgressCallback", "SchemaAnalyzer"]


class SchemaAnalyzer(
    LLMCallerMixin,
    StreamingHandlerMixin,
    ToolCallingMixin,
    ContextBuilderMixin,
    JsonParserMixin,
):
    """Analyze database table schemas and produce sqlseed JSON configs via an LLM.

    The analyzer wraps an :class:`AIConfig` and exposes both non-streaming
    (:meth:`call_llm`) and streaming (:meth:`call_llm_streaming`) entry points.
    It automatically downgrades the system prompt (full -> compact ->
    ultra-compact) when the context window overflows, and falls back to
    smaller Gemma 4 variants on timeout/connection errors.
    """

    def __init__(self, config: AIConfig | None = None) -> None:
        """Initialize the analyzer with an optional pre-built config.

        Args:
            config: AI configuration. If ``None``, it is lazily built from
                environment variables on the first analysis call.
        """
        self._config = config
        if self._config is not None:
            self._config.model = self._config.resolve_model()

    @property
    def config(self) -> AIConfig | None:
        """Read-only access to the AI configuration."""
        return self._config
