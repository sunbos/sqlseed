"""AI suggestion mediator — applies LLM-derived column mappings to specs.

This module is the home of ``apply_ai_suggestions``, moved out of
``sqlseed.core.plugin_mediator`` per ARCHITECTURE.md Section 7.6 ("Only
AI-specific mediation moves out"). It is the implementation behind the
high-level ``sqlseed_apply_ai_suggestions`` pluggy hook.

Responsibilities:
1. Decide whether AI is needed (unmatched ``string`` columns).
2. Build the analysis context (FKs, indexes, sample data) from the
   core ``DatabaseAdapter`` / ``SchemaInferrer``.
3. Invoke the ``analyze_fn`` callable (which is wired to the
   ``sqlseed_ai_analyze_table`` pluggy hook by the caller).
4. Merge the AI-returned column configs into ``specs`` as
   ``GeneratorSpec`` instances, skipping columns the user already
   configured.

The mediator does NOT own the LLM client — that lives in
``SchemaAnalyzer``. It only orchestrates the call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import OperationalError as SAOperationalError

from sqlseed._utils.logger import get_logger
from sqlseed.core.mapper import GeneratorSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed.core.schema import SchemaInferrer
    from sqlseed.database._protocol import DatabaseAdapter

logger = get_logger(__name__)


# Generators that the AI is allowed to override. ``string`` is the
# column mapper's type-faithful fallback (i.e., "no built-in rule
# matched"), so AI suggestions only apply to those columns. Other
# generators (email, integer, uuid, ...) were matched by a built-in
# rule and should not be replaced by AI output.
AI_APPLICABLE_GENERATORS: frozenset[str] = frozenset({"string"})


def _has_unmatched_cols(
    column_infos: list[Any],
    specs: dict[str, GeneratorSpec],
) -> bool:
    """Return True if any AI-applicable column still needs a suggestion."""
    return any(
        specs.get(col.name) is not None
        and specs[col.name].generator_name in AI_APPLICABLE_GENERATORS
        and not col.is_primary_key
        and not col.is_autoincrement
        and col.default is None
        for col in column_infos
    )


def _process_single_ai_column(
    col_cfg: dict[str, Any],
    specs: dict[str, GeneratorSpec],
) -> None:
    """Merge a single AI-suggested column config into ``specs``."""
    col_name = col_cfg.get("name")
    if not col_name or col_name not in specs:
        return

    gen = col_cfg.get("generator")
    if not gen or gen == "skip":
        return

    derive_from = col_cfg.get("derive_from")
    expression = col_cfg.get("expression")

    if derive_from and expression:
        specs[col_name] = GeneratorSpec(
            generator_name="__derive__",
            params={"derive_from": derive_from, "expression": expression},
        )
    else:
        params = col_cfg.get("params", {})
        if isinstance(params, dict):
            specs[col_name] = GeneratorSpec(
                generator_name=gen,
                params=params,
                native_faker_method=col_cfg.get("faker_method"),
                native_mimesis_method=col_cfg.get("mimesis_method"),
                native_params=col_cfg.get("native_params"),
            )


def _process_ai_result(
    ai_result: Any,
    specs: dict[str, GeneratorSpec],
    configured: set[str] | None = None,
) -> None:
    """Merge an AI analysis result dict into ``specs``."""
    if not ai_result or not isinstance(ai_result, dict):
        return

    skip = configured or set()
    ai_columns = ai_result.get("columns", [])
    if not isinstance(ai_columns, list):
        return

    for col_cfg in ai_columns:
        if isinstance(col_cfg, dict):
            col_name = col_cfg.get("name")
            if col_name and col_name in skip:
                continue
            _process_single_ai_column(col_cfg, specs)


def _build_ai_context(
    db: DatabaseAdapter,
    schema: SchemaInferrer,
    table_name: str,
) -> dict[str, Any] | None:
    """Build the context dict passed to the LLM analysis hook."""
    try:
        fks = db.get_foreign_keys(table_name)
        indexes = schema.get_index_info(table_name)
        return {
            "foreign_keys": fks,
            "all_table_names": db.get_table_names(),
            "indexes": [{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
            "sample_data": schema.get_sample_data(table_name, limit=5),
        }
    except (ValueError, RuntimeError, OSError, ImportError, SAOperationalError) as e:
        logger.debug("AI context not available", table_name=table_name, error=str(e))
        return None


def apply_ai_suggestions(
    *,
    analyze_fn: Callable[..., Any],
    db: DatabaseAdapter,
    schema: SchemaInferrer,
    table_name: str,
    column_infos: list[Any],
    specs: dict[str, GeneratorSpec],
    user_configured_columns: set[str] | None = None,
) -> dict[str, GeneratorSpec]:
    """Apply AI-driven suggestions to ``specs`` in place; return ``specs``.

    This is the implementation behind the ``sqlseed_apply_ai_suggestions``
    pluggy hook. It is a no-op when no AI-applicable column exists or when
    the analysis context cannot be built (e.g., schema read failure).

    Args:
        analyze_fn: Callable that performs the LLM analysis. Wired to the
            ``sqlseed_ai_analyze_table`` pluggy hook by the caller (the
            ``AISqlseedPlugin.sqlseed_apply_ai_suggestions`` hookimpl
            passes ``self.sqlseed_ai_analyze_table`` here). Accepts the
            same kwargs as that hook and returns its result dict (or
            None).
        db: Core ``DatabaseAdapter`` (for FK and table-name lookup).
        schema: Core ``SchemaInferrer`` (for index and sample-data lookup).
        table_name: Target table name.
        column_infos: ``ColumnInfo`` list for the table.
        specs: Mapping of column name to ``GeneratorSpec`` (modified in
            place).
        user_configured_columns: Optional set of column names the user
            explicitly configured; AI must not override these.

    Returns:
        The (possibly mutated) ``specs`` dict.
    """
    if not _has_unmatched_cols(column_infos, specs):
        return specs

    ctx = _build_ai_context(db, schema, table_name)
    if ctx is None:
        return specs

    ai_result = analyze_fn(
        table_name=table_name,
        columns=column_infos,
        indexes=ctx["indexes"],
        sample_data=ctx["sample_data"],
        foreign_keys=ctx["foreign_keys"],
        all_table_names=ctx["all_table_names"],
    )

    configured = user_configured_columns or set()
    _process_ai_result(ai_result, specs, configured)

    return specs


__all__ = [
    "AI_APPLICABLE_GENERATORS",
    "apply_ai_suggestions",
]
