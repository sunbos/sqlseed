"""Streaming handler mixin: streaming LLM calls and request dispatch.

Separated from the original ``analyzer.py`` to isolate the concerns of
streaming response collection, JSON-mode dispatch, and backend-specific
request strategy (tool calling vs JSON mode vs text mode).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai._client import APIConnectionError, APIError, APITimeoutError, get_openai_client
from sqlseed_ai.config import AIBackend, AIConfig
from sqlseed_ai.exceptions import ContextOverflowError, ModelFallbackError, classify_api_error

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._caller import ProgressCallback

logger = get_logger(__name__)


class StreamingHandlerMixin:
    """Mixin providing streaming LLM calls and request dispatch strategy.

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None`` and to mix in :class:`LLMCallerMixin` for
    ``_call_with_fallback``, ``_build_llm_kwargs``,
    ``_create_with_reasoning_fallback`` and :class:`ToolCallingMixin`
    for ``_try_tool_calling`` and :class:`JsonParserMixin` for
    ``_parse_json_response``.
    """

    # Type hints for attributes provided by the host class.
    _config: AIConfig | None

    if TYPE_CHECKING:
        # Provided by LLMCallerMixin when combined in SchemaAnalyzer.
        def _ensure_config(self) -> None: ...

        def _call_with_fallback(self, call_fn: Callable[[str], dict[str, Any]]) -> dict[str, Any]: ...

        def _build_llm_kwargs(self, *, stream: bool = False, model: str | None = None) -> dict[str, Any]: ...

        def _create_with_reasoning_fallback(self, client: Any, kwargs: dict[str, Any]) -> Any: ...

        # Provided by ToolCallingMixin when combined in SchemaAnalyzer.
        def _try_tool_calling(self, client: Any, kwargs: dict[str, Any]) -> dict[str, Any] | None: ...

        # Provided by JsonParserMixin when combined in SchemaAnalyzer.
        def _parse_json_response(self, content: str) -> dict[str, Any]: ...

    def call_llm_streaming(
        self,
        messages: list[dict[str, str]],
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Call LLM with streaming output and progress callbacks.

        Args:
            messages: Chat messages to send.
            on_progress: Callback for progress updates.
                Receives (phase, info) where phase is one of:
                - "connecting": API connection started
                - "streaming": token being generated, info={"token": str, "count": int}
                - "parsing": parsing the response JSON
                - "done": analysis complete, info={"tokens": int, "model": str}
        """
        self._ensure_config()
        return self._call_with_fallback(lambda model: self._call_llm_streaming_once(messages, on_progress, model=model))

    def _collect_stream_chunks(
        self,
        stream: Any,
        on_progress: ProgressCallback | None,
    ) -> tuple[str, int]:
        """Collect content from a streaming response.

        Args:
            stream: Iterable of streaming chunks from the API.
            on_progress: Optional progress callback.

        Returns:
            (collected_content, token_count)
        """
        collected_content: list[str] = []
        token_count = 0
        reasoning_count = 0

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Gemma 4 reasoning models emit reasoning_content separately.
            # We skip reasoning tokens but count them for progress display.
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_count += 1
                if on_progress and reasoning_count % 10 == 0:
                    on_progress("streaming", {"token": "...", "count": reasoning_count, "reasoning": True})
                continue
            if delta.content:
                token = delta.content
                collected_content.append(token)
                token_count += 1
                # Throttle progress callbacks to every 10 tokens to reduce overhead.
                if on_progress and token_count % 10 == 0:
                    on_progress("streaming", {"token": token, "count": token_count})

        return "".join(collected_content), token_count

    def _call_llm_streaming_once(
        self,
        messages: list[dict[str, str]],
        on_progress: ProgressCallback | None,
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single streaming LLM call (no fallback).

        Args:
            messages: Chat messages to send.
            on_progress: Optional progress callback.
            model: Model ID to use; falls back to ``self._config.model``.

        Returns:
            Parsed JSON dict from the streamed response.
        """
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before calling LLM")
        client = get_openai_client(self._config)

        if on_progress:
            on_progress("connecting", {"model": model or self._config.model})

        try:
            kwargs = self._build_llm_kwargs(stream=True, model=model)
            kwargs["messages"] = messages

            stream = self._create_with_reasoning_fallback(client, kwargs)

            content, token_count = self._collect_stream_chunks(stream, on_progress)

            if on_progress:
                on_progress("parsing", {"tokens": token_count})

            if not content:
                return {}

            actual_model = model or (self._config.model if self._config else "unknown")
            logger.debug(
                "LLM streaming raw response",
                content_length=len(content),
                content_preview=content[:200],
                model=actual_model,
            )

            result = self._parse_json_response(content)

            if on_progress:
                on_progress("done", {"tokens": token_count, "model": actual_model})

            return result

        except (APITimeoutError, APIConnectionError, APIError, ValueError, RuntimeError, OSError) as e:
            if isinstance(e, (APITimeoutError, APIConnectionError)):
                raise
            # Detect context overflow via structured exception classification
            classified = classify_api_error(e)
            if isinstance(classified, ContextOverflowError):
                logger.info("Context size exceeded, retrying with compact messages", model=model or self._config.model)
                raise classified from e  # Will be caught by caller which can rebuild with compact=True
            raise RuntimeError(f"LLM API call failed (model={model or self._config.model}): {e}") from e

    def _send_llm_request(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Any:
        """Send LLM request with protocol-aware strategy (tool calling, JSON mode, text).

        The dispatch strategy is driven by ``AIConfig.resolve_tool_calling_protocol()``
        (Phase E): the active protocol determines whether tool calling is
        attempted before falling back to JSON mode or text mode.

        Args:
            client: OpenAI client instance.
            kwargs: Request kwargs (will be modified for JSON mode).

        Returns:
            API response object.
        """
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before this operation")
        # Try native function calling when the resolved protocol enables it.
        # "gemma4" and "openai" share the same OpenAI-style tools wire format;
        # the server-side interpretation differs (Gemma 4 special tokens vs.
        # standard OpenAI function calling).
        protocol = self._config.resolve_tool_calling_protocol()
        if protocol in ("gemma4", "openai"):
            result = self._try_tool_calling(client, kwargs)
            if result is not None:
                return result

        # Try JSON mode for cloud backends; skip for local backends
        if self._config.backend in (AIBackend.GOOGLE_AI_STUDIO, AIBackend.OPENAI_COMPAT):
            return self._send_with_json_mode(client, kwargs)

        # Local backends (LM Studio, Ollama): use text mode directly
        return self._create_with_reasoning_fallback(client, kwargs)

    def _send_with_json_mode(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Any:
        """Send LLM request with JSON mode, falling back to text mode on error."""
        kwargs["response_format"] = {"type": "json_object"}
        try:
            return client.chat.completions.create(**kwargs)
        except (APIError, ValueError, RuntimeError) as fmt_err:
            # Detect unsupported JSON mode / response_format via structured classification
            classified = classify_api_error(fmt_err)
            if isinstance(classified, ModelFallbackError):
                logger.debug(
                    "JSON mode not supported, falling back to text mode",
                    model=kwargs.get("model", self._config.model if self._config else "unknown"),
                )
                del kwargs["response_format"]
                return client.chat.completions.create(**kwargs)
            raise
