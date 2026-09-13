"""JSON parser mixin: response parsing and analysis entry points.

Separated from the original ``analyzer.py`` to isolate the concerns of
parsing JSON out of LLM responses and the high-level analysis entry
points (``analyze_table_from_ctx`` and ``generate_template_values``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlseed_ai._json_utils import parse_json_response
from sqlseed_ai._prompts import TEMPLATE_SYSTEM_PROMPT
from sqlseed_ai.config import AIConfig

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class JsonParserMixin:
    """Mixin providing JSON response parsing and analysis entry points.

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None`` and to mix in :class:`ContextBuilderMixin` for
    ``build_initial_messages`` and :class:`LLMCallerMixin` for
    ``call_llm``.
    """

    # Type hints for attributes provided by the host class.
    _config: AIConfig | None

    if TYPE_CHECKING:
        # Provided by ContextBuilderMixin when combined in SchemaAnalyzer.
        # Stubs use `raise NotImplementedError` (not docstring-only body)
        # so pylint does not infer an implicit `return None` and falsely
        # flag callers with assignment-from-no-return. Real impls live in
        # ContextBuilderMixin / LLMCallerMixin and DO return values.
        def build_initial_messages(
            self,
            schema_ctx: dict[str, Any],
            *,
            compact: bool = False,
            ultra_compact: bool = False,
        ) -> list[dict[str, str]]:
            """Build the initial LLM message list from schema context (stub; real impl in ContextBuilderMixin)."""
            raise NotImplementedError

        # Provided by LLMCallerMixin when combined in SchemaAnalyzer.
        def call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
            """Send messages to the LLM and return the parsed response (stub; real impl in LLMCallerMixin)."""
            raise NotImplementedError

    def analyze_table_from_ctx(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Analyze a table from a schema context dict and return a config.

        Args:
            **kwargs: Schema context fields (table_name, columns, indexes,
                foreign_keys, all_table_names, sample_data, distribution).

        Returns:
            Parsed JSON config dict, or ``None`` if the API key is missing
            or the LLM call fails with a recoverable error.
        """
        if self._config is None:
            self._config = AIConfig.from_env()

        self._config.model = self._config.resolve_model()

        if not self._config.resolve_api_key():
            logger.warning(
                "AI API key not configured. "
                "Set GOOGLE_API_KEY, SQLSEED_AI_API_KEY, or OPENAI_API_KEY environment variable. "
                "For Ollama, set SQLSEED_AI_BACKEND=ollama."
            )
            return None

        messages = self.build_initial_messages(kwargs)

        try:
            return self.call_llm(messages)
        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("AI analysis failed", table_name=kwargs.get("table_name", ""), error=str(e))
            return None

    def generate_template_values(
        self,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
        table_name: str = "",
    ) -> list[Any]:
        """Generate realistic sample values for a column via the LLM.

        Args:
            column_name: Name of the column to generate values for.
            column_type: SQL type of the column.
            count: Number of values to request.
            sample_data: Existing sample values to guide generation.
            table_name: Optional table name for context.

        Returns:
            List of generated values (may be empty on failure).
        """
        prompt = (
            f"Generate {count} realistic sample values for a database column "
            f"named '{column_name}' with type '{column_type}'"
        )
        if table_name:
            prompt += f" in table '{table_name}'"
        prompt += "."
        if sample_data:
            prompt += f"\nExisting sample values: {sample_data[:5]}"
        prompt += (
            f'\nRespond with a JSON object: {{"values": [...]}}.\nEach value should be a valid {column_type} value.'
        )

        messages = [
            {"role": "system", "content": TEMPLATE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = self.call_llm(messages)
        values = result.get("values", [])
        return values if isinstance(values, list) else []

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """Parse a JSON object out of an LLM response string.

        Args:
            content: Raw text returned by the model (may include prose
                or markdown fences around the JSON payload).

        Returns:
            Parsed JSON dict.
        """
        return parse_json_response(content)
