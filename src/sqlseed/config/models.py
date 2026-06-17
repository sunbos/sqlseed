from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self


class ProviderType(str, Enum):
    BASE = "base"
    FAKER = "faker"
    MIMESIS = "mimesis"
    CUSTOM = "custom"


class ColumnConstraintsConfig(BaseModel):
    """列约束配置"""

    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = Field(default=100, ge=0)


class ColumnConfig(BaseModel):
    """
    列配置 — 支持源列和派生列两种模式。

    源列模式：指定 generator + params
    派生列模式：指定 derive_from + expression
    两者不能同时使用。

    支持从 dict 快捷构造：
      - "type" 作为 "generator" 的别名
      - 未知键自动归入 params
      - 嵌套 "params" 字典会被展平
    """

    name: str

    # === 源列模式 ===
    generator: str | None = None
    provider: ProviderType | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    null_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    # === 派生列模式 ===
    derive_from: str | None = None  # 源列名
    expression: str | None = None  # 派生表达式

    # === 约束 ===
    constraints: ColumnConstraintsConfig | None = None

    # === Native method overrides (from AI suggestions) ===
    faker_method: str | None = None
    mimesis_method: str | None = None
    native_params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def normalize_dict_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)

        if "type" in result and "generator" not in result:
            result["generator"] = result.pop("type")
        elif "type" in result and "generator" in result:
            result.pop("type")

        derive_from = result.get("derive_from")
        if derive_from:
            return result

        known_fields = set(cls.model_fields)
        nested_params = result.pop("params", None)

        extra_keys = {k: v for k, v in result.items() if k not in known_fields}
        for k in extra_keys:
            result.pop(k)

        merged_params: dict[str, Any] = {}
        if isinstance(nested_params, dict):
            merged_params.update(nested_params)
        merged_params.update(extra_keys)

        if merged_params:
            result["params"] = merged_params

        return result

    @model_validator(mode="after")
    def validate_column_mode(self) -> Self:
        if self.derive_from and self.generator:
            raise ValueError(f"Column '{self.name}': cannot use both 'generator' and 'derive_from'")
        if self.derive_from and not self.expression:
            raise ValueError(f"Column '{self.name}': 'derive_from' requires 'expression'")
        return self


class TableConfig(BaseModel):
    """单表生成配置"""

    name: str
    count: int = Field(default=1000, gt=0)
    batch_size: int = Field(default=5000, gt=0)
    columns: list[ColumnConfig] = Field(default_factory=list)
    clear_before: bool = False
    seed: int | None = None
    transform: str | None = None
    enrich: bool = False


class ColumnAssociation(BaseModel):
    """跨表列关联声明 — 用于隐式关联（同名列跨表引用）"""

    column_name: str
    source_table: str
    source_column: str | None = None
    target_tables: list[str] = Field(default_factory=list)
    strategy: Literal["shared_pool", "random"] = "shared_pool"


class GeneratorConfig(BaseModel):
    """全局生成配置"""

    db_path: str
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = Field(default_factory=list)
    associations: list[ColumnAssociation] = Field(default_factory=list)
    optimize_pragma: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    snapshot_dir: str | None = None
