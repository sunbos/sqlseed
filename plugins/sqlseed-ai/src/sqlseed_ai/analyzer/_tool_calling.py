"""Tool calling mixin: native function calling protocol implementation.

This mixin implements the tool calling protocols defined by
:data:`sqlseed_ai.config.ToolCallingProtocol` (Phase E):

- ``"gemma4"``: Gemma 4 native function calling. Uses :data:`GEMMA_TOOLS`
  with Google AI Studio's special-token-based protocol (``<|tool|>`` /
  ``<|tool_call|>``).
- ``"openai"``: Standard OpenAI function calling. Uses :data:`GEMMA_TOOLS`
  with the OpenAI tools API (same wire format, different server-side
  interpretation).
- ``"none"``: No tool calling. The caller (:meth:`_send_llm_request`)
  skips this mixin entirely and falls back to JSON mode or text mode.

The wire-level API call is identical for both ``"gemma4"`` and ``"openai"``:
the OpenAI Python client abstracts the difference. The protocol field
serves as a semantic label and a future extension point -- if Gemma 5
changes the special-token format, a ``"gemma5"`` protocol can be added
without removing ``"gemma4"`` (backward compatible, per ARCHITECTURE.md
Section 3.3).

Separated from the original ``analyzer.py`` to isolate the concerns of
native function calling (tool use) and result extraction from tool call
responses.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlseed_ai._client import APIError
from sqlseed_ai._tools import GEMMA_TOOLS
from sqlseed_ai.exceptions import ToolCallError, classify_api_error

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig

logger = get_logger(__name__)


class ToolCallingMixin:
    """Mixin providing native function calling support (gemma4 / openai protocols).

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None`` and to mix in :class:`JsonParserMixin` for
    ``_parse_json_response``. The caller (:meth:`_send_llm_request`)
    dispatches to :meth:`_try_tool_calling` only when
    :meth:`AIConfig.resolve_tool_calling_protocol` returns ``"gemma4"`` or
    ``"openai"``.
    """

    # Type hints for attributes provided by the host class.
    _config: AIConfig | None

    if TYPE_CHECKING:
        # Provided by JsonParserMixin when combined in SchemaAnalyzer.
        def _parse_json_response(self, content: str) -> dict[str, Any]: ...

    def _extract_tool_call_result(self, choice: Any) -> dict[str, Any] | None:
        """Extract the analyze_schema result from a tool call choice."""
        if not choice.message.tool_calls:
            return None
        for tool_call in choice.message.tool_calls:
            if tool_call.function.name == "analyze_schema":
                args_str = tool_call.function.arguments
                if args_str:
                    try:
                        result: dict[str, Any] | None = json.loads(args_str)
                        logger.info(
                            "Native function calling succeeded",
                            tool="analyze_schema",
                            protocol=self._config.tool_calling_protocol if self._config else "gemma4",
                            model=self._config.model if self._config else "unknown",
                        )
                        return result
                    except json.JSONDecodeError:
                        logger.debug("Failed to parse tool call arguments", args=args_str[:200])
        return None

    def _try_tool_calling(self, client: Any, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        """Attempt native function calling (gemma4 or openai protocol).

        The wire-level call is identical for both protocols: ``GEMMA_TOOLS``
        is in OpenAI-compatible format, and the OpenAI Python client
        abstracts the server-side difference (Gemma 4 special tokens vs.
        standard OpenAI function calling). The active protocol is determined
        by :meth:`AIConfig.resolve_tool_calling_protocol` in the caller.

        If the model supports tool use, it will invoke the ``analyze_schema``
        function with structured parameters. We then extract the result from
        the tool call response.

        Returns ``None`` if tool calling is not available or fails, so the
        caller can fall back to JSON mode or text mode.
        """
        try:
            tool_kwargs = {**kwargs, "tools": GEMMA_TOOLS, "tool_choice": "auto"}
            # Remove response_format if present (incompatible with tools)
            tool_kwargs.pop("response_format", None)

            response = client.chat.completions.create(**tool_kwargs)

            if not response.choices:
                return None

            choice = response.choices[0]

            result = self._extract_tool_call_result(choice)
            if result is not None:
                return result

            # If no tool call was made but we have text content, parse it
            if choice.message.content:
                return self._parse_json_response(choice.message.content)

            return None

        except (APIError, ValueError, RuntimeError) as e:
            # Detect unsupported tool calling via structured classification
            classified = classify_api_error(e)
            if isinstance(classified, ToolCallError):
                logger.debug(
                    "Tool calling not supported by this endpoint, falling back to JSON/text mode",
                    protocol=self._config.tool_calling_protocol if self._config else "gemma4",
                    model=kwargs.get("model", self._config.model if self._config else "unknown"),
                )
                return None
            raise
