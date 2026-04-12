from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProviderType(str, Enum):
    BASE = "base"
    FAKER = "faker"
    MIMESIS = "mimesis"
    CUSTOM = "custom"
    AI = "ai"


class ColumnConfig(BaseModel):
    name: str
    generator: str | None = None
    provider: ProviderType | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    null_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("null_ratio")
    @classmethod
    def validate_null_ratio(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("null_ratio must be between 0.0 and 1.0")
        return v


class TableConfig(BaseModel):
    name: str
    count: int = Field(default=1000, gt=0)
    batch_size: int = Field(default=5000, gt=0)
    columns: list[ColumnConfig] = Field(default_factory=list)
    clear_before: bool = False
    seed: int | None = None


class GeneratorConfig(BaseModel):
    db_path: str
    provider: ProviderType = ProviderType.MIMESIS
    locale: str = "en_US"
    tables: list[TableConfig] = Field(default_factory=list)
    optimize_pragma: bool = True
    log_level: str = "INFO"
    snapshot_dir: str | None = None
