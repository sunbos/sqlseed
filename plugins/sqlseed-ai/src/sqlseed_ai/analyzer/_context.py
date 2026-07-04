"""Context builder mixin: schema context to LLM message construction.

Separated from the original ``analyzer.py`` to isolate the concerns of
building the chat messages and the user-message text describing the
table schema (columns, indexes, foreign keys, distribution, etc.).
"""

from __future__ import annotations

from typing import Any

from sqlseed_ai._prompts import (
    _COMPACT_SYSTEM_PROMPT,
    _ULTRA_COMPACT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from sqlseed_ai.config import AIBackend, AIConfig
from sqlseed_ai.examples import FEW_SHOT_EXAMPLES


class ContextBuilderMixin:
    """Mixin building chat messages and schema context text for the LLM.

    Expects the host class to expose a ``_config`` attribute of type
    ``AIConfig | None``.
    """

    # Type hints for attributes provided by the host class.
    _config: AIConfig | None

    def build_initial_messages(
        self,
        schema_ctx: dict[str, Any],
        *,
        compact: bool = False,
        ultra_compact: bool = False,
    ) -> list[dict[str, str]]:
        """Build the chat messages for an LLM analysis request.

        Args:
            schema_ctx: Schema context produced by the orchestrator.
            compact: If True, use the compact system prompt and skip examples.
            ultra_compact: If True, use the ultra-compact system prompt and
                skip examples. Takes precedence over ``compact``.

        Returns:
            List of ``{"role": ..., "content": ...}`` message dicts.
        """
        context = self._build_context(schema_ctx)

        # Three-tier prompt selection: ultra-compact > compact > full
        system_prompt = (
            _ULTRA_COMPACT_SYSTEM_PROMPT if ultra_compact else (_COMPACT_SYSTEM_PROMPT if compact else SYSTEM_PROMPT)
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Use fewer examples for local models (4B) to reduce inference time
        max_examples = len(FEW_SHOT_EXAMPLES)
        if self._config and self._config.backend in (AIBackend.LM_STUDIO, AIBackend.OLLAMA):
            max_examples = 1  # Only 1 example for local inference speed
        if compact:
            max_examples = 0  # No examples when context is tight
        if ultra_compact:
            max_examples = 0

        for example in FEW_SHOT_EXAMPLES[:max_examples]:
            messages.append({"role": "user", "content": example["input"]})
            messages.append({"role": "assistant", "content": example["output"]})

        messages.append({"role": "user", "content": context})

        return messages

    def _build_context(
        self,
        schema_ctx: dict[str, Any],
    ) -> str:
        """Build the user-message text describing the table schema.

        Args:
            schema_ctx: Schema context dict from the orchestrator.

        Returns:
            Markdown-formatted schema description for the LLM.
        """
        table_name = schema_ctx.get("table_name", "unknown")
        raw_columns = schema_ctx.get("columns", [])
        indexes = schema_ctx.get("indexes", [])
        foreign_keys = schema_ctx.get("foreign_keys", [])
        all_table_names = schema_ctx.get("all_table_names", [])
        sample_data = schema_ctx.get("sample_data", [])
        distribution_profiles = schema_ctx.get("distribution")
        check_constraints = schema_ctx.get("check_constraints", [])
        dialect = schema_ctx.get("dialect", "sqlite")

        # Set of FK column names — used to mark them in the column list so
        # the LLM knows to OMIT them from the output (the sqlseed core
        # auto-resolves FK columns by sampling existing parent-table ids).
        fk_column_names = {fk.column for fk in foreign_keys}

        # Exclude skippable columns (autoincrement PKs, defaults, computed columns)
        # from the prompt context so that the LLM (especially local models) won't attempt
        # to generate rules for columns that are already handled automatically.
        columns = [
            col
            for col in raw_columns
            if not (
                (col.is_primary_key and col.is_autoincrement)
                or col.default is not None
                or getattr(col, "is_computed", False)
            )
        ]

        lines: list[str] = []
        lines.append(f"# Table: {table_name}")
        lines.append(f"Database dialect: {dialect}")
        lines.append("")

        self._append_columns_info(lines, columns, fk_column_names)

        if indexes:
            self._append_indexes_info(lines, indexes)

        if foreign_keys:
            lines.append("")
            lines.append("## Foreign Keys")
            for fk in foreign_keys:
                lines.append(f"- {fk.column} → {fk.ref_table}.{fk.ref_column}")
            lines.append(
                "NOTE: Foreign-key columns are auto-resolved by the sqlseed core "
                "from existing parent-table ids. Do NOT include them in the output "
                "columns list."
            )

        if check_constraints:
            self._append_check_constraints_info(lines, check_constraints)

        if all_table_names:
            lines.append("")
            lines.append("## All Tables in Database")
            lines.append(", ".join(all_table_names))

        if sample_data:
            lines.append("")
            lines.append("## Sample Data (existing rows)")
            for i, row in enumerate(sample_data[:5]):
                row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                lines.append(f"  Row {i + 1}: {row_str}")

        if distribution_profiles:
            self._append_distribution_info(lines, distribution_profiles)

        lines.append("")
        lines.append(
            "Please analyze this table schema and recommend "
            "a complete sqlseed JSON configuration for generating test data."
        )

        return "\n".join(lines)

    def _append_columns_info(
        self,
        lines: list[str],
        columns: list[Any],
        fk_column_names: set[str] | None = None,
    ) -> None:
        """Append the column list section to the context lines.

        Args:
            lines: Mutable list of context lines to extend.
            columns: Column descriptor objects with name/type/flags.
            fk_column_names: Optional set of FK column names. When provided,
                FK columns are tagged with ``[FOREIGN KEY — skip]`` so the
                LLM knows to omit them from the output.
        """
        fk_column_names = fk_column_names or set()
        lines.append("## Columns")
        for col in columns:
            parts = [f"- {col.name}: {col.type}"]
            if col.is_primary_key:
                parts.append("PRIMARY KEY")
            if col.is_autoincrement:
                parts.append("AUTOINCREMENT")
            if col.nullable:
                parts.append("NULLABLE")
            if col.default is not None:
                parts.append(f"DEFAULT={col.default}")
            if not col.nullable and col.default is None and not col.is_primary_key:
                parts.append("NOT NULL")
            if col.name in fk_column_names:
                parts.append("[FOREIGN KEY — skip in output]")
            lines.append(" ".join(parts))

    def _append_check_constraints_info(
        self,
        lines: list[str],
        check_constraints: list[dict[str, Any]],
    ) -> None:
        """Append the CHECK constraints section to the context lines.

        Args:
            lines: Mutable list of context lines to extend.
            check_constraints: List of dicts with ``name``, ``columns``,
                and ``expression`` keys.
        """
        lines.append("")
        lines.append("## CHECK Constraints")
        for chk in check_constraints:
            name = chk.get("name") or ""
            cols = chk.get("columns", [])
            expr = chk.get("expression", "")
            label = f" ({name})" if name else ""
            cols_str = f" [columns: {', '.join(cols)}]" if cols else ""
            lines.append(f"- CHECK{label}: {expr}{cols_str}")

    def _append_indexes_info(
        self,
        lines: list[str],
        indexes: list[dict[str, Any]],
    ) -> None:
        """Append the indexes section to the context lines.

        Args:
            lines: Mutable list of context lines to extend.
            indexes: Index descriptors with columns/unique flags.
        """
        lines.append("")
        lines.append("## Indexes")
        for idx in indexes:
            unique_str = "UNIQUE " if idx.get("unique") else ""
            cols_str = ", ".join(idx.get("columns", []))
            lines.append(f"- {unique_str}INDEX ({cols_str})")

    def _append_distribution_info(
        self,
        lines: list[str],
        distribution_profiles: list[dict[str, Any]],
    ) -> None:
        """Append the column distribution section to the context lines.

        Args:
            lines: Mutable list of context lines to extend.
            distribution_profiles: Per-column distribution stats.
        """
        lines.append("")
        lines.append("## Column Distribution (from existing data)")
        for profile in distribution_profiles:
            col = profile["column"]
            distinct = profile.get("distinct_count", "?")
            null_ratio = profile.get("null_ratio", 0)
            lines.append(f"- {col}: {distinct} distinct values, {null_ratio:.1%} null")
            top_values = profile.get("top_values", [])
            if top_values:
                top_str = ", ".join(f"{tv['value']}({tv['frequency']:.0%})" for tv in top_values[:3])
                lines.append(f"  Top values: {top_str}")
            vr = profile.get("value_range")
            if vr:
                lines.append(f"  Range: [{vr['min']}, {vr['max']}]")
