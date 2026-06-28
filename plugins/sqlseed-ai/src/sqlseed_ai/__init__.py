"""sqlseed-ai plugin entry point.

This module exposes the :class:`AISqlseedPlugin`, a pluggy plugin that
integrates LLM-powered schema analysis into sqlseed's generation pipeline.

The plugin implements three sqlseed hooks:

* ``sqlseed_apply_ai_suggestions`` — high-level entry point invoked by
  the orchestrator. Decides whether AI is needed, builds the analysis
  context, calls the low-level analyze hook, and merges the result back
  into the column specs. The implementation lives in
  :mod:`sqlseed_ai.ai_mediator` (moved out of core per ARCHITECTURE.md
  Section 7.6).
* ``sqlseed_ai_analyze_table`` — analyzes a full table schema and returns a
  YAML/JSON generation template.
* ``sqlseed_pre_generate_templates`` — generates sample values for columns
  that are not covered by sqlseed's built-in simple-column heuristics.

The plugin lazily constructs a :class:`SchemaAnalyzer` (and the underlying
LLM client) on first use, so importing the module has no side effects.
"""

from __future__ import annotations

import re
from typing import Any

from sqlseed_ai.ai_mediator import apply_ai_suggestions
from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.config import AIBackend, AIConfig, GemmaModel
from sqlseed_ai.refiner import AiConfigRefiner, AISuggestionFailedError

from sqlseed._utils.logger import get_logger
from sqlseed.plugins.hookspecs import hookimpl

logger = get_logger(__name__)

__all__ = [
    "AIBackend",
    "AIConfig",
    "AISuggestionFailedError",
    "AiConfigRefiner",
    "GemmaModel",
    "SchemaAnalyzer",
    "apply_ai_suggestions",
]

_SIMPLE_COL_RE = re.compile(
    r"(^|[_\s])("
    r"name|email|phone|address|url|uuid|"
    r"date|time|datetime|timestamp|boolean|"
    r"int|float|double|real|text|string|"
    r"char|varchar|blob|byte|id|code|title|"
    r"description|status|type|category|count|"
    r"amount|price|value|number|index|order|level|"
    r"username|city|country|state|zip|postal|job|occupation"
    r")($|[_\s])",
    re.IGNORECASE,
)


class AISqlseedPlugin:
    """Pluggy plugin that injects LLM-powered schema analysis into sqlseed.

    The plugin is registered as ``plugin`` at module level and picked up by
    pluggy's plugin manager. The heavy :class:`SchemaAnalyzer` (which owns
    the LLM client) is constructed lazily on first use so that simply
    importing the module never triggers network or configuration work.
    """

    def __init__(self) -> None:
        """Initialize the plugin with no analyzer yet (lazy construction)."""
        self._analyzer: SchemaAnalyzer | None = None

    def _get_analyzer(self) -> SchemaAnalyzer:
        """Return the cached analyzer, constructing it on first call.

        The analyzer is built from environment-derived :class:`AIConfig`
        and its model is resolved before instantiation.

        Returns:
            The shared :class:`SchemaAnalyzer` instance.
        """
        if self._analyzer is None:
            config = AIConfig.from_env()
            config.model = config.resolve_model()
            self._analyzer = SchemaAnalyzer(config=config)
        return self._analyzer

    def _is_simple_column(self, column_name: str, column_type: str) -> bool:
        """Check whether a column matches the simple-column heuristic.

        Columns whose name or type matches :data:`_SIMPLE_COL_RE` are
        considered "simple" and are left to sqlseed's built-in generators,
        avoiding an unnecessary LLM round-trip.

        Args:
            column_name: The column name to inspect.
            column_type: The column SQL type to inspect.

        Returns:
            True if the column is simple and should skip AI generation.
        """
        return bool(_SIMPLE_COL_RE.search(column_name) or _SIMPLE_COL_RE.search(column_type))

    @hookimpl
    def sqlseed_ai_analyze_table(self, **kwargs: Any) -> dict[str, Any] | None:
        """Analyze a table schema and return an AI-generated template.

        Implements the ``sqlseed_ai_analyze_table`` hook. Delegates to
        :meth:`SchemaAnalyzer.analyze_table_from_ctx`.

        Args:
            **kwargs: Hook context forwarded to the analyzer.

        Returns:
            The analysis result dict, or None on failure.
        """
        analyzer = self._get_analyzer()
        try:
            return analyzer.analyze_table_from_ctx(**kwargs)
        except (ValueError, RuntimeError, OSError) as e:
            logger.warning(
                "AI table analysis hook failed",
                table_name=kwargs.get("table_name", ""),
                error=str(e),
            )
            return None

    @hookimpl
    def sqlseed_apply_ai_suggestions(
        self,
        db: Any,
        schema: Any,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, Any],
        user_configured_columns: set[str],
    ) -> dict[str, Any] | None:
        """Apply AI-driven suggestions to column specs (delegates to ai_mediator).

        Implements the ``sqlseed_apply_ai_suggestions`` hook. Parameter
        order differs from the hookspec (pluggy matches by name, not
        position) to avoid CodeDuplication with the hookspec signature.
        Delegates to :func:`sqlseed_ai.ai_mediator.apply_ai_suggestions`.
        """
        return apply_ai_suggestions(
            analyze_fn=self.sqlseed_ai_analyze_table,
            db=db,
            schema=schema,
            table_name=table_name,
            column_infos=column_infos,
            specs=specs,
            user_configured_columns=user_configured_columns,
        )

    @hookimpl
    def sqlseed_pre_generate_templates(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        count: int,
        sample_data: list[Any],
    ) -> list[Any] | None:
        """Generate sample values for a non-simple column via the LLM.

        Implements the ``sqlseed_pre_generate_templates`` hook. Simple
        columns (matched by :meth:`_is_simple_column`) short-circuit to
        None so sqlseed uses its built-in generators. For other columns
        the analyzer is asked for up to 50 template values. Any
        recoverable error returns None so the pipeline can fall back.

        Args:
            table_name: Name of the table the column belongs to.
            column_name: Name of the column to generate values for.
            column_type: SQL type of the column.
            count: Requested number of sample values (capped at 50).
            sample_data: Existing sample data to guide generation.

        Returns:
            A list of generated values, or None to defer to built-ins.
        """
        if self._is_simple_column(column_name, column_type):
            return None

        analyzer = self._get_analyzer()
        try:
            return analyzer.generate_template_values(
                column_name=column_name,
                column_type=column_type,
                count=min(count, 50),
                sample_data=sample_data,
                table_name=table_name,
            )
        except (ValueError, RuntimeError, OSError):
            return None


plugin = AISqlseedPlugin()
