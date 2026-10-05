"""Streaming handler mixin: streaming LLM calls and request dispatch.

Separated from the original ``analyzer.py`` to isolate the concerns of
streaming response collection, JSON-mode dispatch, and backend-specific
request strategy (tool calling vs JSON mode vs text mode).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, NoReturn

from sqlseed_ai._client import APIConnectionError, APIError, APITimeoutError, get_openai_client
from sqlseed_ai._json_utils import JSONResponseError, parse_json_response
from sqlseed_ai.config import AIBackend
from sqlseed_ai.exceptions import ModelFallbackError, classify_api_error

from sqlseed._utils.logger import get_logger

from ._caller import _InteractionLoggingMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._caller import ProgressCallback

logger = get_logger(__name__)
_CALLER_MIXIN_REQUIRED = "provided by LLMCallerMixin"


def _unsupported_local_json_format(error: BaseException) -> bool:
    """Limit local capability fallback to an explicitly rejected JSON format."""
    if getattr(error, "status_code", None) not in (None, 400, 422):
        return False
    diagnostic = str(error).lower()
    return any(field in diagnostic for field in ("response_format", "json_schema", "json mode")) and any(
        reason in diagnostic for reason in ("not supported", "unsupported", "unknown", "unrecognized", "unexpected")
    )


def _report_stream_progress(
    on_progress: ProgressCallback | None, token: str, count: int, *, reasoning: bool = False
) -> None:
    """Throttle both answer and reasoning progress to every ten chunks."""
    if on_progress and count % 10 == 0:
        info: dict[str, str | int | bool] = {"token": token, "count": count}
        if reasoning:
            info["reasoning"] = True
        on_progress("streaming", info)


class StreamingHandlerMixin(_InteractionLoggingMixin):
    """Mixin providing streaming LLM calls and request dispatch strategy.

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None`` and to mix in :class:`LLMCallerMixin` for
    ``_call_with_fallback``, ``_build_llm_kwargs``,
    ``_create_with_reasoning_fallback`` and
    :class:`ToolCallingMixin` for ``_try_tool_calling`` and
    :class:`JsonParserMixin` for ``_parse_json_response``.
    """

    if TYPE_CHECKING:
        # Provided by LLMCallerMixin / ToolCallingMixin / JsonParserMixin
        # when combined in SchemaAnalyzer. Stubs use
        # `raise RuntimeError("provided by ...")` (NOT `...` which pylint
        # infers as implicit None return -> assignment-from-no-return; NOT
        # `return None`/`return {}` which pylint flags as
        # assignment-from-none (E1128) on callers that assign the result;
        # and NOT `raise NotImplementedError` which pylint treats as
        # abstract method -> abstract-method). RuntimeError avoids all
        # three. The `-> None` stub (`_ensure_config`) uses plain `return`
        # since its result is never assigned. The `-> NoReturn` stub
        # (`_handle_llm_api_exception`) already raises. Real impls live in
        # sibling mixins and DO return values.
        def _ensure_config(self) -> None:
            return

        def _call_with_fallback(self, call_fn: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
            raise RuntimeError(_CALLER_MIXIN_REQUIRED)

        def _build_llm_kwargs(self, *, stream: bool = False, model: str | None = None) -> dict[str, Any]:
            raise RuntimeError(_CALLER_MIXIN_REQUIRED)

        def _create_with_reasoning_fallback(self, client: Any, kwargs: dict[str, Any]) -> Any:
            raise RuntimeError(_CALLER_MIXIN_REQUIRED)

        def _handle_llm_api_exception(self, e: Exception, model: str | None, *, streaming: bool = False) -> NoReturn:
            raise RuntimeError(_CALLER_MIXIN_REQUIRED)

        # Provided by ToolCallingMixin when combined in SchemaAnalyzer.
        def _try_tool_calling(
            self, client: Any, kwargs: dict[str, Any], *, preserve_names: bool = False, strict_json: bool = False
        ) -> dict[str, Any] | None:
            raise RuntimeError("provided by ToolCallingMixin")

        # Provided by JsonParserMixin when combined in SchemaAnalyzer.
        def _parse_json_response(self, content: str, *, preserve_names: bool = False) -> dict[str, Any]:
            raise RuntimeError("provided by JsonParserMixin")

    def call_llm_streaming(
        self,
        messages: list[dict[str, str]],
        on_progress: ProgressCallback | None = None,
        *,
        stage: str = "",
        table_name: str = "",
        preserve_names: bool = False,
        strict_json: bool = False,
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
            stage: Pipeline stage identifier for LLM interaction log attribution.
            table_name: Table being analyzed; populates the JSON log field.
            preserve_names: Keep SQL identifiers intact for schema-aware validation.
            strict_json: Raise content-free response errors, including a streamed
                length limit, instead of returning an empty or partial result.
        """
        self._ensure_config()
        return self._call_with_fallback(
            lambda model: self._call_llm_streaming_once(
                messages,
                on_progress,
                model=model,
                stage=stage,
                table_name=table_name,
                preserve_names=preserve_names,
                strict_json=strict_json,
            )
        )

    def _collect_stream_chunks(
        self,
        stream: Any,
        on_progress: ProgressCallback | None,
        *,
        strict_json: bool = False,
    ) -> tuple[str, int]:
        """Collect content from a streaming response.

        Args:
            stream: Iterable of streaming chunks from the API.
            on_progress: Optional progress callback.
            strict_json: Reject streams explicitly terminated by an output limit.

        Returns:
            (collected_content, token_count)
        """
        collected_content: list[str] = []
        token_count = 0
        reasoning_count = 0
        truncated = False

        for chunk in stream:
            if not chunk.choices:
                continue
            if strict_json and chunk.choices[0].finish_reason == "length":
                truncated = True
            delta = chunk.choices[0].delta
            # Gemma 4 reasoning models emit reasoning_content separately.
            # We skip reasoning tokens but count them for progress display.
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_count += 1
                _report_stream_progress(on_progress, "...", reasoning_count, reasoning=True)
                continue
            if not delta.content:
                continue
            token = delta.content
            collected_content.append(token)
            token_count += 1
            _report_stream_progress(on_progress, token, token_count)

        if truncated:
            raise JSONResponseError("truncated_response")
        return "".join(collected_content), token_count

    def _parse_stream_content(self, content: str, *, preserve_names: bool, strict_json: bool) -> dict[str, Any]:
        """Apply the caller-selected parsing policy to collected stream content."""
        if strict_json:
            return parse_json_response(content, strict=True, preserve_names=preserve_names)
        return self._parse_json_response(content, preserve_names=preserve_names)

    def _call_llm_streaming_once(
        self,
        messages: list[dict[str, str]],
        on_progress: ProgressCallback | None,
        *,
        model: str | None = None,
        stage: str = "",
        table_name: str = "",
        preserve_names: bool = False,
        strict_json: bool = False,
    ) -> dict[str, Any]:
        """Execute a single streaming LLM call (no fallback).

        Args:
            messages: Chat messages to send.
            on_progress: Optional progress callback.
            model: Model ID to use; falls back to ``self._config.model``.
            stage: Pipeline stage identifier for LLM interaction log attribution
                (e.g., "stage2_per_column", "refiner").
            table_name: Table being analyzed; populates the ``table_name`` field
                in the JSON log so the log analyzer can group calls by table.

        Returns:
            Parsed JSON dict from the streamed response.
        """
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before calling LLM")
        client = get_openai_client(self._config)
        start_time = time.time()
        stream = None

        try:
            if on_progress:
                on_progress("connecting", {"model": model or self._config.model})
            kwargs = self._build_llm_kwargs(stream=True, model=model)
            kwargs["messages"] = messages

            stream = self._create_streaming_response(client, kwargs, strict_json=strict_json)

            content, token_count = self._collect_stream_chunks(stream, on_progress, strict_json=strict_json)

            if on_progress:
                on_progress("parsing", {"tokens": token_count})

            actual_model = model or (self._config.model if self._config else "unknown")
            elapsed = time.time() - start_time

            if not content:
                if strict_json:
                    raise JSONResponseError("empty_response")
                self._log_llm_interaction(
                    messages=messages,
                    response="(empty stream response)",
                    model=actual_model,
                    stage=stage,
                    table_name=table_name,
                    elapsed=elapsed,
                )
                return {}

            # Log the full interaction (prompt + response) to a JSON file
            self._log_llm_interaction(
                messages=messages,
                response=content,
                model=actual_model,
                stage=stage,
                table_name=table_name,
                elapsed=elapsed,
            )

            logger.debug(
                "LLM streaming raw response",
                content_length=len(content),
                content_preview=content[:200],
                model=actual_model,
            )

            result = self._parse_stream_content(content, preserve_names=preserve_names, strict_json=strict_json)

            if on_progress:
                on_progress("done", {"tokens": token_count, "model": actual_model})

            return result

        except JSONResponseError:
            raise
        except (APITimeoutError, APIConnectionError, APIError, ValueError, RuntimeError, OSError) as e:
            self._log_llm_interaction(
                messages=messages,
                response="",
                model=model or (self._config.model if self._config else "unknown"),
                stage=stage,
                table_name=table_name,
                elapsed=time.time() - start_time,
                error=str(e),
            )
            self._handle_llm_api_exception(e, model, streaming=True)
        finally:
            try:
                if stream is not None:
                    stream.close()
            finally:
                client.close()

    def _create_streaming_response(self, client: Any, kwargs: dict[str, Any], *, strict_json: bool) -> Any:
        """Apply local JSON sampling without changing cloud streaming dispatch."""
        if strict_json and self._config and self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            return self._send_with_json_mode(client, kwargs)
        return self._create_with_reasoning_fallback(client, kwargs)

    def _send_llm_request(
        self,
        client: Any,
        kwargs: dict[str, Any],
        *,
        preserve_names: bool = False,
        strict_json: bool = False,
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
        if (
            self._config.resolve_tool_calling_protocol() in {"gemma4", "openai"}
            and (
                result := self._try_tool_calling(client, kwargs, preserve_names=preserve_names, strict_json=strict_json)
            )
            is not None
        ):
            return result

        # Strict local calls also need sampling constraints, rather than only a
        # prompt requesting JSON. Keep optional direct Python calls unchanged.
        if self._config.backend in (AIBackend.GOOGLE_AI_STUDIO, AIBackend.OPENAI_COMPAT) or strict_json:
            return self._send_with_json_mode(client, kwargs)

        # Non-strict local calls retain their existing text-mode behavior.
        return self._create_with_reasoning_fallback(client, kwargs)

    def _send_with_json_mode(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Any:
        """Request JSON sampling, with one fallback for an unsupported format.

        LM Studio's documented grammar interface uses JSON Schema. Constrain
        only the object envelope: identifiers, generator parameters and business
        rules still require the caller's existing validation.
        """
        if self._config and self._config.backend == AIBackend.LM_STUDIO:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "json_object_response", "strict": True, "schema": {"type": "object"}},
            }
        else:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            return client.chat.completions.create(**kwargs)
        except (APIError, ValueError, RuntimeError) as fmt_err:
            # Detect unsupported JSON mode / response_format via structured classification
            classified = classify_api_error(fmt_err)
            local = self._config and self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA)
            if isinstance(classified, ModelFallbackError) and (not local or _unsupported_local_json_format(fmt_err)):
                logger.debug(
                    "JSON mode not supported, falling back to text mode",
                    model=kwargs.get("model", self._config.model if self._config else "unknown"),
                )
                del kwargs["response_format"]
                return client.chat.completions.create(**kwargs)
            raise
