"""Iterative refinement of AI-generated sqlseed configs.

This module hosts :class:`AiConfigRefiner`, which wraps a
:class:`~sqlseed_ai.analyzer.SchemaAnalyzer` and a database path, then drives
a retry loop that (1) asks the LLM for a config, (2) validates it against the
live schema via :class:`~sqlseed.core.orchestrator.DataOrchestrator`, and
(3) feeds validation errors back to the LLM until the config is valid or the
retry budget is exhausted. Successful configs are cached on disk keyed by a
schema hash so repeated runs skip the LLM round-trip.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError
from sqlseed_ai._json_utils import _sanitize_names
from sqlseed_ai.analyzer import SchemaAnalyzer
from sqlseed_ai.errors import ErrorSummary, summarize_error
from sqlseed_ai.exceptions import ContextOverflowError

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir
from sqlseed.config.models import TableConfig
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.generators._protocol import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlseed_ai.config import AIConfig

logger = get_logger(__name__)


class _RetryState:
    """Mutable state for the refinement retry loop."""

    __slots__ = ("last_error_type", "messages_history", "min_prompt_level", "same_error_count")

    def __init__(self) -> None:
        self.last_error_type: str | None = None
        self.same_error_count = 0
        self.messages_history: list[dict[str, str]] = []
        self.min_prompt_level: int = 0


class AISuggestionFailedError(RuntimeError):
    """Raised when AI config generation/refinement cannot produce a valid config.

    Inherits from :class:`RuntimeError` so that callers catching
    ``(ValueError, RuntimeError, OSError)`` (the standard recoverable-error
    tuple used across sqlseed-ai) also catch this exception without needing
    to import it explicitly.
    """


class AiConfigRefiner:
    """Refine AI-generated configs against a live database schema.

    The refiner orchestrates a multi-attempt loop: each attempt calls the LLM,
    validates the result with :class:`DataOrchestrator`, and on failure appends
    a refinement prompt so the next attempt can fix the reported error.
    Successful configs are cached on disk keyed by a schema hash.
    """

    def __init__(
        self,
        analyzer: SchemaAnalyzer,
        db_path: str,
        *,
        cache_dir: str | None = None,
    ) -> None:
        """Initialize the refiner.

        Args:
            analyzer: The :class:`SchemaAnalyzer` used for LLM calls.
            db_path: Path to the database file (or URL) to validate against.
            cache_dir: Optional override for the cache directory. Defaults to
                the sqlseed cache dir under ``ai_configs``.
        """
        self._analyzer = analyzer
        self._db_path = db_path
        self._cache_dir = Path(cache_dir) if cache_dir else get_cache_dir("ai_configs")

    @classmethod
    def from_config(
        cls,
        ai_config: AIConfig,
        db_path: str,
        *,
        cache_dir: str | None = None,
    ) -> AiConfigRefiner:
        """Create a refiner with an internally-constructed analyzer.

        Convenience factory for callers that don't need the
        :class:`SchemaAnalyzer` separately (e.g., MCP tools that only call
        ``generate_and_refine``). Callers that need the analyzer for other
        operations (e.g., CLI streaming display) should construct the
        analyzer explicitly and use the regular constructor.

        Args:
            ai_config: The AI configuration to build the analyzer from.
            db_path: Path to the database file (or URL) to validate against.
            cache_dir: Optional override for the cache directory.

        Returns:
            A new :class:`AiConfigRefiner` instance.
        """
        return cls(SchemaAnalyzer(config=ai_config), db_path, cache_dir=cache_dir)

    def _handle_generation_failure(self, error: ErrorSummary, attempt: int, max_retries: int) -> None:
        """Decide whether to retry or raise after an LLM generation failure.

        Args:
            error: Summary of the generation error.
            attempt: Current attempt index (0-based).
            max_retries: Maximum number of retries allowed.

        Raises:
            AISuggestionFailedError: If the error is non-retryable or the
                retry budget is exhausted.
        """
        if not error.retryable:
            raise AISuggestionFailedError(f"Non-retryable error: {error.message}")
        if attempt == max_retries:
            raise AISuggestionFailedError(f"Failed after {max_retries} retries. Last error: {error.message}")
        logger.info(
            "LLM API call failed, retrying",
            attempt=attempt + 1,
            max_retries=max_retries,
            error=error.message,
        )

    def _handle_validation_failure(self, error: ErrorSummary, attempt: int, max_retries: int, table_name: str) -> None:
        """Decide whether to retry or raise after a config validation failure.

        Args:
            error: Summary of the validation error.
            attempt: Current attempt index (0-based).
            max_retries: Maximum number of retries allowed.
            table_name: Name of the table being refined.

        Raises:
            AISuggestionFailedError: If the error is non-retryable or the
                retry budget is exhausted.
        """
        if not error.retryable:
            raise AISuggestionFailedError(f"Non-retryable error: {error.message}")

        if attempt == max_retries:
            logger.warning(
                "AI config refinement exhausted all retries",
                table_name=table_name,
                last_error=error.error_type,
            )
            raise AISuggestionFailedError(f"Failed after {max_retries} retries. Last error: {error.message}")

        logger.info(
            "AI config refinement attempt",
            attempt=attempt + 1,
            max_retries=max_retries,
            error_type=error.error_type,
            column=error.column,
        )

    _NON_RETRYABLE_ERRORS = frozenset({"empty_config", "json_syntax"})

    def _check_repeated_error(
        self,
        error: ErrorSummary,
        last_error_type: str | None,
        same_error_count: int,
    ) -> tuple[str, int]:
        """Detect repeated non-retryable errors and bail out early.

        Args:
            error: The current error summary.
            last_error_type: The error type from the previous attempt.
            same_error_count: How many times the previous error has repeated.

        Returns:
            Updated ``(error_type, same_error_count)`` tuple.

        Raises:
            AISuggestionFailedError: If the same non-retryable error repeats
                twice in a row (the model is unlikely to recover).
        """
        if error.error_type in self._NON_RETRYABLE_ERRORS:
            if error.error_type == last_error_type:
                same_error_count += 1
            else:
                same_error_count = 1  # Reset count when error type changes
            if same_error_count >= 2:
                raise AISuggestionFailedError(
                    f"Same error '{error.error_type}' repeated {same_error_count} times. "
                    f"The AI model may not support this task. "
                    f"Try a different model with --model. Last error: {error.message}"
                )
        return error.error_type, same_error_count

    def _get_prompt_levels(self, use_compact: bool) -> list[tuple[bool, bool]]:
        """Return prompt levels: (compact, ultra_compact) tuples."""
        if use_compact:
            return [(True, True)]
        return [(False, False), (True, False), (True, True)]

    def _resolve_use_compact(self, use_compact: bool | None) -> bool:
        """Auto-detect compact mode based on model size if not explicitly set."""
        if use_compact is not None:
            return use_compact
        return self._analyzer.config.should_use_ultra_compact() if self._analyzer.config else False

    def _try_prompt_levels(
        self,
        schema_ctx: Any,
        state: _RetryState,
        use_compact: bool,
        call_fn: Callable[[list[dict[str, str]]], dict[str, Any] | None],
    ) -> tuple[dict[str, Any] | None, ErrorSummary | None]:
        """Try LLM call across prompt levels with context overflow fallback.

        Args:
            schema_ctx: Schema context from the orchestrator.
            state: Mutable retry state (messages_history, min_prompt_level updated in-place).
            use_compact: Whether to force ultra-compact mode.
            call_fn: Function to call LLM (non-streaming or streaming variant).

        Returns:
            (config_dict or None, error or None)
        """
        prompt_levels = self._get_prompt_levels(use_compact)
        for level_idx, (compact, ultra) in enumerate(prompt_levels):
            if level_idx < state.min_prompt_level:
                continue
            initial_messages = self._analyzer.build_initial_messages(schema_ctx, compact=compact, ultra_compact=ultra)
            messages = initial_messages + state.messages_history
            try:
                config_dict = call_fn(messages)
                if not config_dict:
                    return None, ErrorSummary(
                        error_type="empty_config",
                        message="LLM returned empty result",
                        column=None,
                        retryable=True,
                    )
                # Apply Rule #14 (strip invalid generator params) before
                # validation. LLMs sometimes hallucinate params like
                # email's ``min_length``/``example`` that the generator
                # does not accept, causing ConfigurationError at
                # ``_validate_config``. The staged path applies Rule #14
                # in ``Stage3Validator.validate()``, but this refiner path
                # uses ``SchemaAnalyzer`` directly and would otherwise
                # skip Rule #14. Lazy import avoids circular dependency.
                self._apply_rule_14_param_stripping(config_dict)
                return config_dict, None
            except ContextOverflowError:
                if not ultra:
                    logger.info(
                        "Context overflow, retrying with shorter prompt",
                        compact=compact,
                        ultra_compact=ultra,
                    )
                    state.min_prompt_level = level_idx + 1
                    continue
                raise
            except (ValueError, RuntimeError, OSError) as e:
                return None, summarize_error(e)
        return None, None

    def _apply_rule_14_param_stripping(self, config_dict: dict[str, Any]) -> None:
        """Apply Rule #14 (strip invalid generator params) in-place.

        Delegates to ``Stage3Validator._apply_rule_14_strip_invalid_params``
        so the refiner path stays consistent with the staged path. Handles
        both single-table ``{"name": ...}`` and multi-table
        ``{"tables": [...]}`` shapes.

        Lazy import avoids a circular dependency at module load time
        (``staged_analyzer`` imports from ``schema_analyzer`` which is
        imported by ``refiner``).
        """
        from sqlseed_ai.staged_analyzer import Stage3Validator

        validator = Stage3Validator()
        if "tables" in config_dict:
            tables = config_dict["tables"]
        elif "name" in config_dict:
            tables = [config_dict]
        else:
            return
        for table in tables:
            if not isinstance(table, dict):
                continue
            for col in table.get("columns", []):
                if isinstance(col, dict):
                    validator._apply_rule_14_strip_invalid_params(col)

    def _handle_validation_result(
        self,
        orch: DataOrchestrator,
        table_name: str,
        schema_hash: str,
        config_dict: dict[str, Any],
        attempt: int,
        max_retries: int,
        state: _RetryState,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any] | None:
        """Handle validation result: return config on success, or update retry state.

        Returns:
            config_dict if valid, None if validation failed (state updated for next retry).
        """
        val_error = self._validate_config(orch, table_name, config_dict)

        if val_error is None:
            logger.info("AI config validated successfully", table_name=table_name, attempts=attempt + 1)
            self._cache_successful_config(table_name, config_dict, schema_hash)
            if on_progress:
                on_progress("done", {"tokens": 0, "model": "validated"})
            return config_dict

        state.last_error_type, state.same_error_count = self._check_repeated_error(
            val_error, state.last_error_type, state.same_error_count
        )
        self._handle_validation_failure(val_error, attempt, max_retries, table_name)

        state.messages_history.append({"role": "assistant", "content": json.dumps(config_dict, ensure_ascii=False)})
        state.messages_history.append(
            {"role": "user", "content": self._build_refinement_prompt(val_error, attempt, max_retries)}
        )
        return None

    def _run_refinement_loop(
        self,
        orch: DataOrchestrator,
        table_name: str,
        schema_ctx: Any,
        schema_hash: str,
        max_retries: int,
        no_cache: bool,
        use_compact: bool | None,
        call_fn: Callable[[list[dict[str, str]]], dict[str, Any] | None],
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Shared refinement loop for both streaming and non-streaming paths.

        Args:
            orch: DataOrchestrator instance for schema access and validation.
            table_name: Name of the table to generate config for.
            schema_ctx: Schema context from the orchestrator.
            schema_hash: Hash of the table schema for cache invalidation.
            max_retries: Maximum number of refinement retries.
            no_cache: If True, skip cache lookup.
            use_compact: If set, force/override compact mode; None for auto-detect.
            call_fn: Function that takes messages and returns config dict or raises.
            on_progress: Optional progress callback (streaming only).
        """
        if not no_cache:
            cached = self.get_cached_config(table_name, schema_hash)
            if cached is not None:
                logger.info("Using cached AI config", table_name=table_name)
                if on_progress:
                    on_progress("done", {"tokens": 0, "model": "cached"})
                return cached

        resolved_compact = self._resolve_use_compact(use_compact)
        state = _RetryState()

        for attempt in range(max_retries + 1):
            if on_progress:
                on_progress("refining", {"attempt": attempt, "max_retries": max_retries})

            config_dict, error = self._try_prompt_levels(schema_ctx, state, resolved_compact, call_fn)

            if config_dict is None:
                if error is not None:
                    state.last_error_type, state.same_error_count = self._check_repeated_error(
                        error, state.last_error_type, state.same_error_count
                    )
                    self._handle_generation_failure(error, attempt, max_retries)
                continue

            # config_dict is not None -- validate it
            if on_progress:
                on_progress("validating", {"attempt": attempt})

            result = self._handle_validation_result(
                orch,
                table_name,
                schema_hash,
                config_dict,
                attempt,
                max_retries,
                state,
                on_progress,
            )
            if result is not None:
                return result

        raise AISuggestionFailedError("Unexpected state")

    def generate_and_refine(
        self,
        table_name: str,
        *,
        max_retries: int = 3,
        no_cache: bool = False,
        use_compact: bool | None = None,
    ) -> dict[str, Any]:
        """Generate and refine an AI config for a table (non-streaming).

        Args:
            table_name: Name of the table to generate a config for.
            max_retries: Maximum number of refinement retries.
            no_cache: If True, skip cache lookup and storage.
            use_compact: If set, force/override compact mode; None for auto-detect.

        Returns:
            Validated config dict.
        """
        with DataOrchestrator(self._db_path) as orch:
            schema_hash = self._compute_schema_hash(orch, table_name)
            schema_ctx = orch.get_schema_context(table_name)

            def _call_non_streaming(messages: list[dict[str, str]]) -> dict[str, Any] | None:
                return self._analyzer.call_llm(messages)

            return self._run_refinement_loop(
                orch,
                table_name,
                schema_ctx,
                schema_hash,
                max_retries=max_retries,
                no_cache=no_cache,
                use_compact=use_compact,
                call_fn=_call_non_streaming,
            )

    def generate_and_refine_streaming(
        self,
        table_name: str,
        *,
        max_retries: int = 3,
        no_cache: bool = False,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
        use_compact: bool | None = None,
    ) -> dict[str, Any]:
        """Streaming version of generate_and_refine with progress callbacks and
        context-size-aware prompt downgrading (normal -> compact -> ultra-compact).
        """
        with DataOrchestrator(self._db_path) as orch:
            schema_hash = self._compute_schema_hash(orch, table_name)
            schema_ctx = orch.get_schema_context(table_name)

            def _call_streaming(messages: list[dict[str, str]]) -> dict[str, Any] | None:
                return self._analyzer.call_llm_streaming(messages, on_progress=on_progress)

            return self._run_refinement_loop(
                orch,
                table_name,
                schema_ctx,
                schema_hash,
                max_retries=max_retries,
                no_cache=no_cache,
                use_compact=use_compact,
                call_fn=_call_streaming,
                on_progress=on_progress,
            )

    def _compute_schema_hash(self, orch: DataOrchestrator, table_name: str) -> str:
        """Compute a stable hash of the table's column set for cache keys.

        Args:
            orch: Orchestrator with access to the live schema.
            table_name: Name of the table to hash.

        Returns:
            Truncated SHA-256 hex digest (16 chars) of the sorted column names.
        """
        column_names = orch.get_column_names(table_name)
        raw = "|".join(sorted(column_names))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _validate_config(
        self,
        orch: DataOrchestrator,
        table_name: str,
        config_dict: dict[str, Any],
    ) -> ErrorSummary | None:
        """Validate an AI-generated config against the live schema.

        Args:
            orch: Orchestrator used for column lookups and preview.
            table_name: Name of the table the config targets.
            config_dict: The AI-generated config to validate.

        Returns:
            :class:`ErrorSummary` describing the first validation failure,
            or ``None`` if the config is valid.
        """
        try:
            table_config = TableConfig(**config_dict)
        except PydanticValidationError as e:
            return summarize_error(e)

        actual_columns = orch.get_column_names(table_name)
        skippable_cols = orch.get_skippable_columns(table_name)
        suggestable_cols = actual_columns - skippable_cols

        for col_cfg in table_config.columns:
            if col_cfg.name not in actual_columns:
                return ErrorSummary(
                    error_type="column_mismatch",
                    message=(
                        f"Column '{col_cfg.name}' does not exist in table "
                        f"'{table_name}'. Available columns: "
                        f"{sorted(actual_columns)}"
                    ),
                    column=col_cfg.name,
                    retryable=True,
                )

        if suggestable_cols and len(table_config.columns) == 0:
            return ErrorSummary(
                error_type="empty_config",
                message=(
                    f"No column suggestions provided for table '{table_name}'. "
                    f"There are {len(suggestable_cols)} suggestable columns: "
                    f"{sorted(suggestable_cols)}. "
                    "Please provide generator suggestions for at least the "
                    "non-default, non-autoincrement columns."
                ),
                column=None,
                retryable=True,
            )

        # Pre-check: reject generators assigned to GENERATED/computed columns.
        # The mapper silently skips computed columns (via is_computed), so
        # preview_data will never contain them — making the downstream dry-run
        # insert unable to detect this class of misconfiguration. We surface
        # it explicitly here by reflecting the schema before preview.
        computed_err = self._check_computed_column_assignments(orch, table_name, table_config)
        if computed_err is not None:
            return computed_err

        try:
            preview_data = orch.preview_table(
                table_name=table_name,
                # Use 50 rows (not 5) so UNIQUE collisions on long-string
                # generators (e.g., bare "text" producing ~50-char sentences)
                # surface during validation rather than failing the full load.
                count=50,
                column_configs=table_config.columns,
            )
        except (ValueError, RuntimeError, OSError, ConfigurationError) as e:
            return summarize_error(e)

        # Transactional dry-run insert validation to catch DB-level constraints
        # (CHECK, UNIQUE, NOT NULL, VARCHAR length) that preview cannot detect.
        # Note: GENERATED/computed columns are already filtered out of preview_data
        # by the mapper, so the dry-run insert will not attempt to write to them.
        db_adapter = getattr(orch, "_db", None)
        if db_adapter and preview_data:
            engine = getattr(db_adapter, "_engine", None)
            if engine is not None:
                try:
                    from sqlalchemy import MetaData, String, Table

                    metadata = MetaData()
                    table = Table(table_name, metadata, autoload_with=engine)

                    # Pre-validate VARCHAR length constraints in Python to surface
                    # the precise column name to the AI (DB error messages vary by dialect).
                    for row in preview_data:
                        for col in table.columns:
                            val = row.get(col.name)
                            if (
                                val is not None
                                and isinstance(col.type, String)
                                and col.type.length is not None
                                and len(str(val)) > col.type.length
                            ):
                                raise ValueError(
                                    f"Column '{col.name}' value '{val}' is too long "
                                    f"for type character varying({col.type.length})"
                                )

                    # Transactional dry-run insert (for DB-level CHECK/UNIQUE constraints)
                    with engine.connect() as conn:
                        transaction = conn.begin()
                        try:
                            conn.execute(table.insert(), preview_data)
                        finally:
                            transaction.rollback()
                except Exception as e:
                    err_msg = str(e).lower()
                    is_fk_error = False

                    # Detect PostgreSQL foreign key violation code (23503) or generic message
                    pgcode = getattr(e, "pgcode", None)
                    if pgcode == "23503" or "foreign key" in err_msg or "foreignkey" in err_msg:
                        is_fk_error = True

                    if not is_fk_error:
                        return summarize_error(e)

        return None

    def _check_computed_column_assignments(
        self,
        orch: DataOrchestrator,
        table_name: str,
        table_config: TableConfig,
    ) -> ErrorSummary | None:
        """Reject AI configs that assign generators to GENERATED/computed columns.

        Computed columns (``GENERATED ALWAYS AS (...) STORED/VIRTUAL``) are
        auto-calculated by the database and cannot be inserted. The mapper
        silently skips them, so preview_data never contains their values —
        making the dry-run insert unable to detect this misconfiguration.

        This pre-check reflects the schema via SQLAlchemy and surfaces an
        explicit error to the AI so it can remove the offending column from
        its config on the next refinement attempt.

        Args:
            orch: Orchestrator with the live database connection.
            table_name: Name of the table being validated.
            table_config: The AI-generated table config to check.

        Returns:
            :class:`ErrorSummary` if a generator is assigned to a computed
            column, otherwise ``None``.
        """
        db_adapter = getattr(orch, "_db", None)
        if db_adapter is None:
            return None
        engine = getattr(db_adapter, "_engine", None)
        if engine is None:
            # RawSQLiteAdapter (test-only) — skip this pre-check.
            return None

        try:
            from sqlalchemy import MetaData, Table

            metadata = MetaData()
            reflected = Table(table_name, metadata, autoload_with=engine)
            computed_cols = {col.name for col in reflected.columns if getattr(col, "computed", None) is not None}
        except Exception:
            # Reflection failed — skip this pre-check and rely on preview-based validation.
            return None

        if not computed_cols:
            return None

        for col_cfg in table_config.columns:
            if col_cfg.name in computed_cols:
                return ErrorSummary(
                    error_type="computed_column_assignment",
                    message=(
                        f"Column '{col_cfg.name}' is a GENERATED/computed column "
                        f"and cannot have a generator assigned. Computed columns "
                        f"are auto-calculated by the database from the expression "
                        f"in the schema. Remove '{col_cfg.name}' from the columns "
                        f"list. Computed columns in '{table_name}': {sorted(computed_cols)}"
                    ),
                    column=col_cfg.name,
                    retryable=True,
                )
        return None

    def _build_refinement_prompt(
        self,
        error: ErrorSummary,
        attempt: int,
        max_retries: int,
    ) -> str:
        """Build the user-message prompt asking the LLM to fix a validation error.

        Args:
            error: The validation error to surface to the model.
            attempt: Current attempt index (0-based).
            max_retries: Maximum number of retries allowed.

        Returns:
            Refinement prompt string.
        """
        parts = [
            "Your previous configuration contained an error. Please fix it.",
            "",
            "## Error Details",
            error.to_prompt_str(),
            "",
            "## Instructions",
            "- Only fix the column(s) mentioned in the error.",
            "- Do NOT modify other column configurations that were working correctly.",
            "- Return the COMPLETE configuration JSON with only the problematic parts corrected.",
            "- If you are unsure how to fix the error, use 'string' generator as a safe fallback.",
        ]

        if error.message and ("too long" in error.message.lower() or "varying" in error.message.lower()):
            parts.append(
                "- TIP: For varchar/character varying length errors, "
                "use the 'string' generator with 'params: {\"min_length\": 1, \"max_length\": N}' "
                "where N is within the database column length limit."
            )

        parts.extend(
            [
                "",
                f"This is refinement attempt {attempt + 1} of {max_retries}.",
            ]
        )

        if attempt >= max_retries - 1:
            parts.append("WARNING: This is the LAST attempt. Use the simplest possible generators to ensure validity.")

        return "\n".join(parts)

    def _cache_successful_config(
        self,
        table_name: str,
        config_dict: dict[str, Any],
        schema_hash: str,
    ) -> None:
        """Persist a successful config to disk keyed by table name and schema hash.

        Args:
            table_name: Name of the table the config targets.
            config_dict: The validated config to cache.
            schema_hash: Hash of the table schema for invalidation.
        """
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._cache_dir / f"{table_name}.json"
            entry = {
                "_meta": {
                    "schema_hash": schema_hash,
                    "created_at": time.time(),
                },
                "config": config_dict,
            }
            cache_file.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug(
                "Cached AI config",
                table_name=table_name,
                path=str(cache_file),
                schema_hash=schema_hash,
            )
        except OSError as e:
            logger.debug("Failed to cache AI config", error=str(e))

    def get_cached_config(
        self,
        table_name: str,
        schema_hash: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve a previously cached config for the table, if still valid.

        Args:
            table_name: Name of the table to look up.
            schema_hash: Expected schema hash. If provided and the cached
                entry's hash differs, the cache is treated as invalid.

        Returns:
            Cached config dict, or ``None`` if no valid cache exists.
        """
        cache_file = self._cache_dir / f"{table_name}.json"
        if cache_file.exists():
            try:
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(entry, dict) and "_meta" in entry:
                    cached_hash = entry["_meta"].get("schema_hash", "")
                    if schema_hash and cached_hash != schema_hash:
                        logger.debug(
                            "Cache schema hash mismatch, invalidating",
                            table_name=table_name,
                            cached_hash=cached_hash,
                            current_hash=schema_hash,
                        )
                        return None
                    config = entry.get("config")
                    if isinstance(config, dict):
                        _sanitize_names(config)
                    return config
                return entry if isinstance(entry, dict) else None
            except (OSError, ValueError) as e:
                logger.debug("Failed to read AI config cache", error=str(e))
        return None
