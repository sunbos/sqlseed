from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self


class ProviderType(str, Enum):
    BASE = "base"
    FAKER = "faker"
    MIMESIS = "mimesis"
    CUSTOM = "custom"
    AI = "ai"


class ColumnConstraintsConfig(BaseModel):
    """列约束配置"""

    unique: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None
    regex: str | None = None
    max_retries: int = Field(default=100, gt=0)


class ColumnConfig(BaseModel):
    """
    列配置 — 支持源列和派生列两种模式。

    源列模式：指定 generator + params
    派生列模式：指定 derive_from + expression
    两者不能同时使用。
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

    @field_validator("null_ratio")
    @classmethod
    def validate_null_ratio(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("null_ratio must be between 0.0 and 1.0")
        return v

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
    strategy: str = "shared_pool"


class GeneratorConfig(BaseModel):
    """全局生成配置"""

    db_path: str
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = Field(default_factory=list)
    associations: list[ColumnAssociation] = Field(default_factory=list)
    optimize_pragma: bool = True
    log_level: str = "INFO"
    snapshot_dir: str | None = None
