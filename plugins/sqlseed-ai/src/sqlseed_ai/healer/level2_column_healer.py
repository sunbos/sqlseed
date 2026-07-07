"""Level 2: Column-level LLM healer with minimal dependency set.

Spec reference: Section 3.5 + 4.2.

Sends only the target column + its complete dependency set (CHECK
constraints, derive_from sources, cross-column refs, FK info) to the
LLM. This minimizes per-column prompt size and maximizes success rate
when the subgraph-level prompt (Level 1) overflows the context window.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer._client import LLMClient
from sqlseed_ai.healer.models import ColumnContext, FKInfo, Level2Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.validator.models import ViolationReport
    from sqlseed_ai.validator.schema_snapshot import SchemaSnapshot

logger = get_logger(__name__)


_SYSTEM_PROMPT = """You are a SQL test-data generator repair agent.

You will receive:
1. A single column that failed validation.
2. The violation report for that column.
3. The column's complete dependency set (CHECK constraints, derive_from
   sources, cross-column references, FK info).

Your task: output a JSON object with the corrected configuration for
ONLY this column.

Output format:
{"name": "<col>", "generator": "<gen>", "params": {...}}

Rules:
- Never use a generator that crashes on the column type.
- Respect UNIQUE constraints by upgrading choice -> template when needed.
- Respect CHECK constraints by adjusting min/max params.
- If the column has a derive_from source, use derive_from + expression.
- Keep the response under 500 tokens.
"""


class Level2ColumnHealer:
    """Column-level LLM healer (Level 2).

    Processes violation columns individually with minimal dependency
    context. Used when Level 1 fails due to context overflow or empty
    response, or when pre-judgment detects the subgraph prompt is too
    large for the model's context window.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 500,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def _build_column_context(
        self,
        table_name: str,
        column_name: str,
        snapshot: SchemaSnapshot,
    ) -> ColumnContext:
        """Extract minimal dependency info for a column.

        Spec reference: Section 3.5 (information boundary).

        Returns a ColumnContext with:
        - Target column attributes (name, type, nullable, default, UNIQUE)
        - All CHECK constraints this column participates in
        - derive_from source columns (if any)
        - derive_from downstream columns (if any)
        - Cross-column CHECK related columns
        - FK info (if column is a FK)
        """
        meta = snapshot.tables.get(table_name)
        if meta is None:
            return ColumnContext(
                table_name=table_name,
                column_name=column_name,
                column_type="TEXT",
                nullable=True,
                default=None,
                is_unique=False,
                check_constraints=[],
                derive_from_sources=[],
                derive_from_downstream=[],
                cross_column_refs=[],
                fk_info=None,
            )

        col_type = meta.column_types.get(column_name, "TEXT")
        all_columns = meta.columns

        # Collect CHECK constraints this column participates in.
        col_checks: list[dict[str, Any]] = []
        cross_column_refs: list[tuple[str, str]] = []
        for c in meta.constraints:
            if c.get("type") != "check":
                continue
            expr = c.get("expression", "")
            if not expr:
                continue
            if not re.search(rf"\b{re.escape(column_name)}\b", expr, re.IGNORECASE):
                continue
            col_checks.append(c)
            # Find cross-column references (other columns in the same expr).
            for other in all_columns:
                if other == column_name:
                    continue
                if re.search(rf"\b{re.escape(other)}\b", expr, re.IGNORECASE):
                    other_type = meta.column_types.get(other, "TEXT")
                    cross_column_refs.append((other, other_type))

        # Detect UNIQUE.
        is_unique = False
        for c in meta.constraints:
            if c.get("type") == "unique" and column_name in (c.get("columns") or []):
                is_unique = True
                break

        # Detect FK info.
        fk_info: FKInfo | None = None
        for fk in meta.foreign_keys:
            fk_cols = fk.get("columns") or []
            if column_name in fk_cols:
                ref_table = fk.get("ref_table", "")
                ref_cols = fk.get("ref_columns") or []
                fk_info = FKInfo(
                    ref_table=ref_table,
                    ref_column=ref_cols[0] if ref_cols else "",
                )
                break

        # derive_from sources/downstream are not available from schema
        # alone — they come from the current config. The HealOrchestrator
        # passes the config so heal_column() can enrich the context.
        # _build_column_context returns empty lists here; heal_column()
        # fills them in from the config.
        return ColumnContext(
            table_name=table_name,
            column_name=column_name,
            column_type=col_type,
            nullable=True,  # schema reflection doesn't expose this cleanly; safe default
            default=None,
            is_unique=is_unique,
            check_constraints=col_checks,
            derive_from_sources=[],
            derive_from_downstream=[],
            cross_column_refs=cross_column_refs,
            fk_info=fk_info,
        )

    def _enrich_with_config(
        self,
        context: ColumnContext,
        config: dict[str, Any],
    ) -> ColumnContext:
        """Enrich context with derive_from info from the current config."""
        for table_cfg in config.get("tables", []):
            if table_cfg.get("name") != context.table_name:
                continue
            for col in table_cfg.get("columns", []):
                col_name = col.get("name", "")
                # If this column derives from others, record sources.
                if col_name == context.column_name and col.get("derive_from"):
                    sources = col.get("derive_from")
                    if isinstance(sources, str):
                        sources = [sources]
                    for src in sources:
                        src_type = "TEXT"
                        # Look up source column type in the same table.
                        for c2 in table_cfg.get("columns", []):
                            if c2.get("name") == src:
                                # We don't have column_types in config; use
                                # the snapshot type if available (set by caller).
                                pass
                        context.derive_from_sources.append((src, src_type))
                # If another column derives from THIS column, record downstream.
                if col.get("derive_from"):
                    sources = col.get("derive_from")
                    if isinstance(sources, str):
                        sources = [sources]
                    if context.column_name in sources and col_name != context.column_name:
                        context.derive_from_downstream.append(col_name)
        return context

    def _build_prompt(
        self,
        context: ColumnContext,
        violation: ViolationReport,
    ) -> tuple[str, int]:
        """Build the column-level prompt. Returns (user_prompt, estimated_tokens)."""
        lines: list[str] = []
        lines.append(f"Table: {context.table_name}")
        lines.append(f"Column: {context.column_name}")
        lines.append(f"Type: {context.column_type}")
        lines.append(f"Nullable: {context.nullable}")
        lines.append(f"Unique: {context.is_unique}")
        if context.fk_info:
            lines.append(
                f"FK: references {context.fk_info.ref_table}({context.fk_info.ref_column})"
            )
        if context.check_constraints:
            lines.append("CHECK constraints:")
            for c in context.check_constraints:
                lines.append(f"  - {c.get('expression', '')}")
        if context.cross_column_refs:
            lines.append("Cross-column references:")
            for ref_name, ref_type in context.cross_column_refs:
                lines.append(f"  - {ref_name} ({ref_type})")
        if context.derive_from_sources:
            lines.append("derive_from sources:")
            for src_name, src_type in context.derive_from_sources:
                lines.append(f"  - {src_name} ({src_type})")
        if context.derive_from_downstream:
            lines.append(f"derive_from downstream: {context.derive_from_downstream}")
        lines.append(f"\nViolation: {violation.constraint_type.value} on {violation.columns}")
        if violation.message:
            lines.append(f"Message: {violation.message}")

        user_prompt = "\n".join(lines)
        estimated = len(_SYSTEM_PROMPT) // 4 + len(user_prompt) // 4
        return user_prompt, estimated

    def heal_column(
        self,
        table_name: str,
        column_name: str,
        violation: ViolationReport,
        config: dict[str, Any],
        snapshot: SchemaSnapshot,
    ) -> Level2Result:
        """Call LLM with column-level minimal dependency context.

        Returns Level2Result. Network errors are re-raised (Section 5.3).
        """
        context = self._build_column_context(table_name, column_name, snapshot)
        context = self._enrich_with_config(context, config)
        user_prompt, estimated = self._build_prompt(context, violation)
        start = time.monotonic()

        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 2 LLM call failed", column=column_name, error=str(exc))
            return Level2Result(
                success=False,
                column=column_name,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=estimated,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level2Result(
                success=False,
                column=column_name,
                raw_response=content,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        try:
            patch = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Level 2 LLM returned malformed JSON", column=column_name, error=str(exc))
            return Level2Result(
                success=False,
                column=column_name,
                raw_response=content,
                error=exc,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        return Level2Result(
            success=True,
            column=column_name,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=estimated,
        )
