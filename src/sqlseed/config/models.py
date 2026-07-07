"""sqlseed configuration model definitions.

Type-safe configuration models built on Pydantic, including:
- GeneratorConfig: Global generation configuration (connection target, provider, locale, etc.)
- TableConfig: Single-table generation configuration
- ColumnConfig: Column configuration (supports both source-column and derived-column modes)
- ColumnAssociation: Cross-table column association declaration
- ColumnConstraintsConfig: Column constraint configuration
- ProviderType: Data provider type enum
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class ProviderType(str, Enum):
    """Data provider type enumeration (base/faker/mimesis/custom)."""

    BASE = "base"
    FAKER = "faker"
    MIMESIS = "mimesis"
    CUSTOM = "custom"


class ColumnConstraintsConfig(BaseModel):
    """Column constraint configuration."""

    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = Field(
        default=100,
        ge=0,
        description="Maximum retry attempts for unique-constraint backtracking. "
        "Set to 0 to disable retries (the first generated value is kept even if it "
        "violates the unique constraint). Must be >= 0.",
    )


class ColumnConfig(BaseModel):
    """
    Column configuration — supports both source-column and derived-column modes.

    Source-column mode: specify generator + params
    Derived-column mode: specify derive_from + expression
    The two modes cannot be used together.

    Supports convenient construction from a dict:
      - "type" is treated as an alias for "generator"
      - Unknown keys are automatically merged into params
      - A nested "params" dict is flattened
    """

    name: str

    # === Source-column mode ===
    generator: str | None = None
    provider: ProviderType | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    null_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    # === Derived-column mode ===
    derive_from: str | list[str] | None = None  # source column name(s)
    expression: str | None = None  # derivation expression

    # === Constraints ===
    constraints: ColumnConstraintsConfig | None = None

    # === Native method overrides (from AI suggestions) ===
    faker_method: str | None = None
    mimesis_method: str | None = None
    native_params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_dict_input(cls, data: Any) -> Any:
        """Normalize dict input: treat 'type' as alias for 'generator' and merge unknown keys into params."""
        if not isinstance(data, dict):
            return data
        result = dict(data)

        if "type" in result and "generator" not in result:
            result["generator"] = result.pop("type")
        elif "type" in result and "generator" in result:
            # Both 'type' and 'generator' provided: 'type' is discarded.
            # Warn the user so they notice the silent drop.
            logger.warning(
                "Column has both 'type' and 'generator' specified; 'type' is ignored",
                column=result.get("name", "<unknown>"),
            )
            result.pop("type")

        derive_from = result.get("derive_from")
        if derive_from:
            return result

        known_fields = set(cls.model_fields)
        nested_params = result.pop("params", None)

        extra_keys = {k: v for k, v in result.items() if k not in known_fields}
        for k in extra_keys:
            result.pop(k)

        # Filter out Layer 4 internal metadata fields (e.g., _degraded,
        # degrade_reason) — these are ProgressiveDegrader markers used during
        # the auto-heal pipeline and must NOT be merged into params, otherwise
        # they get passed to generators as keyword arguments (e.g.,
        # ``_gen_string(_degraded=True)`` raises TypeError).
        _INTERNAL_FIELDS = {"_degraded", "degrade_reason"}
        extra_keys = {k: v for k, v in extra_keys.items() if k not in _INTERNAL_FIELDS}

        merged_params: dict[str, Any] = {}
        if isinstance(nested_params, dict):
            merged_params.update(nested_params)
        merged_params.update(extra_keys)

        if merged_params:
            result["params"] = merged_params

        return result

    @model_validator(mode="after")
    def validate_column_mode(self) -> Self:
        """Validate that source-column mode and derived-column mode are not mixed."""
        if self.derive_from and self.generator:
            raise ValueError(f"Column '{self.name}': cannot use both 'generator' and 'derive_from'")
        if self.derive_from and not self.expression:
            raise ValueError(f"Column '{self.name}': 'derive_from' requires 'expression'")
        return self


class TableConfig(BaseModel):
    """Single-table generation configuration"""

    name: str
    count: int = Field(default=1000, gt=0)
    batch_size: int = Field(default=5000, gt=0)
    columns: list[ColumnConfig] = Field(default_factory=list)
    clear_before: bool = False
    seed: int | None = None
    transform: str | None = None
    enrich: bool = False


class ColumnAssociation(BaseModel):
    """Cross-table column association declaration — used for implicit associations
    (same-name column references across tables)."""

    column_name: str
    source_table: str
    source_column: str | None = None
    target_tables: list[str] = Field(default_factory=list)
    strategy: Literal["shared_pool", "random"] = "shared_pool"


class ExactColumnMappingRule(BaseModel):
    """Exact-match custom column mapping rule (keyed by column name in a dict).

    Allows users to override the built-in exact-match mapping for specific
    column names without modifying core code or writing a plugin.
    """

    generator: str
    params: dict[str, Any] = Field(default_factory=dict)


class PatternColumnMappingRule(BaseModel):
    """Pattern-based custom column mapping rule.

    Allows users to override the built-in pattern-match mapping via regex
    without modifying core code or writing a plugin.
    """

    pattern: str
    generator: str
    params: dict[str, Any] = Field(default_factory=dict)


class CustomColumnMappings(BaseModel):
    """User-defined custom column mapping rules loaded from YAML config.

    These rules have higher priority than built-in exact/pattern match rules,
    allowing users to override incorrect mappings (e.g., ``file_name`` matching
    the ``*_name`` fallback) without modifying core code.

    Example YAML::

        custom_column_mappings:
          exact:
            tenant_id:
              generator: uuid
            file_name:
              generator: word
          pattern:
            - pattern: "^sku_.*"
              generator: uuid
            - pattern: ".*_name$"
              generator: word
    """

    exact: dict[str, ExactColumnMappingRule] = Field(default_factory=dict)
    pattern: list[PatternColumnMappingRule] = Field(default_factory=list)


class GeneratorConfig(BaseModel):
    """Global generation configuration.

    The connection target is specified via ``db_path`` (SQLite file path) or
    ``url`` (database URL); the two are mutually exclusive. At least one of
    them must be provided.
    """

    db_path: str | None = None
    url: str | None = None
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = Field(default_factory=list)
    associations: list[ColumnAssociation] = Field(default_factory=list)
    custom_column_mappings: CustomColumnMappings | None = None
    optimize_pragma: bool = True
    snapshot_dir: str | None = None
    # Deprecated: retained for backward compatibility with existing YAML/JSON configs.
    # The value is no longer used; configure logging via sqlseed._utils.logger.configure_logging().
    log_level: str | None = Field(
        default=None,
        deprecated=(
            "log_level is deprecated and no longer applied; configure logging via "
            "sqlseed._utils.logger.configure_logging() directly."
        ),
    )

    @model_validator(mode="after")
    def validate_connection_target(self) -> Self:
        """Validate that db_path and url are mutually exclusive and at least one is provided."""
        if self.db_path is not None and self.url is not None:
            raise ValueError("Cannot specify both 'db_path' and 'url'. Use one or the other.")
        if self.db_path is None and self.url is None:
            raise ValueError("Either 'db_path' or 'url' must be provided.")
        return self

    @property
    def connection_target(self) -> str:
        """Return the connection target string (db_path or url)."""
        if self.url is not None:
            return self.url
        if self.db_path is not None:
            return self.db_path
        raise RuntimeError("No connection target configured")
