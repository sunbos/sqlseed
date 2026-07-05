"""LLM caller mixin: model fallback, kwargs building, and non-streaming calls.

Separated from the original ``analyzer.py`` to isolate the concerns of
LLM invocation, model fallback chain, and reasoning-effort handling.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, NoReturn

from sqlseed_ai._client import APIConnectionError, APIError, APITimeoutError, get_openai_client
from sqlseed_ai._model_selector import _normalize_model_id, select_next_gemma_model
from sqlseed_ai.config import AIBackend, AIConfig
from sqlseed_ai.exceptions import ContextOverflowError, ModelFallbackError, classify_api_error

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir

logger = get_logger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[str, dict[str, Any]], None]

_MAX_FALLBACK_ATTEMPTS = 3


class LLMCallerMixin:
    """Mixin providing LLM call orchestration with model fallback.

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None`` and to mix in :class:`StreamingHandlerMixin` for
    ``_send_llm_request`` and :class:`JsonParserMixin` for
    ``_parse_json_response``.
    """

    # Type hints for attributes provided by the host class.
    _config: AIConfig | None

    if TYPE_CHECKING:
        from pathlib import Path

        # Provided by StreamingHandlerMixin / JsonParserMixin when combined
        # in SchemaAnalyzer. Stubs use `raise RuntimeError("provided by ...")`
        # (NOT `...` which pylint infers as implicit None return ->
        # assignment-from-no-return; NOT `return None`/`return {}` which
        # pylint flags as assignment-from-none (E1128) on callers that
        # assign the result; and NOT `raise NotImplementedError` which
        # pylint treats as abstract method -> abstract-method). RuntimeError
        # avoids all three: it's a raise (no implicit None return), it's
        # not an explicit None return, and it's not NotImplementedError.
        # Real impls live in sibling mixins and DO return values.
        def _send_llm_request(self, client: Any, kwargs: dict[str, Any]) -> Any:
            raise RuntimeError("provided by StreamingHandlerMixin")

        # Provided by JsonParserMixin when combined in SchemaAnalyzer.
        def _parse_json_response(self, content: str) -> dict[str, Any]:
            raise RuntimeError("provided by JsonParserMixin")

    def _log_llm_interaction(
        self,
        *,
        messages: list[dict[str, str]],
        response: str,
        model: str | None,
        stage: str = "",
        table_name: str = "",
        elapsed: float = 0.0,
        error: str | None = None,
    ) -> Path | None:
        """Log a full LLM interaction (prompt + response) to a JSON file.

        Writes to ``<cache_root>/ai_logs/<timestamp>_<stage>.json`` when
        ``self._config.log_llm_interactions`` is True. Returns the file path
        on success, or None if logging is disabled or failed.
        """
        if not self._config or not self._config.log_llm_interactions:
            return None
        try:
            log_dir = get_cache_dir("ai_logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            suffix = f"_{stage}" if stage else ""
            suffix += f"_{table_name}" if table_name else ""
            # Sanitize filename (remove invalid chars)
            safe_suffix = re.sub(r"[^\w\-]", "_", suffix)
            log_path = log_dir / f"{ts}{safe_suffix}.json"
            log_data: dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "model": model or "(unknown)",
                "stage": stage,
                "table_name": table_name,
                "elapsed_seconds": round(elapsed, 3),
                "messages": messages,
                "response": response,
            }
            if error:
                log_data["error"] = error
            log_path.write_text(
                json.dumps(log_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return log_path
        except Exception as e:
            logger.warning("Failed to log LLM interaction", error=str(e))
            return None

    def _find_local_fallback_model(
        self,
        current_model: str | None,
        next_model: str,
    ) -> str | None:
        """Check if a fallback model is available on the local backend.

        Uses detect_all_local_models to match against all loaded models,
        not just the first one. Returns the actual local model ID if found,
        or None if no suitable fallback exists.
        """
        config = self._config
        if config is None:
            raise RuntimeError("AIConfig must be initialized before checking local fallback")
        all_local = config.detect_all_local_models()
        if not all_local:
            return None

        # Build a normalized->actual mapping of all local models
        local_map: dict[str, str] = {}
        for m in all_local:
            local_map[_normalize_model_id(m)] = m

        # Check if the next fallback model is available locally
        next_norm = _normalize_model_id(next_model)
        if next_norm in local_map:
            return local_map[next_norm]

        # Check if the only local model is the one that just failed
        current_norm = _normalize_model_id(current_model or "")
        available_others = [v for k, v in local_map.items() if k != current_norm]
        if not available_others:
            # Only one model and it's the one that failed
            return None

        # Walk the fallback chain and find the first available local model
        candidate: str | None = next_model
        while candidate is not None:
            cand_norm = _normalize_model_id(candidate)
            if cand_norm in local_map:
                return local_map[cand_norm]
            candidate = select_next_gemma_model(candidate)

        return None

    def _ensure_config(self) -> None:
        """Initialize and validate AIConfig if not already done."""
        if self._config is None:
            self._config = AIConfig.from_env()
        self._config.model = self._config.resolve_model()
        if not self._config.resolve_api_key():
            raise ValueError("AI API key not configured")

    def _call_with_fallback(
        self,
        call_fn: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute an LLM call with model fallback on timeout/connection errors.

        Args:
            call_fn: A callable that takes a model name and returns the LLM result.
        """
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before this operation")
        current_model: str = self._config.model or ""
        for attempt in range(_MAX_FALLBACK_ATTEMPTS):
            try:
                return call_fn(current_model)
            except (APITimeoutError, APIConnectionError) as e:
                logger.warning(
                    "LLM API call timed out or connection failed",
                    model=current_model,
                    error=str(e)[:200],
                    attempt=attempt + 1,
                )

                next_model = select_next_gemma_model(current_model or "", backend=self._config.backend)
                if next_model is None:
                    raise RuntimeError(
                        f"LLM API call failed after trying {attempt + 1} model(s). "
                        f"Last error (model={current_model}): {e}"
                    ) from e

                # For local backends, verify the fallback model is actually available.
                if self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
                    actual_model = self._find_local_fallback_model(current_model, next_model)
                    if actual_model is None:
                        raise RuntimeError(
                            f"No other model available on local backend besides {current_model}. "
                            f"Consider using a smaller model or increasing --timeout. "
                            f"Last error: {e}"
                        ) from e
                    next_model = actual_model

                logger.warning(
                    "Falling back to next Gemma 4 model",
                    from_model=current_model,
                    to_model=next_model,
                )
                current_model = next_model

        raise RuntimeError(f"LLM API call failed after {_MAX_FALLBACK_ATTEMPTS} fallback attempts")

    def call_llm(
        self,
        messages: list[dict[str, str]],
        *,
        stage: str = "",
        table_name: str = "",
    ) -> dict[str, Any]:
        """Send messages to the LLM (non-streaming) and return the parsed JSON.

        Args:
            messages: Chat messages built by :meth:`build_initial_messages`.
            stage: Pipeline stage identifier for LLM interaction log attribution.
            table_name: Table being analyzed; populates the JSON log field.

        Returns:
            Parsed JSON dict from the model response.
        """
        self._ensure_config()
        return self._call_with_fallback(
            lambda model: self._call_llm_once(messages, model=model, stage=stage, table_name=table_name)
        )

    @staticmethod
    def _is_reasoning_model_id(model_id: str | None) -> bool:
        """Check if a model ID refers to a reasoning model (E2B/E4B).

        This is a standalone check that doesn't depend on config state,
        so it works correctly even during model fallback when the actual
        model differs from config.model.
        """
        return bool(re.search(r"\be[24]b\b", (model_id or "").lower()))

    def _resolve_max_tokens_for_model(self, model_id: str | None) -> int:
        """Resolve max_tokens based on the ACTUAL model being used.

        Unlike config.resolve_max_tokens() which uses self.model (config state),
        this method uses the provided model_id, so it works correctly during
        model fallback when the actual model differs from config.model.
        """
        if self._config is None:
            return 2048
        if self._config.max_tokens > 0:
            return self._config.max_tokens  # User explicitly set a value
        if self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            model_str = (model_id or "").lower()
            if "e2b" in model_str or "e4b" in model_str:
                return 4096
            if "12b" in model_str:
                return 1024
            return 2048
        return 4096

    def _build_llm_kwargs(self, *, stream: bool = False, model: str | None = None) -> dict[str, Any]:
        """Build common kwargs for LLM API calls."""
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before this operation")
        actual_model = model or self._config.model
        kwargs: dict[str, Any] = {
            "model": actual_model,
            "messages": [],  # Caller must set
            "max_tokens": self._resolve_max_tokens_for_model(actual_model),
            "temperature": self._config.temperature,
        }
        if stream:
            kwargs["stream"] = True
        # NOTE: Gemma 4 E2B/E4B in LM Studio with reasoning_effort="none" produces
        # truncated output (finish_reason=stop with incomplete JSON). Let the
        # model use its native reasoning mode for adequate JSON generation.
        # The reasoning tokens are counted separately and do not count against
        # max_tokens budget for content.
        return kwargs

    def _create_with_reasoning_fallback(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Any:
        """Call client.chat.completions.create with reasoning_effort fallback.

        Some backends (older LM Studio) don't support reasoning_effort.
        If they return a 400 error, retry without it.
        """
        try:
            return client.chat.completions.create(**kwargs)
        except APIError as parameter_error:
            # Detect unsupported reasoning_effort via structured classification
            classified = classify_api_error(parameter_error)
            if "reasoning_effort" in kwargs and isinstance(classified, ModelFallbackError):
                logger.debug("reasoning_effort not supported, retrying without it", model=kwargs.get("model"))
                del kwargs["reasoning_effort"]
                return client.chat.completions.create(**kwargs)
            raise

    def _handle_llm_api_exception(
        self,
        e: Exception,
        model: str | None,
        *,
        streaming: bool = False,
    ) -> NoReturn:
        """Classify and re-raise LLM API exceptions.

        Shared error handling for both non-streaming (``_call_llm_once``) and
        streaming (``call_llm_streaming``) paths. Centralizes the
        classification of API errors into ``ContextOverflowError`` (signals
        compact retry) vs. generic ``RuntimeError`` (non-recoverable).

        Args:
            e: The caught exception (from the API call try block).
            model: Model ID used in the call, for error messages. Falls back
                to ``self._config.model`` when None.
            streaming: If True, log context overflow at info level (the
                streaming path provides this hint to the caller for compact
                retry). Non-streaming path skips the log to keep noise down.

        Raises:
            APITimeoutError | APIConnectionError: Re-raised directly for the
                caller's fallback logic.
            ContextOverflowError: Re-raised so the caller can rebuild with
                compact/ultra-compact messages.
            RuntimeError: Wraps non-recoverable errors with model context.
        """
        if isinstance(e, (APITimeoutError, APIConnectionError)):
            raise e
        model_name = model or (self._config.model if self._config else "unknown")
        classified = classify_api_error(e)
        if isinstance(classified, ContextOverflowError):
            if streaming:
                logger.info("Context size exceeded, retrying with compact messages", model=model_name)
            raise classified from e
        raise RuntimeError(f"LLM API call failed (model={model_name}): {e}") from e

    def _call_llm_once(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        stage: str = "",
        table_name: str = "",
    ) -> dict[str, Any]:
        """Execute a single non-streaming LLM call (no fallback).

        Args:
            messages: Chat messages to send.
            model: Model ID to use; falls back to ``self._config.model``.
            stage: Pipeline stage identifier (e.g., "stage1", "stage2_per_column",
                "stage3_validation") for LLM interaction log attribution.
            table_name: Table being analyzed when ``stage`` is per-table or
                per-column. Populates the ``table_name`` field in the JSON log
                so the log analyzer can group calls by table.

        Returns:
            Parsed JSON dict from the model response.
        """
        if self._config is None:
            raise RuntimeError("AIConfig must be initialized before calling LLM")
        client = get_openai_client(self._config)
        start_time = time.time()

        try:
            kwargs = self._build_llm_kwargs(model=model)
            kwargs["messages"] = messages
            response = self._send_llm_request(client, kwargs)
        except (APITimeoutError, APIConnectionError, APIError, ValueError, RuntimeError, OSError) as e:
            self._log_llm_interaction(
                messages=messages,
                response="",
                model=model or self._config.model,
                stage=stage,
                table_name=table_name,
                elapsed=time.time() - start_time,
                error=str(e),
            )
            self._handle_llm_api_exception(e, model, streaming=False)

        if not response.choices:
            raise RuntimeError(
                f"LLM returned no choices (model={model or self._config.model}). The API key or model may be invalid."
            )
        message = response.choices[0].message
        content = message.content

        actual_model = model or self._config.model
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            logger.debug(
                "Model used chain-of-thought reasoning",
                reasoning_chars=len(message.reasoning_content),
                model=actual_model,
            )

        if content is None:
            self._log_llm_interaction(
                messages=messages,
                response="(empty response)",
                model=actual_model,
                stage=stage,
                table_name=table_name,
                elapsed=time.time() - start_time,
            )
            return {}

        # Log the full interaction (prompt + response) to a JSON file
        self._log_llm_interaction(
            messages=messages,
            response=content,
            model=actual_model,
            stage=stage,
            table_name=table_name,
            elapsed=time.time() - start_time,
        )

        logger.debug(
            "LLM raw response",
            content_length=len(content),
            content_preview=content[:200],
            model=actual_model,
        )

        return self._parse_json_response(content)
