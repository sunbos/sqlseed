from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger
from sqlseed_ai.errors import ErrorSummary, summarize_error

if TYPE_CHECKING:
    from sqlseed_ai.analyzer import SchemaAnalyzer

logger = get_logger(__name__)


class AISuggestionFailedError(Exception):
    pass


class AiConfigRefiner:

    def __init__(
        self,
        analyzer: SchemaAnalyzer,
        db_path: str,
        *,
        cache_dir: str | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._db_path = db_path
        self._cache_dir = Path(cache_dir) if cache_dir else Path(".sqlseed_cache/ai_configs")

    def generate_and_refine(
        self,
        table_name: str,
        *,
        max_retries: int = 3,
        no_cache: bool = False,
    ) -> dict[str, Any]:
        from sqlseed.core.orchestrator import DataOrchestrator

        with DataOrchestrator(self._db_path) as orch:
            schema_hash = self._compute_schema_hash(orch, table_name)

            if not no_cache:
                cached = self.get_cached_config(table_name, schema_hash)
                if cached is not None:
                    logger.info("Using cached AI config", table_name=table_name)
                    return cached

            schema_ctx = orch.get_schema_context(table_name)

            messages = self._analyzer.build_initial_messages(
                table_name=schema_ctx["table_name"],
                columns=schema_ctx["columns"],
                indexes=schema_ctx["indexes"],
                sample_data=schema_ctx["sample_data"],
                foreign_keys=schema_ctx["foreign_keys"],
                all_table_names=schema_ctx["all_table_names"],
                distribution_profiles=schema_ctx.get("distribution"),
            )

            for attempt in range(max_retries + 1):
                try:
                    config_dict = self._analyzer.call_llm(messages)
                except Exception as e:
                    error = summarize_error(e)
                    if not error.retryable:
                        raise AISuggestionFailedError(
                            f"Non-retryable error: {error.message}"
                        ) from e
                    if attempt == max_retries:
                        raise AISuggestionFailedError(
                            f"Failed after {max_retries} retries. Last error: {error.message}"
                        ) from e
                    messages.append({
                        "role": "user",
                        "content": self._build_refinement_prompt(error, attempt, max_retries),
                    })
                    continue

                error = self._validate_config(orch, table_name, config_dict)

                if error is None:
                    logger.info(
                        "AI config validated successfully",
                        table_name=table_name,
                        attempts=attempt + 1,
                    )
                    self._cache_successful_config(table_name, config_dict, schema_hash)
                    return config_dict

                if not error.retryable:
                    raise AISuggestionFailedError(
                        f"Non-retryable error: {error.message}"
                    )

                if attempt == max_retries:
                    logger.warning(
                        "AI config refinement exhausted all retries",
                        table_name=table_name,
                        last_error=error.error_type,
                    )
                    raise AISuggestionFailedError(
                        f"Failed after {max_retries} retries. Last error: {error.message}"
                    )

                logger.info(
                    "AI config refinement attempt",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error_type=error.error_type,
                    column=error.column,
                )

                messages.append({
                    "role": "assistant",
                    "content": json.dumps(config_dict, ensure_ascii=False),
                })
                messages.append({
                    "role": "user",
                    "content": self._build_refinement_prompt(error, attempt, max_retries),
                })

        raise AISuggestionFailedError("Unexpected state")

    def _compute_schema_hash(self, orch: Any, table_name: str) -> str:
        column_names = orch.get_column_names(table_name)
        raw = "|".join(sorted(column_names))
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _validate_config(
        self,
        orch: Any,
        table_name: str,
        config_dict: dict[str, Any],
    ) -> ErrorSummary | None:
        from sqlseed.config.models import TableConfig

        try:
            table_config = TableConfig(**config_dict)
        except Exception as e:
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

        try:
            orch.preview_table(
                table_name=table_name,
                count=5,
                column_configs=table_config.columns,
            )
        except Exception as e:
            return summarize_error(e)

        return None

    def _build_refinement_prompt(
        self,
        error: ErrorSummary,
        attempt: int,
        max_retries: int,
    ) -> str:
        parts = [
            "Your previous configuration contained an error. Please fix it.",
            "",
            "## Error Details",
            error.to_prompt_str(),
            "",
            "## Instructions",
            "- Only fix the column(s) mentioned in the error.",
            "- Do NOT modify other column configurations that were working correctly.",
            "- Return the COMPLETE configuration JSON "
            "with only the problematic parts corrected.",
            "- If you are unsure how to fix the error, "
            "use 'string' generator as a safe fallback.",
            "",
            f"This is refinement attempt {attempt + 1} of {max_retries}.",
        ]

        if attempt >= max_retries - 1:
            parts.append(
                "WARNING: This is the LAST attempt. "
                "Use the simplest possible generators to ensure validity."
            )

        return "\n".join(parts)

    def _cache_successful_config(
        self,
        table_name: str,
        config_dict: dict[str, Any],
        schema_hash: str,
    ) -> None:
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
        except Exception as e:
            logger.debug("Failed to cache AI config", error=str(e))

    def get_cached_config(
        self,
        table_name: str,
        schema_hash: str | None = None,
    ) -> dict[str, Any] | None:
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
                    return entry.get("config")
                return entry
            except Exception:
                pass
        return None
