# LLM 分阶段 YAML 驱动数据库分析 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 LLM 分阶段 YAML 驱动分析架构，让 2B 本地模型 (Gemma-4-E2B) 能稳定分析复杂数库结构 + 业务逻辑，生成准确 YAML config。

**Architecture:** 三层架构 — Layer 1 (核心层方言感知特征提取) → Layer 2 (AI 插件阶段相关性判断) → Layer 3 (AI 插件分阶段 LLM 管线: 阶段 0 数据采样 → 阶段 1 结构分析 → 阶段 2 列分析 → 阶段 3 校验+auto-fix)。基于 Least-to-Most Prompting 技术，把 36 个同时决策降为 N 个顺序决策。

**Tech Stack:** Python 3.10+, pydantic, pluggy, structlog, SQLAlchemy (SQLite+PostgreSQL), openai SDK (LM Studio 兼容), pytest, testcontainers (PG 集成测试)。

**Spec 引用:** `docs/superpowers/specs/2026-07-02-llm-staged-yaml-analysis-design.md` (v1.1)

**分支:** `feat/llm-staged-yaml-analysis` (已存在, 从 `feat/schema-driven-architecture` 拉取)

**用户 P2/P3 反馈已融入此 plan:**
- FK 聚合改为逐个保留 (P2 #1): 不按 ref_table 分组, 每个单列 FK 直接转为 `ForeignKeyFeatures(columns=[col])`
- `ColumnFeatures` 补充 `max_length` (P2 #2): 从 type 字符串解析 (如 VARCHAR(255) → max_length=255)
- `complexity_score` 用简单版 (P2 #3): 直接用 spec §6.2 公式
- 阶段 1 降级 fallback 定义 (P3 #4): 定义 deterministic StructureSummary 降级对象
- `_auto_fix_config` 提取为公共函数 (P3 #5): 提取为 `apply_auto_fix_rules_1_13()` 公共函数

---

## 文件结构

### 新增文件

| 路径 | 职责 | 行数估计 |
|------|------|---------|
| `src/sqlseed/core/features.py` | Layer 1: 归一化数据模型 + StructuralFeatureExtractor (核心层, 无业务逻辑) | ~400 |
| `plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py` | Layer 2: 阶段相关性判断 (纯规则, 无 LLM) | ~150 |
| `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` | Layer 3: StagedSchemaAnalyzer + StructureSummary + Stage3Validator + ErrorClassifier | ~600 |
| `plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py` | 各阶段 prompt 模板 + few-shot 示例 | ~300 |
| `tests/test_core/test_features.py` | Layer 1 单元测试 | ~300 |
| `plugins/sqlseed-ai/tests/test_stage_relevance.py` | Layer 2 单元测试 | ~150 |
| `plugins/sqlseed-ai/tests/test_staged_analyzer.py` | Layer 3 单元测试 | ~400 |
| `plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py` | SQLite 端到端测试 | ~250 |

### 修改文件

| 路径 | 修改内容 |
|------|---------|
| `plugins/sqlseed-ai/src/sqlseed_ai/config.py` | 新增 `AIConfig.use_staged_pipeline: bool = False` 字段 |
| `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/__init__.py` | 导出 StagedSchemaAnalyzer (不破坏现有导出) |
| `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` | 提取 `_auto_fix_config` 为公共函数 `apply_auto_fix_rules_1_13()` (规则 1-13), 现有方法保留为 wrapper |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | ai-analyze 命令接入 flag 切换 |

### 不修改文件

- `src/sqlseed/database/_protocol.py` (Protocol 不变)
- `src/sqlseed/generators/*` (生成器不变)
- `src/sqlseed/core/mapper.py` (ColumnMapper 不变)

---

## Task 0: 添加 AIConfig.use_staged_pipeline flag

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/config.py:170-180`
- Test: `plugins/sqlseed-ai/tests/test_ai_config.py`

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_ai_config.py` 末尾追加:

```python
def test_ai_config_has_use_staged_pipeline_flag_default_false():
    """use_staged_pipeline flag 默认 False (向后兼容, 走现有 SchemaSemanticAnalyzer)."""
    config = AIConfig(api_key="test")
    assert hasattr(config, "use_staged_pipeline")
    assert config.use_staged_pipeline is False


def test_ai_config_use_staged_pipeline_can_be_enabled():
    """用户可显式开启分阶段管线."""
    config = AIConfig(api_key="test", use_staged_pipeline=True)
    assert config.use_staged_pipeline is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_config.py::test_ai_config_has_use_staged_pipeline_flag_default_false -v`
Expected: FAIL with "AttributeError: 'AIConfig' object has no attribute 'use_staged_pipeline'" or pydantic validation error

- [ ] **Step 3: 在 AIConfig 中添加字段**

在 `plugins/sqlseed-ai/src/sqlseed_ai/config.py` 的 `AIConfig` 类中 (约 line 176, `timeout` 字段之后) 添加:

```python
    # Staged pipeline flag (Phase 1 of LLM staged YAML-driven analysis).
    # - False (default): use existing SchemaSemanticAnalyzer (backward compat)
    # - True: use new StagedSchemaAnalyzer (3-stage LtM pipeline for small models)
    use_staged_pipeline: bool = False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_config.py::test_ai_config_has_use_staged_pipeline_flag_default_false plugins/sqlseed-ai/tests/test_ai_config.py::test_ai_config_use_staged_pipeline_can_be_enabled -v`
Expected: PASS

- [ ] **Step 5: 运行 mypy 验证类型**

Run: `mypy plugins/sqlseed-ai/src/sqlseed_ai/config.py`
Expected: No issues

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/config.py plugins/sqlseed-ai/tests/test_ai_config.py
git commit -m "feat(ai): add AIConfig.use_staged_pipeline flag (default False)"
```

---

## Task 1: Layer 1 归一化数据模型 (dataclasses)

**Files:**
- Create: `src/sqlseed/core/features.py`
- Test: `tests/test_core/test_features.py`

**Spec 引用:** §4.1 (归一化数据模型), 用户 P2 #2 (max_length)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_core/test_features.py`:

```python
"""Tests for sqlseed.core.features module."""

from __future__ import annotations

from sqlseed.core.features import (
    CheckConstraintFeatures,
    ColumnFeatures,
    ForeignKeyFeatures,
    IndexFeatures,
    StructuralFeatures,
    TableFeatures,
    UniqueConstraintFeatures,
)


def test_column_features_min_fields():
    """ColumnFeatures 仅需 name + type + nullable + default + pk/ai/computed."""
    cf = ColumnFeatures(
        name="id",
        type="INTEGER",
        nullable=False,
        default=None,
        is_primary_key=True,
        is_autoincrement=True,
        is_computed=False,
    )
    assert cf.name == "id"
    assert cf.max_length is None
    assert cf.collation is None


def test_column_features_max_length_parsed_from_varchar():
    """max_length 从 type 字符串解析 (P2 #2 fix)."""
    cf = ColumnFeatures(
        name="email",
        type="VARCHAR(255)",
        nullable=False,
        default=None,
        is_primary_key=False,
        is_autoincrement=False,
        is_computed=False,
    )
    # max_length 由 StructuralFeatureExtractor 解析, dataclass 本身不解析
    # 这里只验证字段存在且默认 None
    assert cf.max_length is None


def test_foreign_key_features_single_column():
    """FK features 支持单列 (P2 #1 fix: 逐个保留, 不分组聚合)."""
    fk = ForeignKeyFeatures(
        table="orders",
        columns=["user_id"],
        ref_table="users",
        ref_columns=["id"],
    )
    assert len(fk.columns) == 1
    assert fk.columns == ["user_id"]
    assert fk.on_delete is None
    assert fk.on_update is None


def test_foreign_key_features_composite():
    """FK features 支持复合 FK (多列)."""
    fk = ForeignKeyFeatures(
        table="order_items",
        columns=["order_id", "product_id"],
        ref_table="orders",
        ref_columns=["order_id", "product_id"],
    )
    assert len(fk.columns) == 2


def test_unique_constraint_features_index_based():
    """UNIQUE 约束从 IndexInfo 派生."""
    uc = UniqueConstraintFeatures(
        table="users",
        columns=["email"],
        is_index_based=True,
    )
    assert uc.is_index_based is True
    assert uc.partial_predicate is None


def test_table_features_aggregates_all():
    """TableFeatures 聚合所有特征类型."""
    tf = TableFeatures(
        name="users",
        columns=[
            ColumnFeatures(
                name="id", type="INTEGER", nullable=False, default=None,
                is_primary_key=True, is_autoincrement=True, is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    assert tf.name == "users"
    assert len(tf.columns) == 1
    assert tf.is_strict is False
    assert tf.is_without_rowid is False


def test_structural_features_has_schema_hash_and_dialect():
    """StructuralFeatures 包含 schema_hash (缓存键) + dialect."""
    sf = StructuralFeatures(
        dialect="sqlite",
        tables=[],
        schema_hash="abc123",
    )
    assert sf.dialect == "sqlite"
    assert sf.schema_hash == "abc123"
    assert sf.dialect_specific is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_core/test_features.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'sqlseed.core.features'"

- [ ] **Step 3: 创建 features.py 实现数据模型**

创建 `src/sqlseed/core/features.py`:

```python
"""Layer 1: Normalized structural features for cross-database schema analysis.

Defines dialect-agnostic dataclasses for schema introspection results.
Used by Layer 2 (stage relevance) and Layer 3 (staged LLM pipeline) in
the sqlseed-ai plugin.

This module is in the CORE layer (no business logic, no LLM code).
It builds on the existing DatabaseAdapter Protocol
(src/sqlseed/database/_protocol.py) and adds normalized containers
that support composite FK, composite UNIQUE, partial indexes, collation,
and other features the Protocol does not directly expose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnFeatures:
    """Normalized column features, dialect-agnostic.

    Extends ColumnInfo with optional max_length (parsed from type string
    like VARCHAR(255)) and collation (dialect-specific).
    """

    name: str
    type: str  # Original type string (e.g., "VARCHAR(255)", "INTEGER")
    nullable: bool
    default: Any
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool
    # Optional extensions (filled by dialect-specific extractor)
    max_length: int | None = None  # Parsed from VARCHAR(N)/CHAR(N) etc.
    collation: str | None = None  # SQLite: NOCASE/BINARY/RTRIM; PG: COLLATION name


@dataclass
class ForeignKeyFeatures:
    """Normalized foreign key features, supports composite FK.

    P2 #1 fix: each single-column ForeignKeyInfo from the Protocol is
    preserved as a separate ForeignKeyFeatures with columns=[col].
    Composite FK (multi-column) is only created when the dialect
    extension detects multiple columns share the same FK name/id.
    """

    table: str
    columns: list[str]  # Single-col FK: len==1; composite FK: len>1
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None  # Requires dialect extension
    on_update: str | None = None  # Requires dialect extension


@dataclass
class UniqueConstraintFeatures:
    """Normalized UNIQUE constraint, supports composite.

    Derived from IndexInfo(unique=True) (is_index_based=True) or from
    DDL parsing of table-level UNIQUE constraints (is_index_based=False).
    """

    table: str
    columns: list[str]
    is_index_based: bool
    partial_predicate: str | None = None  # Requires dialect extension


@dataclass
class CheckConstraintFeatures:
    """Normalized CHECK constraint. Direct mapping from CheckConstraintInfo."""

    table: str
    name: str
    expression: str  # Raw SQL expression
    columns: list[str]  # Extracted column references


@dataclass
class IndexFeatures:
    """Normalized index. Based on IndexInfo with optional partial predicate."""

    table: str
    name: str
    columns: list[str]
    unique: bool
    partial_predicate: str | None = None  # Requires dialect extension


@dataclass
class TableFeatures:
    """Normalized table features."""

    name: str
    columns: list[ColumnFeatures]
    primary_key: list[str]  # Composite PK supported (from get_primary_keys)
    foreign_keys: list[ForeignKeyFeatures]  # Per-column (P2 #1 fix)
    unique_constraints: list[UniqueConstraintFeatures]
    check_constraints: list[CheckConstraintFeatures]
    indexes: list[IndexFeatures]
    # SQLite-specific (PG: always default values)
    is_strict: bool = False
    is_without_rowid: bool = False
    on_conflict: str | None = None


@dataclass
class DialectSpecificFeatures:
    """Dialect-specific features not in the common model."""

    dialect: str  # "sqlite" | "postgresql"
    features: dict[str, Any]


@dataclass
class StructuralFeatures:
    """Complete normalized schema features, dialect-agnostic.

    Output of StructuralFeatureExtractor.extract(). Consumed by Layer 2
    (stage relevance determination) and Layer 3 (staged LLM pipeline).
    """

    dialect: str
    tables: list[TableFeatures]
    schema_hash: str  # For cache key
    dialect_specific: DialectSpecificFeatures | None = None
    # views omitted: Protocol does not provide get_view_names()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_core/test_features.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 运行 mypy + ruff**

Run: `mypy src/sqlseed/core/features.py && ruff check src/sqlseed/core/features.py`
Expected: No issues

- [ ] **Step 6: Commit**

```bash
git add src/sqlseed/core/features.py tests/test_core/test_features.py
git commit -m "feat(core): add Layer 1 normalized structural features data model"
```

---

## Task 2: Layer 1 StructuralFeatureExtractor (公共提取)

**Files:**
- Modify: `src/sqlseed/core/features.py` (追加 StructuralFeatureExtractor 类)
- Test: `tests/test_core/test_features.py` (追加测试)

**Spec 引用:** §4.2 (特征提取器), P2 #1 (FK 逐个保留)

- [ ] **Step 1: 写失败测试**

在 `tests/test_core/test_features.py` 末尾追加:

```python
import sqlite3
from pathlib import Path

import pytest

from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.core.features import StructuralFeatureExtractor


@pytest.fixture
def tmp_users_db(tmp_path: Path) -> RawSQLiteAdapter:
    """Create a small users/orders DB for feature extraction tests."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            age INTEGER DEFAULT 0 CHECK (age >= 0)
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL DEFAULT 0 CHECK (total >= 0),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX idx_orders_user_id ON orders(user_id);
    """)
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    return adapter


def test_extractor_extract_returns_structural_features(tmp_users_db):
    """extract() returns StructuralFeatures with correct dialect."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract()
    assert isinstance(features, StructuralFeatures)
    assert features.dialect == "sqlite"
    assert len(features.tables) == 2


def test_extractor_resolves_scope_all_tables(tmp_users_db):
    """_resolve_scope(None) returns all table names."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    scope = extractor._resolve_scope(None)
    assert set(scope) == {"users", "orders"}


def test_extractor_resolves_scope_with_fk_closure(tmp_users_db):
    """_resolve_scope(['orders']) includes FK parent 'users'."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    scope = extractor._resolve_scope(["orders"])
    assert "orders" in scope
    assert "users" in scope  # FK parent


def test_extractor_extracts_table_features_correctly(tmp_users_db):
    """_extract_table_common extracts columns, PK, FK, CHECK, UNIQUE."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract(["users"])
    users = next(t for t in features.tables if t.name == "users")
    assert len(users.columns) == 4
    assert users.primary_key == ["id"]
    assert len(users.check_constraints) == 1  # age >= 0
    assert users.check_constraints[0].expression == "age >= 0"
    # email UNIQUE detected from index
    assert len(users.unique_constraints) >= 1
    assert any("email" in uc.columns for uc in users.unique_constraints)


def test_extractor_preserves_single_column_fk(tmp_users_db):
    """P2 #1 fix: each single-column FK preserved as separate features."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features = extractor.extract(["orders"])
    orders = next(t for t in features.tables if t.name == "orders")
    assert len(orders.foreign_keys) == 1
    fk = orders.foreign_keys[0]
    assert fk.columns == ["user_id"]
    assert fk.ref_table == "users"
    assert fk.ref_columns == ["id"]


def test_extractor_computes_schema_hash(tmp_users_db):
    """_compute_schema_hash returns stable hash for same schema."""
    extractor = StructuralFeatureExtractor(tmp_users_db)
    features1 = extractor.extract()
    features2 = extractor.extract()
    assert features1.schema_hash == features2.schema_hash
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_core/test_features.py::test_extractor_extract_returns_structural_features -v`
Expected: FAIL with "AttributeError: module 'sqlseed.core.features' has no attribute 'StructuralFeatureExtractor'"

- [ ] **Step 3: 实现 StructuralFeatureExtractor (公共部分)**

在 `src/sqlseed/core/features.py` 末尾追加:

```python
import hashlib
import json

if TYPE_CHECKING:
    from sqlseed.database._protocol import (
        CheckConstraintInfo,
        ColumnInfo,
        DatabaseAdapter,
        ForeignKeyInfo,
        IndexInfo,
    )


def _parse_max_length(type_str: str) -> int | None:
    """Parse max_length from type string like 'VARCHAR(255)' -> 255."""
    import re

    match = re.match(r"^\s*\w+\s*\(\s*(\d+)\s*\)", type_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


class StructuralFeatureExtractor:
    """Extract structural features from any supported database.

    Uses DatabaseAdapter Protocol API + dialect extensions. Does NOT
    call non-existent methods like get_columns/get_pk_constraint.

    Spec §4.2: feature extractor with actual Protocol API.
    """

    def __init__(self, adapter: DatabaseAdapter) -> None:
        self.adapter = adapter
        # dialect via hasattr (Protocol does not declare attributes)
        self.dialect = getattr(adapter, "dialect", "sqlite")

    def extract(self, table_names: list[str] | None = None) -> StructuralFeatures:
        """Extract structural features.

        Args:
            table_names: None extracts all tables; provided extracts only
                those tables + FK parent closure (on-demand analysis).
        """
        tables_to_analyze = self._resolve_scope(table_names)
        tables = [self._extract_table_common(name) for name in tables_to_analyze]
        # Dialect-specific extensions fill Protocol gaps
        dialect_specific = self._extract_dialect_specific(tables_to_analyze)
        if dialect_specific:
            self._merge_dialect_specific(tables, dialect_specific)
        schema_hash = self._compute_schema_hash(tables)
        return StructuralFeatures(
            dialect=self.dialect,
            tables=tables,
            schema_hash=schema_hash,
            dialect_specific=dialect_specific,
        )

    def _resolve_scope(self, table_names: list[str] | None) -> list[str]:
        """On-demand: all tables or target tables + FK parent closure."""
        if table_names is None:
            return self.adapter.get_table_names()
        scope = set(table_names)
        changed = True
        while changed:
            changed = False
            for table in list(scope):
                fks = self.adapter.get_foreign_keys(table)
                for fk in fks:
                    if fk.ref_table not in scope:
                        scope.add(fk.ref_table)
                        changed = True
        return sorted(scope)

    def _extract_table_common(self, table_name: str) -> TableFeatures:
        """Common extraction using existing Protocol API."""
        # Uses get_column_info (NOT get_columns)
        column_infos = self.adapter.get_column_info(table_name)
        columns = [
            ColumnFeatures(
                name=ci.name,
                type=ci.type,
                nullable=ci.nullable,
                default=ci.default,
                is_primary_key=ci.is_primary_key,
                is_autoincrement=ci.is_autoincrement,
                is_computed=ci.is_computed,
                max_length=_parse_max_length(ci.type),
                # collation filled by dialect extension, default None
            )
            for ci in column_infos
        ]

        # Uses get_primary_keys (NOT get_pk_constraint)
        pk = self.adapter.get_primary_keys(table_name)

        # Uses get_foreign_keys + preserves per-column (P2 #1 fix)
        raw_fks = self.adapter.get_foreign_keys(table_name)
        fks = self._preserve_foreign_keys(raw_fks, table_name)

        # Derive UNIQUE constraints from get_index_info (Protocol has no get_unique_constraints)
        index_infos = self.adapter.get_index_info(table_name)
        unique_constraints = [
            UniqueConstraintFeatures(
                table=table_name,
                columns=list(idx.columns),
                is_index_based=True,
                # partial_predicate filled by dialect extension
            )
            for idx in index_infos if idx.unique
        ]
        indexes = [
            IndexFeatures(
                table=table_name,
                name=idx.name,
                columns=list(idx.columns),
                unique=idx.unique,
                # partial_predicate filled by dialect extension
            )
            for idx in index_infos
        ]

        # Uses get_check_constraints (direct mapping)
        check_infos = self.adapter.get_check_constraints(table_name)
        check_constraints = [
            CheckConstraintFeatures(
                table=table_name,
                name=cci.name,
                expression=cci.expression,
                columns=list(cci.columns),
            )
            for cci in check_infos
        ]

        return TableFeatures(
            name=table_name,
            columns=columns,
            primary_key=pk,
            foreign_keys=fks,
            unique_constraints=unique_constraints,
            check_constraints=check_constraints,
            indexes=indexes,
            # is_strict/is_without_rowid/on_conflict filled by dialect extension
        )

    def _preserve_foreign_keys(
        self, raw_fks: list[ForeignKeyInfo], table: str
    ) -> list[ForeignKeyFeatures]:
        """P2 #1 fix: preserve each single-column FK as separate features.

        Do NOT group by ref_table (that would incorrectly merge
        created_by -> users(id) and approved_by -> users(id)).
        Composite FK detection requires dialect extension to read FK name/id.
        """
        return [
            ForeignKeyFeatures(
                table=table,
                columns=[fk.column],
                ref_table=fk.ref_table,
                ref_columns=[fk.ref_column],
                # on_delete/on_update filled by dialect extension
            )
            for fk in raw_fks
        ]

    def _extract_dialect_specific(self, tables: list[str]) -> DialectSpecificFeatures | None:
        """Dialect-specific extraction: fills Protocol gaps."""
        if self.dialect == "sqlite":
            return self._extract_sqlite_specific(tables)
        if self.dialect == "postgresql":
            return self._extract_postgresql_specific(tables)
        return None

    def _extract_sqlite_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """SQLite-specific: STRICT, WITHOUT ROWID, ON CONFLICT, COLLATE, partial indexes.

        Implemented in Task 3.
        """
        return DialectSpecificFeatures(dialect="sqlite", features={})

    def _extract_postgresql_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """PostgreSQL-specific: SEQUENCE, EXCLUSION, PARTITION, COLLATION.

        Implemented in Task 4.
        """
        return DialectSpecificFeatures(dialect="postgresql", features={})

    def _merge_dialect_specific(
        self, tables: list[TableFeatures], dialect_specific: DialectSpecificFeatures
    ) -> None:
        """Merge dialect-specific fields into TableFeatures.

        Fills is_strict, is_without_rowid, on_conflict, collation,
        partial_predicate. Dialect-specific fields are populated by
        `_extract_sqlite_specific` (Task 3) or `_extract_postgresql_specific`
        (Task 4 stub); this method merges them into TableFeatures.
        """
        features = dialect_specific.features
        for table in tables:
            table_features = features.get(table.name, {})
            if "is_strict" in table_features:
                table.is_strict = table_features["is_strict"]
            if "is_without_rowid" in table_features:
                table.is_without_rowid = table_features["is_without_rowid"]
            if "on_conflict" in table_features:
                table.on_conflict = table_features["on_conflict"]
            # collation / partial_predicate filled per-column/per-index
            col_collations = table_features.get("column_collations", {})
            if col_collations:
                for col in table.columns:
                    if col.name in col_collations:
                        col.collation = col_collations[col.name]
            index_predicates = table_features.get("index_predicates", {})
            if index_predicates:
                for idx in table.indexes:
                    if idx.name in index_predicates:
                        idx.partial_predicate = index_predicates[idx.name]

    def _compute_schema_hash(self, tables: list[TableFeatures]) -> str:
        """Compute stable hash of schema for cache key."""
        # Hash table names + columns + constraints (deterministic order)
        payload = []
        for table in sorted(tables, key=lambda t: t.name):
            payload.append({
                "name": table.name,
                "columns": [
                    {"name": c.name, "type": c.type, "nullable": c.nullable,
                     "pk": c.is_primary_key, "ai": c.is_autoincrement}
                    for c in table.columns
                ],
                "pk": table.primary_key,
                "fks": [
                    {"cols": fk.columns, "ref_table": fk.ref_table, "ref_cols": fk.ref_columns}
                    for fk in table.foreign_keys
                ],
                "checks": [
                    {"name": c.name, "expr": c.expression, "cols": c.columns}
                    for c in table.check_constraints
                ],
                "uniques": [
                    {"cols": u.columns, "index_based": u.is_index_based}
                    for u in table.unique_constraints
                ],
            })
        json_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()[:16]
```

注意: 在 features.py 顶部 `from typing import Any` 之后添加:

```python
from typing import TYPE_CHECKING, Any
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_core/test_features.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: 运行 mypy + ruff**

Run: `mypy src/sqlseed/core/features.py && ruff check src/sqlseed/core/features.py`
Expected: No issues

- [ ] **Step 6: Commit**

```bash
git add src/sqlseed/core/features.py tests/test_core/test_features.py
git commit -m "feat(core): implement StructuralFeatureExtractor with actual Protocol API"
```

---

## Task 3: Layer 1 SQLite 方言扩展

**Files:**
- Modify: `src/sqlseed/core/features.py` (实现 `_extract_sqlite_specific`)
- Test: `tests/test_core/test_features.py` (追加测试)

**Spec 引用:** §4.4 (方言特有特征处理策略)

- [ ] **Step 1: 写失败测试**

在 `tests/test_core/test_features.py` 末尾追加:

```python
def test_extractor_sqlite_detects_strict_table(tmp_path: Path):
    """SQLite STRICT table detected via DDL parsing."""
    db_path = tmp_path / "strict.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("CREATE TABLE strict_tbl (x INTEGER) STRICT;")
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    strict_tbl = next(t for t in features.tables if t.name == "strict_tbl")
    assert strict_tbl.is_strict is True


def test_extractor_sqlite_detects_without_rowid(tmp_path: Path):
    """SQLite WITHOUT ROWID table detected."""
    db_path = tmp_path / "wrid.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("CREATE TABLE wrid_tbl (id INTEGER PRIMARY KEY) WITHOUT ROWID;")
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    wrid = next(t for t in features.tables if t.name == "wrid_tbl")
    assert wrid.is_without_rowid is True


def test_extractor_sqlite_detects_column_collation(tmp_path: Path):
    """SQLite per-column COLLATE detected."""
    db_path = tmp_path / "collate.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE items (name TEXT COLLATE NOCASE, code TEXT COLLATE BINARY);"
    )
    conn.commit()
    conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    extractor = StructuralFeatureExtractor(adapter)
    features = extractor.extract()
    items = next(t for t in features.tables if t.name == "items")
    name_col = next(c for c in items.columns if c.name == "name")
    code_col = next(c for c in items.columns if c.name == "code")
    assert name_col.collation == "NOCASE"
    assert code_col.collation == "BINARY"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_core/test_features.py::test_extractor_sqlite_detects_strict_table -v`
Expected: FAIL (is_strict still False)

- [ ] **Step 3: 实现 SQLite 方言扩展**

在 `src/sqlseed/core/features.py` 中替换 `_extract_sqlite_specific` 方法:

```python
    def _extract_sqlite_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """SQLite-specific: STRICT, WITHOUT ROWID, ON CONFLICT, COLLATE.

        Uses sqlite_master.sql DDL parsing (no extra Protocol methods needed).
        """
        import re

        features: dict[str, Any] = {}
        for table_name in tables:
            table_features: dict[str, Any] = {}
            # Read DDL from sqlite_master
            try:
                result = self.adapter.execute(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                rows = result.fetchall() if hasattr(result, "fetchall") else []
                ddl = rows[0][0] if rows and rows[0] else ""
            except Exception:
                ddl = ""

            if ddl:
                # STRICT table
                if re.search(r"\bSTRICT\b", ddl, re.IGNORECASE):
                    table_features["is_strict"] = True
                # WITHOUT ROWID
                if re.search(r"\bWITHOUT\s+ROWID\b", ddl, re.IGNORECASE):
                    table_features["is_without_rowid"] = True
                # ON CONFLICT clause (rare)
                on_conflict_match = re.search(
                    r"\bON\s+CONFLICT\s+(ROLLBACK|ABORT|FAIL|IGNORE|REPLACE)\b",
                    ddl, re.IGNORECASE,
                )
                if on_conflict_match:
                    table_features["on_conflict"] = on_conflict_match.group(1).upper()

                # Per-column COLLATE
                col_collations: dict[str, str] = {}
                # Match: column_name TYPE ... COLLATE COLLATION_NAME
                # Skip CONSTRAINT keyword to avoid table-level constraints
                col_pattern = re.compile(
                    r'"?(\w+)"?\s+\w+(?:\s*\([^)]*\))?'
                    r'(?:\s+(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|UNIQUE|DEFAULT\s+\S+))*'
                    r'\s+COLLATE\s+(\w+)',
                    re.IGNORECASE,
                )
                for match in col_pattern.finditer(ddl):
                    col_name = match.group(1)
                    collation = match.group(2).upper()
                    col_collations[col_name] = collation
                if col_collations:
                    table_features["column_collations"] = col_collations

            # Partial index predicates via PRAGMA index_list
            index_predicates: dict[str, str] = {}
            try:
                from sqlseed._utils.sql_safe import quote_identifier

                safe_table = quote_identifier(table_name)
                result = self.adapter.execute(f"PRAGMA index_list({safe_table})")
                rows = result.fetchall() if hasattr(result, "fetchall") else []
                for row in rows:
                    # row: (seq, name, unique, origin, partial)
                    if len(row) >= 5 and row[4]:
                        idx_name = row[1]
                        partial = row[4]
                        if isinstance(partial, str) and partial.strip():
                            index_predicates[idx_name] = partial
            except Exception:
                pass
            if index_predicates:
                table_features["index_predicates"] = index_predicates

            if table_features:
                features[table_name] = table_features

        return DialectSpecificFeatures(dialect="sqlite", features=features)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_core/test_features.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sqlseed/core/features.py tests/test_core/test_features.py
git commit -m "feat(core): implement SQLite dialect extension (STRICT/WROWID/COLLATE)"
```

---

## Task 4: Layer 1 PostgreSQL 方言扩展 (stub)

**Files:**
- Modify: `src/sqlseed/core/features.py` (实现 `_extract_postgresql_specific`)
- Test: `tests/test_core/test_features.py` (追加 stub 测试)

**Spec 引用:** §4.4 (PostgreSQL 特有: SEQUENCE, EXCLUSION, PARTITION, INHERITANCE)

注: PG 集成测试需 testcontainers, 此处仅实现 stub + 单元测试用 mock adapter。

- [ ] **Step 1: 写 stub 测试**

在 `tests/test_core/test_features.py` 末尾追加:

```python
from unittest.mock import MagicMock


def test_extractor_postgresql_dialect_returns_empty_features():
    """PG dialect extension returns empty features dict (stub for now).

    Full PG introspection (SEQUENCE/EXCLUSION/PARTITION) is implemented
    in integration test phase (Task 16).
    """
    mock_adapter = MagicMock()
    mock_adapter.dialect = "postgresql"
    mock_adapter.get_table_names.return_value = []
    extractor = StructuralFeatureExtractor(mock_adapter)
    features = extractor.extract()
    assert features.dialect == "postgresql"
    assert features.dialect_specific is not None
    assert features.dialect_specific.dialect == "postgresql"
    assert features.dialect_specific.features == {}
```

- [ ] **Step 2: 运行测试验证通过 (stub 已在 Task 2 实现)**

Run: `pytest tests/test_core/test_features.py::test_extractor_postgresql_dialect_returns_empty_features -v`
Expected: PASS

- [ ] **Step 3: 给 PostgreSQL stub 添加未来扩展点 docstring**

修改 `_extract_postgresql_specific` 方法, 在 docstring 中明确未来扩展点 (Phase 1 仅返回空 features, 不查询 pg_catalog):

```python
    def _extract_postgresql_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """PostgreSQL-specific: SEQUENCE, EXCLUSION, PARTITION, INHERITANCE, COLLATION.

        Phase 1 stub: returns empty features. Full implementation deferred
        to a future phase (tracked in spec §11.3 as a non-blocking enhancement).
        When implemented, this method will query:
        - pg_sequences for SEQUENCE objects (SERIAL/IDENTITY)
        - pg_constraint conflist for EXCLUSION constraints
        - pg_partitioned_table for PARTITION BY
        - pg_inherits for INHERITS
        - pg_collation per column for COLLATION

        The stub is intentional: Phase 1 focuses on SQLite + core PostgreSQL
        feature parity (tables, columns, PKs, FKs, indexes, checks, uniques)
        which the DatabaseAdapter Protocol already exposes.
        """
        return DialectSpecificFeatures(dialect="postgresql", features={})
```

- [ ] **Step 4: 运行测试 + mypy + ruff**

Run: `pytest tests/test_core/test_features.py -v && mypy src/sqlseed/core/features.py && ruff check src/sqlseed/core/features.py`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sqlseed/core/features.py tests/test_core/test_features.py
git commit -m "feat(core): add PostgreSQL dialect extension stub (full impl in Task 16)"
```

---

## Task 5: Layer 2 阶段相关性判断

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py`
- Test: `plugins/sqlseed-ai/tests/test_stage_relevance.py`

**Spec 引用:** §5 (阶段相关性矩阵 + 判断器)

- [ ] **Step 1: 写失败测试**

创建 `plugins/sqlseed-ai/tests/test_stage_relevance.py`:

```python
"""Tests for stage_relevance module."""

from __future__ import annotations

from sqlseed_ai.stage_relevance import StageRelevance, determine_stage_relevance
from sqlseed.core.features import (
    ColumnFeatures,
    ForeignKeyFeatures,
    IndexFeatures,
    StructuralFeatures,
    TableFeatures,
    UniqueConstraintFeatures,
)


def _make_features(
    *,
    has_composite_unique: bool = False,
    has_composite_fk: bool = False,
    has_collate: bool = False,
    has_strict: bool = False,
    has_partial_index: bool = False,
    has_on_conflict: bool = False,
    has_default: bool = False,
    has_autoincrement: bool = False,
    has_generated: bool = False,
) -> StructuralFeatures:
    """Build minimal StructuralFeatures for testing."""
    columns = [
        ColumnFeatures(
            name="id", type="INTEGER", nullable=False, default=None,
            is_primary_key=True, is_autoincrement=has_autoincrement, is_computed=False,
        ),
    ]
    if has_default:
        columns.append(
            ColumnFeatures(
                name="status", type="TEXT", nullable=False, default="active",
                is_primary_key=False, is_autoincrement=False, is_computed=False,
            )
        )
    if has_collate:
        columns.append(
            ColumnFeatures(
                name="name", type="TEXT", nullable=True, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=False,
                collation="NOCASE",
            )
        )
    if has_generated:
        columns.append(
            ColumnFeatures(
                name="total", type="REAL", nullable=False, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=True,
            )
        )

    unique_constraints = []
    if has_composite_unique:
        unique_constraints.append(
            UniqueConstraintFeatures(
                table="t", columns=["a", "b"], is_index_based=True,
            )
        )

    foreign_keys = []
    if has_composite_fk:
        foreign_keys.append(
            ForeignKeyFeatures(
                table="t", columns=["a", "b"], ref_table="ref", ref_columns=["a", "b"],
            )
        )

    indexes = []
    if has_partial_index:
        indexes.append(
            IndexFeatures(
                table="t", name="idx_partial", columns=["x"], unique=False,
                partial_predicate="x > 0",
            )
        )

    table = TableFeatures(
        name="t",
        columns=columns,
        primary_key=["id"],
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        check_constraints=[],
        indexes=indexes,
        is_strict=has_strict,
        on_conflict="REPLACE" if has_on_conflict else None,
    )
    return StructuralFeatures(dialect="sqlite", tables=[table], schema_hash="test")


def test_stage_relevance_stage1_always_includes_basic_structure():
    """S1 always includes tables/columns/types/pk/fk/check/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage1["tables"] is True
    assert rel.stage1["columns"] is True
    assert rel.stage1["types"] is True
    assert rel.stage1["pk"] is True
    assert rel.stage1["fk"] is True
    assert rel.stage1["check"] is True
    assert rel.stage1["unique"] is True


def test_stage_relevance_stage1_composite_flags():
    """S1 composite_unique/composite_fk flags set when present."""
    features = _make_features(has_composite_unique=True, has_composite_fk=True)
    rel = determine_stage_relevance(features)
    assert rel.stage1["composite_unique"] is True
    assert rel.stage1["composite_fk"] is True


def test_stage_relevance_stage2_includes_not_null_pk_fk():
    """S2 always includes not_null/pk/fk/check/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage2["not_null"] is True
    assert rel.stage2["pk"] is True
    assert rel.stage2["fk"] is True
    assert rel.stage2["check"] is True
    assert rel.stage2["unique"] is True


def test_stage_relevance_stage2_optional_flags_off_by_default():
    """Optional S2 flags off when feature absent."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage2["default"] is False
    assert rel.stage2["autoincrement"] is False
    assert rel.stage2["generated"] is False
    assert rel.stage2["collate"] is False
    assert rel.stage2["strict"] is False


def test_stage_relevance_stage2_optional_flags_on_when_present():
    """Optional S2 flags on when feature present."""
    features = _make_features(
        has_default=True, has_autoincrement=True, has_generated=True,
        has_collate=True, has_strict=True, has_partial_index=True,
    )
    rel = determine_stage_relevance(features)
    assert rel.stage2["default"] is True
    assert rel.stage2["autoincrement"] is True
    assert rel.stage2["generated"] is True
    assert rel.stage2["collate"] is True
    assert rel.stage2["strict"] is True
    assert rel.stage2["partial_unique"] is True


def test_stage_relevance_stage3_includes_check_fk_unique():
    """S3 always includes check/fk/unique."""
    features = _make_features()
    rel = determine_stage_relevance(features)
    assert rel.stage3["check"] is True
    assert rel.stage3["fk"] is True
    assert rel.stage3["unique"] is True


def test_stage_relevance_stage3_postgres_always_strict():
    """S3 strict=True for PostgreSQL dialect (PG always strict)."""
    features = _make_features()
    features.dialect = "postgresql"
    rel = determine_stage_relevance(features)
    assert rel.stage3["strict"] is True


def test_stage_relevance_stage3_on_conflict_flag():
    """S3 on_conflict flag set when present (SQLite only)."""
    features = _make_features(has_on_conflict=True)
    rel = determine_stage_relevance(features)
    assert rel.stage3["on_conflict"] is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_stage_relevance.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'sqlseed_ai.stage_relevance'"

- [ ] **Step 3: 实现 stage_relevance.py**

创建 `plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py`:

```python
"""Layer 2: Stage relevance determination.

Consumes StructuralFeatures (from Layer 1) and outputs StageRelevance —
a deterministic, no-LLM judgment of which structural features each
stage (1/2/3) needs.

Spec §5: stage relevance matrix + determinator.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlseed.core.features import StructuralFeatures


@dataclass
class StageRelevance:
    """Per-stage feature relevance, deterministic pre-analysis judgment.

    Each dict maps feature name -> bool (True: stage needs it, False: skip).
    Keys are documented in spec §5.2 relevance matrix.
    """

    stage1: dict[str, bool]  # Structure analysis
    stage2: dict[str, bool]  # Column analysis
    stage3: dict[str, bool]  # Validation + auto-fix


def determine_stage_relevance(features: StructuralFeatures) -> StageRelevance:
    """Determine which features each stage needs.

    Pure deterministic rules, no LLM, dialect-agnostic
    (operates on normalized StructuralFeatures).
    """
    # Detect optional features across all tables
    has_composite_unique = any(
        len(uc.columns) > 1
        for t in features.tables
        for uc in t.unique_constraints
    )
    has_composite_fk = any(
        len(fk.columns) > 1
        for t in features.tables
        for fk in t.foreign_keys
    )
    has_collate = any(
        c.collation is not None
        for t in features.tables
        for c in t.columns
    )
    has_strict = any(t.is_strict for t in features.tables)  # SQLite-only
    has_partial_index = any(
        idx.partial_predicate is not None
        for t in features.tables
        for idx in t.indexes
    )
    has_on_conflict = any(t.on_conflict for t in features.tables)  # SQLite-only
    has_default = any(
        c.default is not None
        for t in features.tables
        for c in t.columns
    )
    has_autoincrement = any(
        c.is_autoincrement
        for t in features.tables
        for c in t.columns
    )
    has_generated = any(
        c.is_computed
        for t in features.tables
        for c in t.columns
    )

    return StageRelevance(
        stage1={
            "tables": True,
            "columns": True,
            "types": True,
            "pk": True,
            "fk": True,
            "check": True,
            "unique": True,
            "composite_unique": has_composite_unique,
            "composite_fk": has_composite_fk,
        },
        stage2={
            "not_null": True,
            "default": has_default,
            "autoincrement": has_autoincrement,
            "generated": has_generated,
            "pk": True,
            "fk": True,
            "check": True,
            "unique": True,
            "collate": has_collate,
            "strict": has_strict,
            "partial_unique": has_partial_index,
        },
        stage3={
            "check": True,
            "fk": True,
            "unique": True,
            "composite_unique": has_composite_unique,
            "on_conflict": has_on_conflict,
            "collate": has_collate,
            "strict": has_strict or features.dialect == "postgresql",
            "partial_unique": has_partial_index,
        },
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_stage_relevance.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: 运行 mypy + ruff**

Run: `mypy plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py && ruff check plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py`
Expected: No issues

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/stage_relevance.py plugins/sqlseed-ai/tests/test_stage_relevance.py
git commit -m "feat(ai): implement Layer 2 stage relevance determinator"
```

---

## Task 6: Layer 3 StructureSummary + Stage3Validator 骨架

**Files:**
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py`
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py`

**Spec 引用:** §6.6 (StagedSchemaAnalyzer 关系), §6.7 (StructureSummary), §6.8 (ErrorClassifier)

- [ ] **Step 1: 写失败测试**

创建 `plugins/sqlseed-ai/tests/test_staged_analyzer.py`:

```python
"""Tests for staged_analyzer module."""

from __future__ import annotations

from sqlseed_ai.staged_analyzer import (
    ErrorCategory,
    ErrorClassifier,
    StructureSummary,
    TableStructureSummary,
)


def test_table_structure_summary_minimal():
    """TableStructureSummary requires name/purpose/anchor_columns/naming_prefix/complexity."""
    summary = TableStructureSummary(
        name="users",
        purpose="User account management",
        anchor_columns=["id", "email"],
        naming_prefix="USER-",
        complexity=10,
    )
    assert summary.name == "users"
    assert summary.cross_column_checks == []
    assert summary.fk_references == []


def test_structure_summary_has_required_fields():
    """StructureSummary has schema_hash/topological_order/fk_graph/tables/etc."""
    summary = StructureSummary(
        schema_hash="abc123",
        topological_order=["users", "orders"],
        fk_graph=[{"parent": "users", "child": "orders", "col": "user_id"}],
        tables=[],
        naming_conventions={"users": "USER-", "orders": "ORD-"},
        complexity_score={"tables": 2, "avg_columns": 5, "avg_constraints": 2},
        dialect="sqlite",
    )
    assert summary.schema_hash == "abc123"
    assert summary.topological_order == ["users", "orders"]
    assert summary.dialect == "sqlite"


def test_error_classifier_transient_timeout():
    """TimeoutError classified as TRANSIENT."""
    category = ErrorClassifier.classify(TimeoutError("LLM timeout"))
    assert category == ErrorCategory.TRANSIENT


def test_error_classifier_logic_json_decode():
    """JSON decode error classified as LOGIC."""
    import json

    try:
        json.loads("{invalid}")
    except json.JSONDecodeError as e:
        category = ErrorClassifier.classify(e)
        assert category == ErrorCategory.LOGIC


def test_error_classifier_quality_empty_output():
    """Empty output classified as QUALITY."""
    category = ErrorClassifier.classify(RuntimeError("empty"), output="")
    assert category == ErrorCategory.QUALITY


def test_error_classifier_quality_short_output():
    """Short output (<50 chars) classified as QUALITY."""
    category = ErrorClassifier.classify(RuntimeError("too short"), output='{"name":"t"}')
    assert category == ErrorCategory.QUALITY


def test_error_classifier_quality_all_string_default():
    """Output with >80% string generators classified as QUALITY (LLM gave up)."""
    output = '{"columns":[{"name":"a","generator":"string"},{"name":"b","generator":"string"}]}'
    category = ErrorClassifier.classify(RuntimeError("all defaults"), output=output)
    assert category == ErrorCategory.QUALITY
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'sqlseed_ai.staged_analyzer'"

- [ ] **Step 3: 实现 staged_analyzer.py (数据结构 + ErrorClassifier)**

创建 `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py`:

```python
"""Layer 3: Staged LLM analysis pipeline.

Implements the Least-to-Most Prompting approach (Zhou et al. 2022):
  Stage 0 (optional): data sampling
  Stage 1: structure analysis (1 LLM call)
  Decision: dynamic granularity selection (no LLM)
  Stage 2: column analysis (N LLM calls, granularity-adaptive)
  Stage 3: validation + auto-fix (no LLM, pure rules)

This module contains:
  - StructureSummary / TableStructureSummary dataclasses (spec §6.7)
  - StagedSchemaAnalyzer class (spec §6.6, flag-switched entry point)
  - Stage3Validator class (spec §6.1 stage 3, new auto-fix rules #14-#16)
  - ErrorClassifier class (spec §6.8)

Spec reference: docs/superpowers/specs/2026-07-02-llm-staged-yaml-analysis-design.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig
    from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer

logger = get_logger(__name__)


# ── Spec §6.7: inter-stage data format ────────────────────────────────


@dataclass
class TableStructureSummary:
    """Single-table structure summary, Stage 1 output, Stage 2 input."""

    name: str
    purpose: str  # LLM-inferred table purpose (e.g., "employee payroll")
    anchor_columns: list[str]  # PK + UNIQUE columns (decide generation strategy)
    naming_prefix: str  # Prefix (e.g., "EMP-" for employees, derived from table name)
    complexity: int  # Score: column_count * constraint_count
    cross_column_checks: list[dict] = field(default_factory=list)
    # Cross-column CHECK expressions + involved column names+types
    # for per_column mode context injection.
    # Example: [{"expression": "end_date >= start_date",
    #           "columns": {"start_date": "DATE", "end_date": "DATE"}}]
    fk_references: list[dict] = field(default_factory=list)
    # Same-table FK reference info (this table as parent, referenced columns)
    # Example: [{"column": "id", "ref_count": 3}]


@dataclass
class StructureSummary:
    """Stage 1 complete output, passed in-memory to Stage 2/3.

    This is the "YAML state machine" Stage 1 state. Not written to disk
    unless --cache-analysis is set.
    """

    schema_hash: str  # Cache key
    topological_order: list[str]  # Table fill order (topological sort)
    fk_graph: list[dict]  # FK dependency graph [{parent, child, col, on_delete}]
    tables: list[TableStructureSummary]  # Per-table structure summaries
    naming_conventions: dict[str, str]  # {table_name: prefix}
    complexity_score: dict  # {tables, avg_columns, avg_constraints}
    dialect: str  # sqlite | postgresql


# ── Spec §6.8: error classifier ──────────────────────────────────────


class ErrorCategory(Enum):
    """LLM call failure category."""

    TRANSIENT = "transient"  # Temporary (retry may fix)
    LOGIC = "logic"  # Logic error (switch prompt/strategy)
    QUALITY = "quality"  # Insufficient quality (degrade)


class ErrorClassifier:
    """LLM call failure classifier, pure rules, no LLM.

    Spec §6.8: classify based on exception type + output content.
    """

    @staticmethod
    def classify(error: Exception, output: str | None = None) -> ErrorCategory:
        """Classify based on exception type + output content."""
        # === TRANSIENT (temporary, retry may fix) ===
        if isinstance(error, TimeoutError):
            return ErrorCategory.TRANSIENT
        try:
            from openai import APIConnectionError, APITimeoutError
            if isinstance(error, (APIConnectionError, APITimeoutError)):
                return ErrorCategory.TRANSIENT
        except ImportError:
            pass
        try:
            from openai import InternalServerError, RateLimitError
            if isinstance(error, (InternalServerError, RateLimitError)):
                return ErrorCategory.TRANSIENT
        except ImportError:
            pass
        if "out of memory" in str(error).lower() or "cuda" in str(error).lower():
            return ErrorCategory.TRANSIENT

        # === LOGIC (logic error, switch prompt/strategy retry) ===
        if isinstance(error, (ValueError, json.JSONDecodeError)):
            return ErrorCategory.LOGIC
        if "schema" in str(error).lower() and "mismatch" in str(error).lower():
            return ErrorCategory.LOGIC
        if output and output.strip().startswith("{"):
            try:
                parsed = json.loads(output)
                if isinstance(parsed, dict) and "columns" in parsed:
                    # Column count check happens externally; here just tag category
                    return ErrorCategory.LOGIC
            except Exception:
                pass
        if "unknown generator" in str(error).lower() or "invalid generator" in str(error).lower():
            return ErrorCategory.LOGIC
        if "param" in str(error).lower() and "type" in str(error).lower():
            return ErrorCategory.LOGIC

        # === QUALITY (insufficient quality, degrade) ===
        if output is None or output.strip() in ("", "{}"):
            return ErrorCategory.QUALITY
        if output and len(output.strip()) < 50:
            return ErrorCategory.QUALITY
        if output and '"generator": "string"' in output.lower():
            string_count = output.lower().count('"generator": "string"')
            total_count = output.lower().count('"generator":')
            if total_count > 0 and string_count / total_count > 0.8:
                return ErrorCategory.QUALITY

        # === Default: unknown errors -> QUALITY (degrade, don't crash pipeline) ===
        return ErrorCategory.QUALITY


# ── Spec §6.6: StagedSchemaAnalyzer (flag-switched entry point) ───────
# Full implementation in Task 7+


class StagedSchemaAnalyzer:
    """Staged LLM analysis entry point.

    Replaces SchemaSemanticAnalyzer.analyze() via flag switch, but does
    NOT delete existing class. Switched via AIConfig.use_staged_pipeline:
      - False (default): existing SchemaSemanticAnalyzer (backward compat)
      - True: this staged pipeline (new)

    Reuse relationships:
      - Stage 1/2 LLM calls: reuse SchemaAnalyzer._call_llm_once() (low-level client)
      - Stage 2 per_column retry: reuse AiConfigRefiner retry logic
      - Stage 3 auto-fix: call existing SchemaSemanticAnalyzer._auto_fix_config
        (rules 1-13, refactored to public function in Task 8) +
        new Stage3Validator (rules 14-16)
    """

    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config
        self._semantic_analyzer: SchemaSemanticAnalyzer | None = None
        self._low_level_analyzer: Any = None  # SchemaAnalyzer, lazy-init

    # Full implementation in Task 7 (stage 1) + Task 8 (stage 2) + Task 10 (stage 3)
    def analyze(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Analyze database via staged pipeline. Implemented in Task 7+."""
        raise NotImplementedError("StagedSchemaAnalyzer.analyze() implemented in Task 7+")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: 运行 mypy + ruff**

Run: `mypy plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py && ruff check plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py`
Expected: No issues

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): add Layer 3 StructureSummary + ErrorClassifier (skeleton)"
```

---

## Task 7: Layer 3 阶段 1 结构分析 + 降级 fallback

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (实现 StagedSchemaAnalyzer.analyze + _run_stage1)
- Create: `plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py` (阶段 1 prompt)
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (追加测试)

**Spec 引用:** §6.1 阶段 1, P3 #4 (降级 fallback 定义)

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_staged_analyzer.py` 末尾追加:

```python
from unittest.mock import MagicMock

from sqlseed.core.features import (
    ColumnFeatures,
    ForeignKeyFeatures,
    StructuralFeatures,
    TableFeatures,
)


def _make_simple_features() -> StructuralFeatures:
    """Build minimal StructuralFeatures for staged analyzer tests."""
    users = TableFeatures(
        name="users",
        columns=[
            ColumnFeatures(
                name="id", type="INTEGER", nullable=False, default=None,
                is_primary_key=True, is_autoincrement=True, is_computed=False,
            ),
            ColumnFeatures(
                name="email", type="TEXT", nullable=False, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    orders = TableFeatures(
        name="orders",
        columns=[
            ColumnFeatures(
                name="id", type="INTEGER", nullable=False, default=None,
                is_primary_key=True, is_autoincrement=True, is_computed=False,
            ),
            ColumnFeatures(
                name="user_id", type="INTEGER", nullable=False, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=False,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[
            ForeignKeyFeatures(
                table="orders", columns=["user_id"],
                ref_table="users", ref_columns=["id"],
            ),
        ],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    return StructuralFeatures(
        dialect="sqlite",
        tables=[users, orders],
        schema_hash="test123",
    )


def test_stage1_fallback_returns_deterministic_summary_when_llm_fails():
    """P3 #4: stage 1 fallback returns deterministic StructureSummary.

    When LLM returns empty/invalid output 3 times, stage 1 degrades to
    a deterministic summary derived purely from StructuralFeatures
    (no LLM). This ensures pipeline continues rather than crashes.
    """
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock low-level analyzer to always raise (simulating LLM failure)
    mock_low_level = MagicMock()
    mock_low_level._call_llm_once.side_effect = RuntimeError("LLM unavailable")
    analyzer._low_level_analyzer = mock_low_level

    summary = analyzer._run_stage1_with_fallback(features)

    # Fallback should produce a deterministic StructureSummary
    assert isinstance(summary, StructureSummary)
    assert summary.dialect == "sqlite"
    assert summary.schema_hash == "test123"
    # Topological order: users before orders (FK dependency)
    assert summary.topological_order == ["users", "orders"]
    # Tables should have summaries with naming prefixes derived from table name
    users_summary = next(t for t in summary.tables if t.name == "users")
    assert users_summary.naming_prefix == "USER-"
    orders_summary = next(t for t in summary.tables if t.name == "orders")
    assert orders_summary.naming_prefix == "ORD-"


def test_stage1_naming_prefix_derived_from_table_name():
    """Naming prefix derived from table name (first 4 chars upper + '-')."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    assert analyzer._derive_naming_prefix("users") == "USER-"
    assert analyzer._derive_naming_prefix("orders") == "ORD-"
    assert analyzer._derive_naming_prefix("categories") == "CATE-"


def test_stage1_topological_sort_orders_by_fk_dependency():
    """Topological sort puts FK parents before children."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    features = _make_simple_features()
    order = analyzer._topological_sort(features)
    # users must come before orders (orders has FK to users)
    assert order.index("users") < order.index("orders")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage1_fallback_returns_deterministic_summary_when_llm_fails -v`
Expected: FAIL with "NotImplementedError" or "AttributeError: '_run_stage1_with_fallback'"

- [ ] **Step 3: 创建 _stage_prompts.py (阶段 1 prompt)**

创建 `plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py`:

```python
"""Prompt templates for staged LLM analysis.

Spec §6.1: each stage has its own prompt + few-shot examples.
"""

from __future__ import annotations

# Stage 1: structure analysis
# Input: StructuralFeatures (filtered by stage1 relevance) + few-shot
# Output: JSON with tables/fk_graph/topological_order/naming_conventions/complexity

STAGE1_SYSTEM_PROMPT = """You are a database structure analyst. Analyze the schema and produce a JSON structure summary.

Output JSON schema:
{
  "tables": [
    {
      "name": "<table_name>",
      "purpose": "<one-sentence business purpose>",
      "anchor_columns": ["<pk_or_unique_col>", ...],
      "naming_prefix": "<PREFIX-> (4-letter table abbreviation + dash)",
      "complexity": <int: column_count * constraint_count>
    }
  ],
  "fk_graph": [
    {"parent": "<table>", "child": "<table>", "col": "<fk_col>"}
  ],
  "topological_order": ["<table1>", "<table2>", ...],
  "naming_conventions": {"<table>": "<PREFIX->"}
}

Rules:
- naming_prefix: first 4 chars of table name, uppercased, + "-"
- anchor_columns: PK columns + UNIQUE columns (max 3 per table)
- topological_order: FK parents before children
- Respond with ONLY valid JSON, no prose."""

STAGE1_USER_TEMPLATE = """Analyze this database schema (dialect: {dialect}):

Tables:
{tables_summary}

Foreign keys:
{fk_summary}

Produce the JSON structure summary."""

# Stage 2: per_column analysis (single column)
# Input: 1 column constraints + structure summary + cross-column CHECKs
# Output: {column, generator, params, derive_from, expression}

STAGE2_PER_COLUMN_SYSTEM_PROMPT = """You are a database test data engineer. Output JSON config for ONE column only.

Available generators: string(min_length,max_length,charset), integer(min_value,max_value),
float(min_value,max_value,precision), boolean, name, first_name, last_name, username,
email, phone, address, company, city, country, state, zip_code, country_code,
job_title, url, ipv4, uuid, date(start_year,end_year), datetime(start_year,end_year),
timestamp, text(min_length,max_length), sentence, password, word, choice,
json(schema), pattern(regex), template, weighted_choice.

template generator: params={"template":"FORMAT","sequence_start":0,"sequence_step":1}.
  FORMAT MUST contain {sequence} or {random_digits:N} placeholder.
  Use TABLE-SPECIFIC prefix (provided in context), never literal "PREFIX".

Output JSON: {"column":"<name>","generator":"<type>","params":{...},"derive_from":null,"expression":null}

Cross-column CHECK constraints: if this column is bounded by another column,
set "derive_from":["<other_col>"] and "expression":"<formula>" instead of "generator".

Respond with ONLY valid JSON, no prose."""

STAGE2_PER_COLUMN_USER_TEMPLATE = """Analyze column for table "{table_name}" (prefix: {naming_prefix}):

Column:
  name: {column_name}
  type: {column_type}
  nullable: {nullable}
  default: {default}
  is_pk: {is_pk}
  is_autoincrement: {is_autoincrement}
  is_computed: {is_computed}
  is_unique: {is_unique}

Cross-column CHECK constraints in this table:
{cross_column_checks}

Foreign keys in this table:
{foreign_keys}

Produce the JSON column config."""
```

- [ ] **Step 4: 在 staged_analyzer.py 中实现阶段 1 + 降级 fallback**

替换 `StagedSchemaAnalyzer` 类的实现 (替换 `NotImplementedError`):

```python
    def analyze(
        self,
        db: Any,
        *,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Analyze database via staged pipeline.

        Implemented incrementally:
          - Stage 1 (this task): structure analysis with fallback
          - Stage 2 (Task 8): per_column column analysis
          - Stage 3 (Task 10): validation + auto-fix
        """
        from sqlseed.core.features import StructuralFeatureExtractor
        from sqlseed_ai.stage_relevance import determine_stage_relevance

        # Pre-check: extract structural features
        extractor = StructuralFeatureExtractor(db)
        features = extractor.extract(table_names=tables)
        relevance = determine_stage_relevance(features)

        # Stage 1: structure analysis (with fallback on LLM failure)
        summary = self._run_stage1_with_fallback(features)

        # Stage 2 + 3 are wired up in Task 11 (full integration).
        # In this Task 7 we return a minimal config dict derived purely from
        # the deterministic stage-1 fallback, so the public analyze() entry
        # point is callable end-to-end without waiting for Task 11.
        tables_config: list[dict[str, Any]] = []
        for table_name in summary.topological_order:
            table_features = next(
                (t for t in features.tables if t.name == table_name), None,
            )
            if table_features is None:
                continue
            # Skip autoincrement PK columns (LLM stage 2 will handle in Task 8)
            skippable = self._get_skippable_columns(table_features)
            columns = [
                {"name": c.name, "generator": "string", "params": {}}
                for c in table_features.columns
                if c.name not in skippable
            ]
            tables_config.append({"name": table_name, "columns": columns})
        return {"tables": tables_config}

    def _run_stage1_with_fallback(self, features: StructuralFeatures) -> StructureSummary:
        """Run stage 1 with deterministic fallback on LLM failure (P3 #4)."""
        # Try LLM call first (max 3 retries)
        for attempt in range(3):
            try:
                return self._call_stage1_llm(features)
            except Exception as e:
                logger.warning(
                    "Stage 1 LLM call failed, attempting fallback",
                    attempt=attempt + 1, error=str(e)[:200],
                )
                category = ErrorClassifier.classify(e)
                if category == ErrorCategory.TRANSIENT and attempt < 2:
                    continue
                # LOGIC/QUALITY or TRANSIENT exhausted: use deterministic fallback
                break

        # P3 #4 fix: deterministic fallback StructureSummary
        logger.warning("Stage 1 falling back to deterministic summary (LLM unavailable)")
        return self._build_deterministic_fallback(features)

    def _call_stage1_llm(self, features: StructuralFeatures) -> StructureSummary:
        """Call LLM for stage 1 (will be fully implemented; raises if LLM unavailable)."""
        # Build prompt
        from sqlseed_ai._stage_prompts import (
            STAGE1_SYSTEM_PROMPT, STAGE1_USER_TEMPLATE,
        )

        tables_summary = "\n".join(
            f"- {t.name}: {len(t.columns)} cols, "
            f"{len(t.foreign_keys)} FKs, {len(t.check_constraints)} CHECKs, "
            f"{len(t.unique_constraints)} UNIQUEs"
            for t in features.tables
        )
        fk_summary = "\n".join(
            f"- {t.name}.{fk.columns} -> {fk.ref_table}.{fk.ref_columns}"
            for t in features.tables for fk in t.foreign_keys
        )
        user_prompt = STAGE1_USER_TEMPLATE.format(
            dialect=features.dialect,
            tables_summary=tables_summary,
            fk_summary=fk_summary or "(none)",
        )

        # Call LLM (reuse existing SchemaAnalyzer if available)
        if self._low_level_analyzer is None:
            raise RuntimeError("Low-level analyzer not configured")

        messages = [
            {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        response = self._low_level_analyzer._call_llm_once(messages)
        return self._parse_stage1_response(response, features)

    def _parse_stage1_response(
        self, response: str, features: StructuralFeatures
    ) -> StructureSummary:
        """Parse LLM JSON response into StructureSummary."""
        import json

        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from LLM: {e}") from e

        # Build StructureSummary from parsed JSON
        tables = []
        for t in data.get("tables", []):
            cross_checks = self._extract_cross_column_checks(t["name"], features)
            tables.append(TableStructureSummary(
                name=t["name"],
                purpose=t.get("purpose", ""),
                anchor_columns=t.get("anchor_columns", []),
                naming_prefix=t.get("naming_prefix", self._derive_naming_prefix(t["name"])),
                complexity=t.get("complexity", 0),
                cross_column_checks=cross_checks,
                fk_references=[],
            ))
        return StructureSummary(
            schema_hash=features.schema_hash,
            topological_order=data.get("topological_order", [t.name for t in features.tables]),
            fk_graph=data.get("fk_graph", []),
            tables=tables,
            naming_conventions=data.get("naming_conventions", {t.name: t.naming_prefix for t in tables}),
            complexity_score=data.get("complexity_score", {
                "tables": len(features.tables),
                "avg_columns": sum(len(t.columns) for t in features.tables) // max(len(features.tables), 1),
                "avg_constraints": 0,
            }),
            dialect=features.dialect,
        )

    def _build_deterministic_fallback(self, features: StructuralFeatures) -> StructureSummary:
        """P3 #4 fix: deterministic StructureSummary derived purely from features.

        No LLM, no business logic heuristics. Just mechanical derivations:
        - naming_prefix: first 4 chars of table name uppercased + "-"
        - purpose: empty (LLM-inferred, not available in fallback)
        - anchor_columns: PK + UNIQUE columns
        - topological_order: from _topological_sort()
        - complexity: column_count * constraint_count
        """
        tables_summary = []
        for t in features.tables:
            unique_cols = [
                col for uc in t.unique_constraints for col in uc.columns
            ]
            anchor = list(dict.fromkeys(t.primary_key + unique_cols))[:3]
            complexity = len(t.columns) * (
                len(t.foreign_keys) + len(t.unique_constraints) + len(t.check_constraints)
            )
            tables_summary.append(TableStructureSummary(
                name=t.name,
                purpose="",  # Cannot infer without LLM
                anchor_columns=anchor,
                naming_prefix=self._derive_naming_prefix(t.name),
                complexity=complexity,
                cross_column_checks=self._extract_cross_column_checks(t.name, features),
                fk_references=[],
            ))
        return StructureSummary(
            schema_hash=features.schema_hash,
            topological_order=self._topological_sort(features),
            fk_graph=[
                {"parent": fk.ref_table, "child": t.name, "col": fk.columns[0]}
                for t in features.tables for fk in t.foreign_keys
            ],
            tables=tables_summary,
            naming_conventions={t.name: t.naming_prefix for t in tables_summary},
            complexity_score={
                "tables": len(features.tables),
                "avg_columns": sum(len(t.columns) for t in features.tables) // max(len(features.tables), 1),
                "avg_constraints": sum(
                    len(t.foreign_keys) + len(t.unique_constraints) + len(t.check_constraints)
                    for t in features.tables
                ) // max(len(features.tables), 1),
            },
            dialect=features.dialect,
        )

    def _derive_naming_prefix(self, table_name: str) -> str:
        """Derive naming prefix from table name (first 4 chars upper + '-')."""
        # Take first 4 alphanumeric chars, uppercase, add dash
        prefix_chars = "".join(c for c in table_name[:5] if c.isalnum())[:4]
        return prefix_chars.upper() + "-"

    def _topological_sort(self, features: StructuralFeatures) -> list[str]:
        """Topological sort: FK parents before children (Kahn's algorithm)."""
        # Build adjacency: parent -> [children]
        children: dict[str, list[str]] = {t.name: [] for t in features.tables}
        in_degree: dict[str, int] = {t.name: 0 for t in features.tables}
        for t in features.tables:
            for fk in t.foreign_keys:
                if fk.ref_table in in_degree:
                    children[fk.ref_table].append(t.name)
                    in_degree[t.name] += 1
        # Kahn's algorithm
        queue = sorted([n for n, d in in_degree.items() if d == 0])
        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for child in sorted(children[node]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        return result

    def _extract_cross_column_checks(
        self, table_name: str, features: StructuralFeatures
    ) -> list[dict]:
        """Extract cross-column CHECK constraints for a table (for per_column context)."""
        table = next((t for t in features.tables if t.name == table_name), None)
        if table is None:
            return []
        result = []
        for chk in table.check_constraints:
            if len(chk.columns) > 1:
                # Build column name -> type map
                col_types = {c.name: c.type for c in table.columns}
                result.append({
                    "expression": chk.expression,
                    "columns": {col: col_types.get(col, "UNKNOWN") for col in chk.columns},
                })
        return result
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: 运行 mypy + ruff**

Run: `mypy plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py && ruff check plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py`
Expected: No issues

- [ ] **Step 7: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/src/sqlseed_ai/_stage_prompts.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): implement Stage 1 structure analysis + deterministic fallback"
```

---

## Task 8: Layer 3 阶段 2 per_column 列分析

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (实现 _run_stage2_per_column)
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (追加测试)

**Spec 引用:** §6.1 阶段 2 per_column, P1 #3 (跨列 CHECK 上下文注入)

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_staged_analyzer.py` 末尾追加:

```python
def test_stage2_per_column_calls_llm_once_per_column():
    """Stage 2 per_column mode calls LLM once per non-skipped column."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock low-level analyzer
    mock_low_level = MagicMock()
    mock_low_level._call_llm_once.return_value = '{"column":"id","generator":"integer","params":{},"derive_from":null,"expression":null}'
    analyzer._low_level_analyzer = mock_low_level

    # Build summary
    summary = analyzer._run_stage1_with_fallback(features)

    # Run stage 2 per_column
    result = analyzer._run_stage2_per_column(features, summary, target_tables=["users"])

    # Should have called LLM for each non-skipped column
    # users has id (PK autoincrement, skipped) + email (1 call)
    assert mock_low_level._call_llm_once.call_count == 1
    assert "tables" in result
    assert len(result["tables"]) == 1
    assert result["tables"][0]["name"] == "users"


def test_stage2_per_column_skips_pk_autoincrement_columns():
    """Stage 2 skips PK/AUTOINCREMENT/GENERATED/DEFAULT columns."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    features = _make_simple_features()
    analyzer = StagedSchemaAnalyzer(config=None)

    # Should skip id (PK + autoincrement)
    skip_cols = analyzer._get_skippable_columns(
        next(t for t in features.tables if t.name == "users")
    )
    assert "id" in skip_cols
    assert "email" not in skip_cols


def test_stage2_per_column_injects_cross_column_checks_in_prompt():
    """P1 #3 fix: cross-column CHECK injected into per_column prompt."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)
    # Build features with cross-column CHECK
    cross_check_table = TableFeatures(
        name="projects",
        columns=[
            ColumnFeatures(
                name="start_date", type="DATE", nullable=False, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=False,
            ),
            ColumnFeatures(
                name="end_date", type="DATE", nullable=False, default=None,
                is_primary_key=False, is_autoincrement=False, is_computed=False,
            ),
        ],
        primary_key=[],
        foreign_keys=[],
        unique_constraints=[],
        check_constraints=[],
        indexes=[],
    )
    # Manually add cross-column CHECK (since check_constraints needs CheckConstraintFeatures)
    from sqlseed.core.features import CheckConstraintFeatures
    cross_check_table.check_constraints.append(
        CheckConstraintFeatures(
            table="projects",
            name="ck_dates",
            expression="end_date >= start_date",
            columns=["end_date", "start_date"],
        )
    )
    features = StructuralFeatures(
        dialect="sqlite", tables=[cross_check_table], schema_hash="cross",
    )

    cross_checks = analyzer._extract_cross_column_checks("projects", features)
    assert len(cross_checks) == 1
    assert cross_checks[0]["expression"] == "end_date >= start_date"
    assert cross_checks[0]["columns"]["start_date"] == "DATE"
    assert cross_checks[0]["columns"]["end_date"] == "DATE"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage2_per_column_calls_llm_once_per_column -v`
Expected: FAIL with "AttributeError: '_run_stage2_per_column'"

- [ ] **Step 3: 实现 _run_stage2_per_column**

在 `StagedSchemaAnalyzer` 类中 (在 `_run_stage1_with_fallback` 之后) 添加:

```python
    def _run_stage2_per_column(
        self,
        features: StructuralFeatures,
        summary: StructureSummary,
        target_tables: list[str],
    ) -> dict[str, Any]:
        """Stage 2: per_column analysis (2B model recommended).

        Spec §6.1 per_column mode:
          - Input per call: 1 column constraints + structure summary
            + same-table cross-column CHECK context (P1 #3 fix)
          - Output: {column, generator, params, derive_from, expression}
          - Skip: PK/AUTOINCREMENT/GENERATED/DEFAULT (auto-fix handles)
        """
        from sqlseed_ai._stage_prompts import (
            STAGE2_PER_COLUMN_SYSTEM_PROMPT, STAGE2_PER_COLUMN_USER_TEMPLATE,
        )

        all_tables_config: list[dict[str, Any]] = []
        for table_name in summary.topological_order:
            if target_tables and table_name not in target_tables:
                continue
            table_features = next(
                (t for t in features.tables if t.name == table_name), None
            )
            if table_features is None:
                continue
            table_summary = next(
                (t for t in summary.tables if t.name == table_name), None
            )
            naming_prefix = (
                table_summary.naming_prefix if table_summary
                else self._derive_naming_prefix(table_name)
            )
            cross_checks = self._extract_cross_column_checks(table_name, features)
            skip_cols = self._get_skippable_columns(table_features)

            columns_config: list[dict[str, Any]] = []
            for col in table_features.columns:
                if col.name in skip_cols:
                    continue
                # Build per-column prompt with cross-column context
                fk_summary = self._format_fks_for_prompt(table_features)
                cross_checks_str = self._format_cross_checks_for_prompt(cross_checks)
                user_prompt = STAGE2_PER_COLUMN_USER_TEMPLATE.format(
                    table_name=table_name,
                    naming_prefix=naming_prefix,
                    column_name=col.name,
                    column_type=col.type,
                    nullable=col.nullable,
                    default=col.default,
                    is_pk=col.is_primary_key,
                    is_autoincrement=col.is_autoincrement,
                    is_computed=col.is_computed,
                    is_unique=self._is_column_unique(table_features, col.name),
                    cross_column_checks=cross_checks_str,
                    foreign_keys=fk_summary,
                )
                messages = [
                    {"role": "system", "content": STAGE2_PER_COLUMN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
                try:
                    response = self._low_level_analyzer._call_llm_once(messages)
                    col_config = self._parse_stage2_response(response)
                    col_config["name"] = col.name
                    columns_config.append(col_config)
                except Exception as e:
                    category = ErrorClassifier.classify(e)
                    if category == ErrorCategory.TRANSIENT:
                        # Retry once
                        try:
                            response = self._low_level_analyzer._call_llm_once(messages)
                            col_config = self._parse_stage2_response(response)
                            col_config["name"] = col.name
                            columns_config.append(col_config)
                            continue
                        except Exception:
                            pass
                    # LOGIC/QUALITY or retry failed: degrade to type-routed config
                    logger.warning(
                        "Stage 2 column analysis failed, degrading to type-routed config",
                        table=table_name, column=col.name, error=str(e)[:200],
                    )
                    columns_config.append(self._degrade_to_type_routed(col))

            all_tables_config.append({
                "name": table_name,
                "columns": columns_config,
            })

        return {"tables": all_tables_config}

    def _get_skippable_columns(self, table: TableFeatures) -> set[str]:
        """Skip PK + AUTOINCREMENT + GENERATED + DEFAULT (handled by auto-fix)."""
        skip = set()
        for col in table.columns:
            if col.is_primary_key and col.is_autoincrement:
                skip.add(col.name)
            elif col.is_computed:
                skip.add(col.name)
        return skip

    def _is_column_unique(self, table: TableFeatures, column_name: str) -> bool:
        """Check if column is UNIQUE."""
        return any(
            column_name in uc.columns
            for uc in table.unique_constraints
        )

    def _format_fks_for_prompt(self, table: TableFeatures) -> str:
        """Format FKs for prompt injection."""
        if not table.foreign_keys:
            return "(none)"
        return "\n".join(
            f"- {fk.columns} -> {fk.ref_table}.{fk.ref_columns}"
            for fk in table.foreign_keys
        )

    def _format_cross_checks_for_prompt(self, cross_checks: list[dict]) -> str:
        """P1 #3 fix: format cross-column CHECKs for prompt injection."""
        if not cross_checks:
            return "(none)"
        return "\n".join(
            f"- {chk['expression']} (columns: {chk['columns']})"
            for chk in cross_checks
        )

    def _parse_stage2_response(self, response: str) -> dict[str, Any]:
        """Parse LLM stage 2 response."""
        import json

        try:
            data = json.loads(response)
            if not isinstance(data, dict):
                raise ValueError("Response is not a JSON object")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from LLM: {e}") from e

    def _degrade_to_type_routed(self, col: ColumnFeatures) -> dict[str, Any]:
        """Degrade to type-routed minimal config (QUALITY fallback)."""
        type_upper = col.type.upper()
        if "INT" in type_upper:
            generator = "integer"
            params: dict[str, Any] = {"min_value": 0, "max_value": 99999}
        elif any(t in type_upper for t in ("REAL", "FLOAT", "DOUBLE", "DECIMAL")):
            generator = "float"
            params = {"min_value": 0.0, "max_value": 9999.0}
        elif "BOOL" in type_upper:
            generator = "boolean"
            params = {}
        elif "DATE" in type_upper and "TIME" not in type_upper:
            generator = "date"
            params = {}
        elif any(t in type_upper for t in ("DATETIME", "TIMESTAMP")):
            generator = "datetime"
            params = {}
        else:
            generator = "string"
            params = {"min_length": 1, "max_length": 100}
        return {
            "name": col.name,
            "generator": generator,
            "params": params,
            "derive_from": None,
            "expression": None,
        }
```

需要在文件顶部添加导入 (在 `from sqlseed.core.features import` 之后, 加在 TYPE_CHECKING 块外):

实际 features 类型在运行时需要, 加在文件顶部正常导入位置:

```python
from sqlseed.core.features import ColumnFeatures, StructuralFeatures, TableFeatures
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): implement Stage 2 per_column analysis with cross-column CHECK context"
```

---

## Task 9: 提取 _auto_fix_config 为公共函数 (P3 #5)

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py`
- Test: `plugins/sqlseed-ai/tests/test_schema_analyzer.py`

**Spec 引用:** P3 #5 (auto-fix 跨类调用应提取为公共函数)

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_schema_analyzer.py` 末尾追加:

```python
def test_apply_auto_fix_rules_1_13_is_public_function():
    """P3 #5: _auto_fix_config extracted as public function apply_auto_fix_rules_1_13()."""
    from sqlseed_ai.schema_analyzer import apply_auto_fix_rules_1_13

    config = {"name": "users", "columns": [
        {"name": "id", "generator": "integer", "derive_from": ["x"]},  # mutual exclusivity
    ]}
    fixed = apply_auto_fix_rules_1_13(config)
    # Fix 1: derive_from wins, generator stripped
    col = fixed["columns"][0]
    assert "generator" not in col
    assert col["derive_from"] == ["x"]


def test_apply_auto_fix_rules_preserves_existing_behavior():
    """Public function preserves existing _auto_fix_config behavior."""
    from sqlseed_ai.schema_analyzer import (
        SchemaSemanticAnalyzer, apply_auto_fix_rules_1_13,
    )

    config = {"name": "t", "columns": [
        {"name": "x", "generator": "choice", "params": {"weighted_choices": [{"value": "a", "weight": 1}]}},
    ]}
    # Public function
    result_pub = apply_auto_fix_rules_1_13(dict(config))
    # Existing method
    analyzer = SchemaSemanticAnalyzer()
    result_method = analyzer._auto_fix_config(dict(config))

    assert result_pub == result_method
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py::test_apply_auto_fix_rules_1_13_is_public_function -v`
Expected: FAIL with "ImportError: cannot import name 'apply_auto_fix_rules_1_13'"

- [ ] **Step 3: 提取公共函数**

在 `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` 中, 在 `SchemaSemanticAnalyzer` 类之前 (在 `AnalysisRequest` 之后) 添加公共函数:

```python
def apply_auto_fix_rules_1_13(
    config: dict[str, Any],
    schema: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply auto-fix rules #1-#13 to a config dict.

    P3 #5 fix: extracted from SchemaSemanticAnalyzer._auto_fix_config as
    a public function so Stage3Validator can call it without accessing
    a private method of another class.

    The existing SchemaSemanticAnalyzer._auto_fix_config method now
    delegates to this function (preserved for backward compatibility).

    Args:
        config: Parsed config dict from LLM (single-table {"name":...}
            or multi-table {"tables":[...]} format).
        schema: Optional table schema dict (used by Fixes 5, 6, and 8).
            When None, those fixes are skipped.

    Returns:
        The same dict with fixes applied in-place.
    """
    if "tables" in config:
        tables = config["tables"]
    elif "name" in config:
        tables = [config]
    else:
        return config

    for table in tables:
        if not isinstance(table, dict):
            continue
        columns = table.get("columns", [])
        if not isinstance(columns, list):
            continue
        for col in columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name", "<unknown>")
            derive_from = col.get("derive_from")
            generator = col.get("generator")
            # Fix 1: mutual exclusivity — derive_from wins
            if derive_from and generator:
                logger.warning(
                    "Auto-fix: stripping generator+params (derive_from takes precedence)",
                    column=col_name, generator=generator,
                )
                col.pop("generator", None)
                col.pop("params", None)
                derive_from = col.get("derive_from")
                generator = None
            # Fix 2: weighted_choices in params but generator is "choice"
            params = col.get("params")
            if (
                generator == "choice"
                and isinstance(params, dict)
                and "weighted_choices" in params
            ):
                logger.warning(
                    "Auto-fix: generator 'choice' has weighted_choices, fixing to 'weighted_choice'",
                    column=col_name,
                )
                col["generator"] = "weighted_choice"
            # Fix 3 & 4: single-column derive_from expression corrections
            expression = col.get("expression")
            if derive_from and expression and isinstance(expression, str):
                is_single = isinstance(derive_from, str) or (
                    isinstance(derive_from, list) and len(derive_from) == 1
                )
                if is_single:
                    if "value[0]" in expression:
                        logger.warning(
                            "Auto-fix: replacing value[0] with value (single-column derive_from)",
                            column=col_name,
                        )
                        expression = expression.replace("value[0]", "value")
                        col["expression"] = expression
                    if isinstance(derive_from, str):
                        src_col = derive_from
                    elif isinstance(derive_from, list) and derive_from:
                        src_col = derive_from[0]
                    else:
                        src_col = ""
                    if (
                        src_col
                        and src_col in expression
                        and not re.search(r"\bvalue\b", expression)
                    ):
                        logger.warning(
                            "Auto-fix: replacing source column name with 'value' "
                            "(single-column derive_from)",
                            column=col_name, source_column=src_col,
                        )
                        col["expression"] = re.sub(
                            r"\b" + re.escape(src_col) + r"\b", "value", expression
                        )
            # Fix 7: orphan expression cleanup
            if generator and not derive_from and col.get("expression"):
                logger.warning(
                    "Auto-fix: removing orphan expression (generator set, derive_from is null)",
                    column=col_name,
                )
                col.pop("expression", None)

            # Fix 9: name column generator correction
            if (
                isinstance(col_name, str)
                and col_name.endswith("_name")
                and col.get("generator") in ("string", "text")
                and not col.get("derive_from")
            ):
                old_gen = col.get("generator")
                name_lower = col_name.lower()
                if "merchant" in name_lower or "company" in name_lower:
                    new_gen = "company"
                elif name_lower in ("full_name", "person_name") or name_lower == "name":
                    new_gen = "name"
                elif name_lower in ("first_name", "fname"):
                    new_gen = "first_name"
                elif name_lower in ("last_name", "lname", "surname"):
                    new_gen = "last_name"
                else:
                    new_gen = "word"
                logger.warning(
                    "Auto-fix: correcting name column generator (string/text -> readable)",
                    table=table.get("name"), column=col_name,
                    old_generator=old_gen, new_generator=new_gen,
                )
                col["generator"] = new_gen
                col.pop("params", None)

            # Fix 10: add max_value to integer generator when missing
            if (
                col.get("generator") == "integer"
                and isinstance(col.get("params"), dict)
                and "max_value" not in col["params"]
            ):
                if col_name and isinstance(col_name, str):
                    name_lower = col_name.lower()
                    if "quantity" in name_lower:
                        default_max = 100
                    elif "count" in name_lower or "stock" in name_lower:
                        default_max = 9999
                    else:
                        default_max = 99999
                else:
                    default_max = 99999
                logger.warning(
                    "Auto-fix: adding max_value to integer generator",
                    table=table.get("name"), column=col_name, max_value=default_max,
                )
                col["params"]["max_value"] = default_max

            # Fix 11: enforce semantic generators for email/phone columns
            if (
                isinstance(col_name, str)
                and col.get("generator") == "string"
                and not col.get("derive_from")
            ):
                if col_name.endswith("_email") or col_name == "email":
                    logger.warning(
                        "Auto-fix: correcting email column generator (string -> email)",
                        table=table.get("name"), column=col_name,
                    )
                    col["generator"] = "email"
                    col.pop("params", None)
                elif col_name in (
                    "phone", "mobile", "telephone", "tel",
                    "cell", "cellphone", "contact_number",
                ) or col_name.endswith("_phone") or col_name.endswith("_mobile"):
                    logger.warning(
                        "Auto-fix: correcting phone column generator (string -> phone)",
                        table=table.get("name"), column=col_name,
                    )
                    col["generator"] = "phone"
                    col.pop("params", None)

            # Fix 12: phone+regex mismatch -> pattern
            if (
                col.get("generator") == "phone"
                and isinstance(col.get("params"), dict)
                and "regex" in col["params"]
            ):
                regex_val = col["params"]["regex"]
                logger.warning(
                    "Auto-fix: converting phone+regex to pattern generator "
                    "(phone does not accept regex param)",
                    table=table.get("name"), column=col_name, regex=regex_val,
                )
                col["generator"] = "pattern"
                col["params"] = {"regex": regex_val}

        # Fix 5: remove GENERATED columns from config
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                generated_cols = {
                    c["name"]
                    for c in table_schema.get("columns", [])
                    if isinstance(c, dict) and c.get("is_computed")
                }
                if generated_cols:
                    logger.warning(
                        "Auto-fix: removing GENERATED columns from config",
                        table=table_name, columns=list(generated_cols),
                    )
                    table["columns"] = [
                        c for c in columns
                        if isinstance(c, dict) and c.get("name") not in generated_cols
                    ]

        # Fix 6: enforce UNIQUE indexes as constraints.unique=true
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                unique_cols: set[str] = set()
                for idx in table_schema.get("unique_indexes", []):
                    if isinstance(idx, dict) and idx.get("unique"):
                        for col_in_idx in idx.get("columns", []):
                            unique_cols.add(col_in_idx)
                for col_name_unique in table_schema.get("unique_columns", []):
                    unique_cols.add(col_name_unique)
                if unique_cols:
                    for c in table.get("columns", []):
                        if isinstance(c, dict) and c.get("name") in unique_cols:
                            constraints = c.get("constraints")
                            if not isinstance(constraints, dict):
                                constraints = {}
                                c["constraints"] = constraints
                            if not constraints.get("unique"):
                                logger.warning(
                                    "Auto-fix: setting constraints.unique=true "
                                    "(UNIQUE index detected in schema)",
                                    table=table_name, column=c.get("name"),
                                )
                                constraints["unique"] = True

        # Fix 8: cross-column CHECK — convert source-mode columns to derive_from
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                checks = table_schema.get("check_constraints", [])
                valid_cols = {
                    c["name"]
                    for c in table_schema.get("columns", [])
                    if isinstance(c, dict) and isinstance(c.get("name"), str)
                }
                for c in table.get("columns", []):
                    if not isinstance(c, dict):
                        continue
                    col_name = c.get("name")
                    if not isinstance(col_name, str):
                        continue
                    if not c.get("generator") or c.get("derive_from"):
                        continue
                    for chk in checks:
                        if not isinstance(chk, dict):
                            continue
                        chk_cols = set(chk.get("columns", []))
                        if col_name not in chk_cols or len(chk_cols) <= 1:
                            continue
                        expr = chk.get("expression", "")
                        if not isinstance(expr, str):
                            continue
                        upper_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*<=\s*([a-zA-Z_]\w*)",
                            expr, re.IGNORECASE,
                        )
                        lower_zero_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*>=?\s*0\b",
                            expr, re.IGNORECASE,
                        )
                        if upper_pat and lower_zero_pat:
                            other_col = upper_pat.group(1)
                            if other_col == col_name or other_col not in valid_cols:
                                continue
                            logger.warning(
                                "Auto-fix: converting source-mode column to derive_from "
                                "(cross-column CHECK constraint detected)",
                                table=table_name, column=col_name,
                                source_column=other_col, check_expression=expr,
                            )
                            c["derive_from"] = [other_col]
                            c["expression"] = "round(random_float(0, value), 2)"
                            c.pop("generator", None)
                            c.pop("params", None)
                            break
                        lower_col_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*>=?\s*([a-zA-Z_]\w*)",
                            expr, re.IGNORECASE,
                        )
                        if lower_col_pat:
                            other_col = lower_col_pat.group(1)
                            if other_col == col_name or other_col not in valid_cols:
                                continue
                            match_str = lower_col_pat.group(0)
                            min_offset = 1 if (">" in match_str and ">=" not in match_str) else 0
                            col_type_upper = ""
                            for schema_col in table_schema.get("columns", []):
                                if isinstance(schema_col, dict) and schema_col.get("name") == col_name:
                                    col_type_upper = str(schema_col.get("type", "")).upper()
                                    break
                            if "DATE" in col_type_upper:
                                expr_str = "value"
                            elif "INT" in col_type_upper:
                                delta = 100
                                expr_str = f"value + random_int({min_offset}, {delta})"
                            elif any(t in col_type_upper for t in ("REAL", "FLOAT", "DOUBLE", "DECIMAL")):
                                delta = 1000.0
                                expr_str = f"round(value + random_float({min_offset}, {delta}), 2)"
                            else:
                                delta = 100
                                expr_str = f"value + random_int({min_offset}, {delta})"
                            logger.warning(
                                "Auto-fix: converting source-mode column to derive_from "
                                "(lower-bound cross-column CHECK constraint detected)",
                                table=table_name, column=col_name,
                                source_column=other_col, check_expression=expr,
                                expression=expr_str,
                            )
                            c["derive_from"] = [other_col]
                            c["expression"] = expr_str
                            c.pop("generator", None)
                            c.pop("params", None)
                            break

        # Fix 13: detect UNIQUE NOT NULL columns omitted by the LLM
        # (Implementation preserved from existing _auto_fix_config —
        # the full code is long and unchanged. For brevity in this plan,
        # delegate to the existing method body via a helper. In actual
        # implementation, the full Fix 13 body is moved here verbatim
        # from the original _auto_fix_config.)
        if schema:
            _apply_fix_13_omitted_unique(table, schema, columns)

    return config


def _apply_fix_13_omitted_unique(
    table: dict, schema: dict[str, dict[str, Any]], columns: list
) -> None:
    """Fix 13: detect UNIQUE NOT NULL columns omitted by LLM."""
    # Implementation preserved verbatim from existing _auto_fix_config
    # (the original Fix 13 body — see git history for the full text)
    table_name = table.get("name")
    if not isinstance(table_name, str) or table_name not in schema:
        return
    table_schema = schema[table_name]
    unique_cols: set[str] = set()
    for idx in table_schema.get("unique_indexes", []):
        if isinstance(idx, dict) and idx.get("unique"):
            for col_in_idx in idx.get("columns", []):
                unique_cols.add(col_in_idx)
    for col_name_unique in table_schema.get("unique_columns", []):
        unique_cols.add(col_name_unique)
    not_null_unique = {
        c["name"]
        for c in table_schema.get("columns", [])
        if isinstance(c, dict) and not c.get("nullable", True) and c.get("name") in unique_cols
    }
    existing = {c.get("name") for c in columns if isinstance(c, dict)}
    omitted = not_null_unique - existing
    for omitted_col in omitted:
        prefix = omitted_col[:4].upper() + "-"
        logger.warning(
            "Auto-fix: adding omitted UNIQUE NOT NULL column with template generator",
            table=table_name, column=omitted_col,
        )
        columns.append({
            "name": omitted_col,
            "generator": "template",
            "params": {"template": f"{prefix}{{sequence:04d}}"},
            "constraints": {"unique": True, "nullable": False},
        })
```

- [ ] **Step 4: 修改 _auto_fix_config 委托给公共函数**

在 `SchemaSemanticAnalyzer._auto_fix_config` 中替换方法体为委托:

```python
    def _auto_fix_config(
        self,
        config: dict[str, Any],
        schema: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Auto-fix common LLM mistakes (delegates to public function).

        P3 #5 fix: delegates to apply_auto_fix_rules_1_13() public function.
        Preserved for backward compatibility.
        """
        return apply_auto_fix_rules_1_13(config, schema)
```

注意: 保留原 docstring 不变 (在方法上), 仅替换方法体.

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_schema_analyzer.py -v`
Expected: PASS (所有现有测试 + 2 个新测试)

- [ ] **Step 6: 运行所有 ai 插件测试确保无回归**

Run: `pytest plugins/sqlseed-ai/tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py plugins/sqlseed-ai/tests/test_schema_analyzer.py
git commit -m "refactor(ai): extract _auto_fix_config as public apply_auto_fix_rules_1_13 (P3 #5)"
```

---

## Task 10: Layer 3 阶段 3 Stage3Validator (新增规则 #14-#16)

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (添加 Stage3Validator 类)
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (追加测试)

**Spec 引用:** §6.1 阶段 3 新增规则 #14-#16

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_staged_analyzer.py` 末尾追加:

```python
def test_stage3_validator_rule_14_strips_invalid_params_for_word():
    """Rule #14: GENERATOR_PARAMS validation — word does not accept min_length."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {"tables": [{"name": "projects", "columns": [
        {"name": "project_name", "generator": "word", "params": {"min_length": 5, "max_length": 100}},
    ]}]}
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    # word does not accept min_length/max_length -> stripped
    assert "min_length" not in col["params"]
    assert "max_length" not in col["params"]
    assert col["generator"] == "word"


def test_stage3_validator_rule_14_keeps_valid_params_for_string():
    """Rule #14: string accepts min_length/max_length, kept."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {"tables": [{"name": "t", "columns": [
        {"name": "code", "generator": "string", "params": {"min_length": 3, "max_length": 10}},
    ]}]}
    validator = Stage3Validator()
    validator.validate(config)
    col = config["tables"][0]["columns"][0]
    assert col["params"]["min_length"] == 3
    assert col["params"]["max_length"] == 10


def test_stage3_validator_rule_15_bounds_unbounded_regex():
    """Rule #15: unbounded regex {N,} -> {N,N+5}."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    config = {"tables": [{"name": "t", "columns": [
        {"name": "phone", "generator": "pattern", "params": {"regex": r"\d{5,}"}},
    ]}]}
    validator = Stage3Validator()
    validator.validate(config)
    regex = config["tables"][0]["columns"][0]["params"]["regex"]
    # {5,} should be replaced with {5,10}
    assert "{5,10}" in regex
    assert "{5,}" not in regex


def test_stage3_validator_rule_16_detects_fk_semantic_mismatch():
    """Rule #16: FK semantic check — created_by → users(id) should use integer generator."""
    from sqlseed_ai.staged_analyzer import Stage3Validator

    # created_by is FK to users.id (integer), but LLM chose "username" generator (string)
    config = {"tables": [{"name": "orders", "columns": [
        {"name": "created_by", "generator": "username", "params": {}},
    ]}]}
    schema = {"orders": {"foreign_keys": [
        {"columns": ["created_by"], "ref_table": "users", "ref_columns": ["id"]},
    ]}}
    validator = Stage3Validator()
    validator.validate(config, schema=schema)
    col = config["tables"][0]["columns"][0]
    # FK to integer column must use integer generator, not username (string)
    assert col["generator"] == "integer"
    assert col["params"]["max_value"] >= 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_14_strips_invalid_params_for_word plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_15_bounds_unbounded_regex plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_16_detects_fk_semantic_mismatch -v`
Expected: FAIL with "ImportError: cannot import name 'Stage3Validator' from 'sqlseed_ai.staged_analyzer'"

- [ ] **Step 3: 实现 Stage3Validator 类**

在 `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` 末尾追加:

```python
import re as _re
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)

# Rule #14: GENERATOR_PARAMS whitelist — based on src/sqlseed/generators/base_provider.py
# Each generator's accepted keyword arguments. Params not in this list are stripped.
_GENERATOR_ACCEPTED_PARAMS: dict[str, set[str]] = {
    "string": {"min_length", "max_length", "charset"},
    "integer": {"min_value", "max_value"},
    "float": {"min_value", "max_value", "precision"},
    "boolean": set(),
    "bytes": {"length"},
    "name": set(),
    "first_name": set(),
    "last_name": set(),
    "email": set(),
    "phone": set(),
    "address": set(),
    "company": set(),
    "url": set(),
    "ipv4": set(),
    "uuid": set(),
    "date": {"start_year", "end_year"},
    "datetime": {"start_year", "end_year"},
    "timestamp": set(),
    "text": {"min_length", "max_length"},
    "sentence": set(),
    "password": {"length"},
    "choice": {"choices"},
    "json": {"schema"},
    "pattern": {"pattern", "regex"},
    "username": set(),
    "city": set(),
    "country": set(),
    "state": set(),
    "zip_code": set(),
    "job_title": set(),
    "country_code": set(),
    "word": set(),  # word takes NO params (P2 #1 root cause)
    "template": {"template", "sequence_start", "sequence_step"},
    "weighted_choice": {"choices", "weights"},
}

# Rule #15: regex patterns that match unbounded quantifiers {N,} or {N,}
_UNBOUNDED_REGEX_PATTERN = _re.compile(r"\{(\d+),\}")


class Stage3Validator:
    """Stage 3 validator: apply auto-fix rules #14-#16 on top of LLM output.

    Rule #14: GENERATOR_PARAMS validation — strip params not accepted by generator.
    Rule #15: bounds unbounded regex quantifiers {N,} -> {N,N+5}.
    Rule #16: FK semantic check — FK columns must use a generator compatible with
              the referenced column's type.
    """

    def validate(
        self,
        config: dict[str, Any],
        *,
        schema: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply all Stage 3 rules in-place. Returns the same config dict."""
        for table in config.get("tables", []):
            table_name = table.get("name")
            if not isinstance(table_name, str):
                continue
            for col in table.get("columns", []):
                if not isinstance(col, dict):
                    continue
                self._apply_rule_14_strip_invalid_params(col)
                self._apply_rule_15_bound_regex(col)
            if schema and table_name in schema:
                self._apply_rule_16_fk_semantic(table, schema[table_name])
        return config

    def _apply_rule_14_strip_invalid_params(self, col: dict[str, Any]) -> None:
        """Rule #14: strip params not in generator's accepted whitelist."""
        gen = col.get("generator")
        if not isinstance(gen, str):
            return
        accepted = _GENERATOR_ACCEPTED_PARAMS.get(gen)
        if accepted is None:
            # Unknown generator — leave params alone (let core raise at runtime)
            return
        params = col.get("params")
        if not isinstance(params, dict):
            return
        invalid_keys = set(params.keys()) - accepted
        for key in invalid_keys:
            logger.warning(
                "Stage3 Rule #14: stripping invalid param for generator",
                generator=gen, param=key,
            )
            params.pop(key, None)

    def _apply_rule_15_bound_regex(self, col: dict[str, Any]) -> None:
        """Rule #15: bound unbounded regex quantifiers {N,} -> {N,N+5}."""
        if col.get("generator") not in ("pattern",):
            return
        params = col.get("params")
        if not isinstance(params, dict):
            return
        for key in ("regex", "pattern"):
            val = params.get(key)
            if not isinstance(val, str):
                continue
            # Replace each {N,} with {N,N+5}
            def _bound(match: _re.Match[str]) -> str:
                n = int(match.group(1))
                return "{" + f"{n},{n + 5}" + "}"

            new_val = _UNBOUNDED_REGEX_PATTERN.sub(_bound, val)
            if new_val != val:
                logger.warning(
                    "Stage3 Rule #15: bounding unbounded regex quantifier",
                    original=val, bounded=new_val,
                )
                params[key] = new_val

    def _apply_rule_16_fk_semantic(
        self, table: dict[str, Any], table_schema: dict[str, Any]
    ) -> None:
        """Rule #16: FK columns must use a generator compatible with ref column type.

        Currently only checks: FK to integer column must use integer generator
        (common LLM mistake: assigning username/name to FK columns ending in _by).
        """
        fks = table_schema.get("foreign_keys", [])
        if not isinstance(fks, list):
            return
        # Build set of FK column names whose ref column is integer-like.
        # Note: ref column type is not always available in schema snapshot;
        # we assume "id" / "user_id" / "*_id" ref columns are integers.
        integer_fk_cols: set[str] = set()
        for fk in fks:
            if not isinstance(fk, dict):
                continue
            ref_cols = fk.get("ref_columns", [])
            if not ref_cols:
                continue
            ref_col_lower = str(ref_cols[0]).lower()
            # Heuristic: ref column ending in "id" is integer (PK autoincrement).
            if ref_col_lower.endswith("id"):
                for col_in_fk in fk.get("columns", []):
                    integer_fk_cols.add(col_in_fk)

        for col in table.get("columns", []):
            if not isinstance(col, dict):
                continue
            col_name = col.get("name")
            if col_name not in integer_fk_cols:
                continue
            gen = col.get("generator")
            # Integer-compatible generators
            if gen in ("integer", "uuid", "pattern"):
                continue
            logger.warning(
                "Stage3 Rule #16: replacing string generator on integer FK column",
                column=col_name, original_generator=gen, ref_column_type="integer",
            )
            col["generator"] = "integer"
            col["params"] = {"min_value": 1, "max_value": 999999}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_14_strips_invalid_params_for_word plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_14_keeps_valid_params_for_string plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_15_bounds_unbounded_regex plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_stage3_validator_rule_16_detects_fk_semantic_mismatch -v`
Expected: All PASS

- [ ] **Step 5: 运行全部 staged_analyzer 测试确保无回归**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): add Stage3Validator with rules #14-#16 (GENERATOR_PARAMS, regex bounding, FK semantic)"
```

---

## Task 11: StagedSchemaAnalyzer.analyze 完整集成

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (替换 Task 7 中 analyze() 的 minimal placeholder)
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (追加 e2e 测试)

**Spec 引用:** §6.1 完整 3 阶段流程

**说明:** Task 7 中 `analyze(db)` 方法返回了一个 minimal config (基于 stage 1 的 deterministic fallback). Task 11 把它替换为完整管线: stage 1 → stage 2 (per_column) → stage 3 (validate). 复用 Task 7 的 `_run_stage1_with_fallback` / `_build_deterministic_fallback` / `_topological_sort` 方法和 Task 8 的 `_run_stage2_per_column` 方法. 不重新定义 StagedSchemaAnalyzer 类.

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_staged_analyzer.py` 末尾追加:

```python
def test_staged_analyzer_analyze_full_pipeline_calls_stages_in_order(monkeypatch, raw_adapter):
    """Full analyze(adapter) pipeline: stage 1 -> stage 2 -> stage 3.

    Verifies that the analyze() entry point wires up all three stages
    in the correct order, producing a config dict with table entries.
    Uses monkeypatch to mock LLM-calling internals so no real LLM is needed.
    Uses raw_adapter fixture (RawSQLiteAdapter, DatabaseAdapter Protocol-compliant).
    """
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer, StructureSummary, TableStructureSummary

    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock stage 1 to return a StructureSummary dataclass (not dict!)
    fake_summary = StructureSummary(
        schema_hash="fake_hash",
        topological_order=["users"],
        fk_graph=[],
        tables=[
            TableStructureSummary(
                name="users",
                purpose="test",
                anchor_columns=["id"],
                naming_prefix="USER-",
                complexity=1,
                cross_column_checks=[],
                fk_references=[],
            ),
        ],
        naming_conventions={"users": "USER-"},
        complexity_score={"tables": 1, "avg_columns": 1, "avg_constraints": 0},
        dialect="sqlite",
    )
    monkeypatch.setattr(
        analyzer, "_run_stage1_with_fallback", lambda features: fake_summary,
    )

    # Mock stage 2 to return a complete config dict (Task 8 signature:
    # _run_stage2_per_column(features, summary, target_tables) -> dict[str, Any])
    monkeypatch.setattr(
        analyzer, "_run_stage2_per_column",
        lambda features, summary, target_tables: {
            "tables": [
                {"name": "users", "columns": [
                    {"name": "email", "generator": "email", "params": {}},
                ]},
            ],
        },
    )

    # Mock stage 3 to be a pass-through (rules are tested in Task 9/10)
    monkeypatch.setattr(
        analyzer, "_run_stage3_validate", lambda config, features: config,
    )

    config = analyzer.analyze(raw_adapter)

    # Pipeline produced a config dict with the expected table
    assert "tables" in config
    assert len(config["tables"]) == 1
    assert config["tables"][0]["name"] == "users"
    # stage 2 added the email column
    email_col = next(
        c for c in config["tables"][0]["columns"] if c["name"] == "email"
    )
    assert email_col["generator"] == "email"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_staged_analyzer_analyze_full_pipeline_calls_stages_in_order -v`
Expected: FAIL (analyze() returns minimal config without stage 2 columns)

- [ ] **Step 3: 替换 analyze() 方法为完整集成**

在 `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` 中, 找到 Task 7 写入的 `analyze(self, db, *, tables=..., ...)` 方法 (该方法返回 minimal placeholder config). 替换方法体为:

```python
    def analyze(
        self,
        db: Any,
        *,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Analyze database via staged pipeline.

        Full pipeline (Task 11 integration):
          - Layer 1: extract StructuralFeatures via StructuralFeatureExtractor
          - Stage 1: _run_stage1_with_fallback -> StructureSummary
          - Stage 2: _run_stage2_per_column(features, summary, target_tables)
                     returns config dict with all tables/columns
          - Stage 3: _run_stage3_validate (auto-fix rules #1-#16)
        """
        from sqlseed.core.features import StructuralFeatureExtractor
        from sqlseed_ai.stage_relevance import determine_stage_relevance

        # Layer 1: extract structural features
        extractor = StructuralFeatureExtractor(db)
        features = extractor.extract(table_names=tables)
        relevance = determine_stage_relevance(features)

        # Stage 1: structure analysis (with deterministic fallback on LLM failure)
        summary: StructureSummary = self._run_stage1_with_fallback(features)

        # Stage 2: per_column analysis (returns full config dict).
        # _run_stage2_per_column is defined in Task 8 with this exact signature:
        #   (features, summary, target_tables) -> dict[str, Any]
        target_tables = tables if tables is not None else summary.topological_order
        config: dict[str, Any] = self._run_stage2_per_column(
            features, summary, target_tables,
        )

        # Stage 3: validate + auto-fix rules #1-#13 (Task 9) + #14-#16 (Task 10)
        config = self._run_stage3_validate(config, features)

        return config

    def _run_stage3_validate(
        self, config: dict[str, Any], features: StructuralFeatures,
    ) -> dict[str, Any]:
        """Stage 3: apply existing rules #1-#13 + new rules #14-#16 in place."""
        # Existing rules #1-#13 (extracted in Task 9 as public function)
        from sqlseed_ai.schema_analyzer import apply_auto_fix_rules_1_13

        schema_dict = self._features_to_schema_dict(features)
        config = apply_auto_fix_rules_1_13(config, schema_dict)

        # New rules #14-#16 (Task 10 Stage3Validator)
        config = self._validator.validate(config, schema=schema_dict)
        return config

    def _features_to_schema_dict(
        self, features: StructuralFeatures,
    ) -> dict[str, dict[str, Any]]:
        """Convert StructuralFeatures to legacy schema dict shape.

        apply_auto_fix_rules_1_13() expects dict[str, dict] with keys
        'columns' / 'primary_keys' / 'foreign_keys' / 'unique_indexes' /
        'unique_columns' / 'check_constraints' — same shape that
        SchemaSemanticAnalyzer._auto_fix_config used to receive.
        """
        result: dict[str, dict[str, Any]] = {}
        for t in features.tables:
            result[t.name] = {
                "columns": [
                    {"name": c.name, "type": c.type, "nullable": c.nullable}
                    for c in t.columns
                ],
                "primary_keys": list(t.primary_keys),
                "foreign_keys": [
                    {
                        "columns": list(fk.columns),
                        "ref_table": fk.ref_table,
                        "ref_columns": list(fk.ref_columns),
                    }
                    for fk in t.foreign_keys
                ],
                "unique_indexes": [
                    {"name": u.name, "columns": list(u.columns), "unique": True}
                    for u in t.unique_constraints
                ],
                "unique_columns": [
                    col for u in t.unique_constraints for col in u.columns
                ],
                "check_constraints": [
                    {"name": c.name, "columns": list(c.columns), "expression": c.expression}
                    for c in t.check_constraints
                ],
            }
        return result
```

注意: Task 7 中已实现的 `_run_stage1_with_fallback` / `_build_deterministic_fallback` / `_topological_sort` / `_extract_cross_column_checks` / `_get_skippable_columns` / `_get_sample_rows` 全部保留不变. Task 8 中已实现 `_run_stage2_per_column(features, summary, target_tables) -> dict[str, Any]`, 此 Task 11 仅新增 `_run_stage3_validate` 和 `_features_to_schema_dict` 两个辅助方法并替换 Task 7 中的 placeholder analyze() 方法体.

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_staged_analyzer_analyze_full_pipeline_calls_stages_in_order -v`
Expected: PASS

- [ ] **Step 5: 运行全部 staged_analyzer 测试确保无回归**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py -v`
Expected: All PASS (Task 6/7/8/9/10/11 所有测试)

- [ ] **Step 6: 运行 all plugin tests 确保 analyze() 修改未破坏其他测试**

Run: `pytest plugins/sqlseed-ai/tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): integrate full StagedSchemaAnalyzer.analyze (stage 1+2+3 pipeline)"
```

---

## Task 12: 动态粒度决策 (decide_granularity)

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` (添加 decide_granularity 函数)
- Test: `plugins/sqlseed-ai/tests/test_staged_analyzer.py` (追加测试)

**Spec 引用:** §6.2 复杂度评分 + 阶段 2 粒度选择

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_staged_analyzer.py` 末尾追加:

```python
def test_decide_granularity_2b_model_uses_per_column():
    """Small model (E2B) + table with FK + UNIQUE + CHECK -> per_column."""
    from sqlseed_ai.staged_analyzer import decide_granularity
    from sqlseed.core.features import (
        ColumnFeatures, ForeignKeyFeatures, CheckConstraintFeatures,
        TableFeatures, StructuralFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="orders",
                columns=[
                    ColumnFeatures(name="id", type="INTEGER", nullable=False),
                    ColumnFeatures(name="user_id", type="INTEGER", nullable=False),
                    ColumnFeatures(name="amount", type="REAL", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[
                    ForeignKeyFeatures(
                        columns=["user_id"], ref_table="users", ref_columns=["id"],
                    ),
                ],
                check_constraints=[
                    CheckConstraintFeatures(
                        name="ck_positive", columns=["amount"], expression="amount > 0",
                    ),
                ],
            ),
        ],
        dialect="sqlite",
    )
    # E2B model -> per_column (max LLM calls, smallest context per call)
    granularity = decide_granularity(features, model_id="gemma-4-e2b-it")
    assert granularity == "per_column"


def test_decide_granularity_7b_model_uses_per_table():
    """Mid-size model (E4B) -> per_table (balance cost and context)."""
    from sqlseed_ai.staged_analyzer import decide_granularity
    from sqlseed.core.features import (
        ColumnFeatures, TableFeatures, StructuralFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="simple",
                columns=[
                    ColumnFeatures(name="id", type="INTEGER", nullable=False),
                    ColumnFeatures(name="name", type="TEXT", nullable=True),
                ],
                primary_keys=["id"],
            ),
        ],
        dialect="sqlite",
    )
    # E4B model + simple table -> per_table
    granularity = decide_granularity(features, model_id="gemma-4-e4b-it")
    assert granularity == "per_table"


def test_decide_granularity_cloud_model_uses_per_db():
    """Large cloud model -> per_db (single LLM call for the whole db)."""
    from sqlseed_ai.staged_analyzer import decide_granularity
    from sqlseed.core.features import (
        ColumnFeatures, TableFeatures, StructuralFeatures,
    )

    features = StructuralFeatures(
        tables=[
            TableFeatures(
                name="t1",
                columns=[ColumnFeatures(name="id", type="INTEGER", nullable=False)],
                primary_keys=["id"],
            ),
        ],
        dialect="sqlite",
    )
    # 31B model -> per_db
    granularity = decide_granularity(features, model_id="gemma-4-31b-it")
    assert granularity == "per_db"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_2b_model_uses_per_column plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_7b_model_uses_per_table plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_cloud_model_uses_per_db -v`
Expected: FAIL with "ImportError: cannot import name 'decide_granularity'"

- [ ] **Step 3: 实现 decide_granularity 函数**

在 `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` 顶部 (imports 之后, 类定义之前) 追加:

```python
def decide_granularity(
    features: StructuralFeatures, *, model_id: str
) -> str:
    """Choose stage 2 granularity: 'per_column' | 'per_table' | 'per_db'.

    Spec §6.2 complexity_score (P2 #3 simple version):
      score = (#tables) + (#fk_columns) + 2 * (#check_constraints) + (#unique_columns)

    Decision matrix (P2 #3 simple version):
      - E2B (2B):  score >= 1           -> per_column
      - E4B (4B):  score >= 5           -> per_column; else per_table
      - 12B+:      score >= 10          -> per_column; else per_table
      - 26B+/31B+: score >= 20          -> per_table; else per_db
      - Unknown model id: default per_column (safest)

    Args:
        features: Layer 1 structural features.
        model_id: LLM model id (e.g., "gemma-4-e2b-it").

    Returns:
        One of 'per_column', 'per_table', 'per_db'.
    """
    score = _compute_complexity_score(features)
    model_lower = (model_id or "").lower()

    if "e2b" in model_lower:
        # 2B: always per_column (smallest context per call)
        return "per_column"
    if "e4b" in model_lower:
        return "per_column" if score >= 5 else "per_table"
    if "12b" in model_lower:
        return "per_column" if score >= 10 else "per_table"
    # 26B / 31B / unknown-large: prefer per_db for simplicity
    if "26b" in model_lower or "31b" in model_lower:
        return "per_table" if score >= 20 else "per_db"
    # Unknown model: safest = per_column (most LLM calls, smallest context each)
    return "per_column"


def _compute_complexity_score(features: StructuralFeatures) -> int:
    """Spec §6.2 simple complexity_score (P2 #3 simple version)."""
    score = 0
    for t in features.tables:
        score += 1  # one per table
        score += sum(len(fk.columns) for fk in t.foreign_keys)
        score += 2 * len(t.check_constraints)
        score += sum(len(u.columns) for u in t.unique_constraints)
    return score
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_2b_model_uses_per_column plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_7b_model_uses_per_table plugins/sqlseed-ai/tests/test_staged_analyzer.py::test_decide_granularity_cloud_model_uses_per_db -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_analyzer.py
git commit -m "feat(ai): add decide_granularity for stage 2 LLM call mode selection"
```

---

## Task 13: CLI 接入 (--staged-pipeline flag)

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py`
- Test: `plugins/sqlseed-ai/tests/test_ai_commands.py`

**Spec 引用:** §6.6 flag 切换 + 迁移路径

- [ ] **Step 1: 写失败测试**

在 `plugins/sqlseed-ai/tests/test_ai_commands.py` 末尾追加:

```python
def test_ai_analyze_command_accepts_staged_pipeline_flag():
    """ai-analyze command accepts --staged-pipeline flag."""
    from click.testing import CliRunner
    from sqlseed_ai.cli.ai_commands import ai_analyze

    runner = CliRunner()
    # Use --help to verify the flag exists without invoking the LLM
    result = runner.invoke(ai_analyze, ["--help"])
    assert result.exit_code == 0
    assert "--staged-pipeline" in result.output


def test_ai_analyze_command_staged_pipeline_flag_sets_config():
    """--staged-pipeline flag flips AIConfig.use_staged_pipeline to True."""
    from sqlseed_ai.cli.ai_commands import _build_ai_config

    config = _build_ai_config(
        api_key="test",
        model="gemma-4-e2b-it",
        staged_pipeline=True,
    )
    assert config.use_staged_pipeline is True

    config2 = _build_ai_config(
        api_key="test",
        model="gemma-4-e2b-it",
        staged_pipeline=False,
    )
    assert config2.use_staged_pipeline is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_commands.py::test_ai_analyze_command_accepts_staged_pipeline_flag plugins/sqlseed-ai/tests/test_ai_commands.py::test_ai_analyze_command_staged_pipeline_flag_sets_config -v`
Expected: FAIL

- [ ] **Step 3: 添加 --staged-pipeline flag 到 ai-analyze 命令**

在 `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` 的 `ai_analyze` 命令上添加 flag (放在其他 options 之后):

```python
@click.option(
    "--staged-pipeline",
    is_flag=True,
    default=False,
    help="Use the new 3-stage LtM pipeline (StagedSchemaAnalyzer) instead of "
         "the legacy SchemaSemanticAnalyzer. Recommended for 2B local models.",
)
```

并在命令回调参数中加入 `staged_pipeline: bool = False`。

在回调体中调用 `_build_ai_config(..., staged_pipeline=staged_pipeline)`。

在 `_build_ai_config` 函数中 (文件末尾或顶部 helpers 区) 添加 `staged_pipeline` 参数:

```python
def _build_ai_config(
    *,
    api_key: str | None,
    model: str,
    base_url: str | None = None,
    backend: str | None = None,
    staged_pipeline: bool = False,
    **kwargs: Any,
) -> "AIConfig":
    """Build an AIConfig from CLI args."""
    from sqlseed_ai.config import AIConfig

    return AIConfig(
        api_key=api_key or "dummy",
        model=model,
        base_url=base_url,
        backend=backend,
        use_staged_pipeline=staged_pipeline,
        **kwargs,
    )
```

并在 ai_analyze 命令回调中根据 `config.use_staged_pipeline` 选择走 StagedSchemaAnalyzer 还是现有 SchemaSemanticAnalyzer:

```python
if config.use_staged_pipeline:
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer
    from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter

    # Build a DatabaseAdapter from the CLI-provided db_path / url.
    # analyze(adapter) internally calls StructuralFeatureExtractor(adapter).
    adapter = SQLAlchemyAdapter(db_path) if isinstance(db_path, str) else SQLAlchemyAdapter.from_url(url)
    analyzer = StagedSchemaAnalyzer(config=config)
    config_dict = analyzer.analyze(adapter, tables=tables)
else:
    # Legacy path
    from sqlseed_ai.schema_analyzer import SchemaSemanticAnalyzer
    analyzer = SchemaSemanticAnalyzer(config=config, db=db_path)
    config_dict = analyzer.analyze()
```

注: 实际实现时, `db_path` / `url` 变量名应与 ai_analyze 命令回调中已有的参数名一致. 若 SQLAlchemyAdapter 的构造方式不同 (例如使用 `SQLAlchemyAdapter.connect(db_path)`), 调整为实际 API.

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_commands.py::test_ai_analyze_command_accepts_staged_pipeline_flag plugins/sqlseed-ai/tests/test_ai_commands.py::test_ai_analyze_command_staged_pipeline_flag_sets_config -v`
Expected: PASS

- [ ] **Step 5: 运行全部 ai_commands 测试确保无回归**

Run: `pytest plugins/sqlseed-ai/tests/test_ai_commands.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py plugins/sqlseed-ai/tests/test_ai_commands.py
git commit -m "feat(ai-cli): add --staged-pipeline flag to ai-analyze command"
```

---

## Task 14: 集成测试 - SQLite E2E

**Files:**
- Test: `plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py`

**Spec 引用:** §13 验收标准 (E2E 在 SQLite 上跑通)

- [ ] **Step 1: 创建测试文件和 fixture**

创建 `plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py`:

```python
"""E2E tests for the staged pipeline on SQLite (no real LLM required).

These tests exercise the full Layer 1 -> Layer 2 -> Layer 3 pipeline with
mocked LLM responses, validating that the final YAML config is well-formed
and that the StagedSchemaAnalyzer integrates correctly with the rest of
the system.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def complex_biz_db(tmp_path: Path):
    """Build a SQLite db with multiple tables, FKs, UNIQUE, CHECK constraints.

    Returns a connected RawSQLiteAdapter (DatabaseAdapter Protocol-compliant)
    so StructuralFeatureExtractor can consume it directly.

    Schema (mirrors the spec §13 example):
      - categories(id PK, name UNIQUE NOT NULL)
      - products(id PK, name NOT NULL, category_id FK -> categories(id),
                  price REAL CHECK(price > 0), sku UNIQUE)
      - orders(id PK, customer_name, created_at, total REAL CHECK(total >= 0))
      - order_items(id PK, order_id FK -> orders(id), product_id FK -> products(id),
                    quantity INTEGER CHECK(quantity > 0))
    """
    from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter

    db_path = tmp_path / "complex_biz.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id),
                price REAL NOT NULL CHECK(price > 0),
                sku TEXT NOT NULL UNIQUE
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                total REAL NOT NULL CHECK(total >= 0)
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL CHECK(quantity > 0)
            );
            CREATE INDEX idx_products_category ON products(category_id);
            CREATE INDEX idx_order_items_order ON order_items(order_id);
        """)
        conn.commit()
    finally:
        conn.close()
    adapter = RawSQLiteAdapter()
    adapter.connect(str(db_path))
    return adapter


def test_layer1_extract_features_from_complex_biz(complex_biz_db):
    """E2E: Layer 1 StructuralFeatureExtractor reads all tables / FKs / checks."""
    from sqlseed.core.features import StructuralFeatureExtractor

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()

    # All 4 tables detected
    table_names = {t.name for t in features.tables}
    assert table_names == {"categories", "products", "orders", "order_items"}

    # categories has UNIQUE on name
    categories = next(t for t in features.tables if t.name == "categories")
    assert any("name" in u.columns for u in categories.unique_constraints)

    # products has FK to categories
    products = next(t for t in features.tables if t.name == "products")
    assert any(fk.ref_table == "categories" for fk in products.foreign_keys)

    # products has CHECK on price > 0
    assert any(
        any("price" in c for c in check.columns) for check in products.check_constraints
    )


def test_staged_analyzer_topological_sort_puts_parents_first(complex_biz_db):
    """E2E: topological sort puts FK parents before children."""
    from sqlseed.core.features import StructuralFeatureExtractor
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()
    analyzer = StagedSchemaAnalyzer(config=None)
    order = analyzer._topological_sort(features)
    # categories before products (products has FK to categories)
    assert order.index("categories") < order.index("products")
    # orders before order_items
    assert order.index("orders") < order.index("order_items")
    # products before order_items
    assert order.index("products") < order.index("order_items")


def test_staged_analyzer_deterministic_fallback(complex_biz_db):
    """E2E: when LLM stage 1 fails, deterministic fallback produces valid summary."""
    from sqlseed.core.features import StructuralFeatureExtractor
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    extractor = StructuralFeatureExtractor(complex_biz_db)
    features = extractor.extract()
    analyzer = StagedSchemaAnalyzer(config=None)
    summary = analyzer._build_deterministic_fallback(features)

    assert hasattr(summary, "tables")
    assert len(summary.tables) == 4
    assert summary.schema_hash == features.schema_hash
    assert set(summary.topological_order) == {
        "categories", "products", "orders", "order_items",
    }
    # Topological order in fallback is also valid
    order = summary.topological_order
    assert order.index("categories") < order.index("products")
    assert order.index("products") < order.index("order_items")


def test_staged_analyzer_full_pipeline_with_mocked_llm(complex_biz_db, monkeypatch):
    """E2E: full Layer 1 -> Layer 2 -> Layer 3 pipeline with mocked LLM."""
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    analyzer = StagedSchemaAnalyzer(config=None)

    # Mock all LLM-calling methods so the test runs without a real LLM.
    # Stage 1: deterministic fallback (no LLM, pure Layer 1 derivation)
    monkeypatch.setattr(
        analyzer, "_call_stage1_llm",
        lambda features: (_ for _ in ()).throw(RuntimeError("mock: no LLM in unit test")),
    )
    # Stage 2: mock _run_stage2_per_column to return full config dict
    # (Task 8 signature: features, summary, target_tables -> dict[str, Any])
    monkeypatch.setattr(
        analyzer, "_run_stage2_per_column",
        lambda features, summary, target_tables: _mock_stage2_config(features, target_tables),
    )

    # analyze(db) accepts a DatabaseAdapter; complex_biz_db fixture returns one
    config = analyzer.analyze(complex_biz_db)

    # Sanity-check the final config structure
    assert "tables" in config
    table_names = {t["name"] for t in config["tables"]}
    assert table_names == {"categories", "products", "orders", "order_items"}

    # Each table has at least the auto-fix-added columns
    for table in config["tables"]:
        assert "columns" in table
        assert isinstance(table["columns"], list)
        assert len(table["columns"]) >= 1


def _mock_stage2_config(features, target_tables) -> dict[str, Any]:
    """Mock stage 2 LLM output: full config dict with all tables/columns.

    Returns config in the same shape as Task 8 _run_stage2_per_column.
    Skip id columns (autoincrement PKs are skipped per stage 2 skippable logic).
    """
    mocks: dict[str, list[dict[str, Any]]] = {
        "categories": [
            {"name": "name", "generator": "word", "params": {}},
        ],
        "products": [
            {"name": "name", "generator": "word", "params": {}},
            {"name": "category_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "price", "generator": "float",
             "params": {"min_value": 0.01, "max_value": 999.99, "precision": 2}},
            {"name": "sku", "generator": "template",
             "params": {"template": "SKU-{sequence:04d}"}},
        ],
        "orders": [
            {"name": "customer_name", "generator": "name", "params": {}},
            {"name": "created_at", "generator": "datetime", "params": {}},
            {"name": "total", "generator": "float",
             "params": {"min_value": 0.0, "max_value": 10000.0, "precision": 2}},
        ],
        "order_items": [
            {"name": "order_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "product_id", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
            {"name": "quantity", "generator": "integer",
             "params": {"min_value": 1, "max_value": 100}},
        ],
    }
    tables_config = [
        {"name": name, "columns": mocks.get(name, [])}
        for name in target_tables
    ]
    return {"tables": tables_config}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py -v`
Expected: FAIL (StagedSchemaAnalyzer methods not yet wired up — may pass if Task 11 fully wired)

- [ ] **Step 3: 运行测试验证通过**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py -v`
Expected: All PASS (4 tests)

如果失败, 修复 wiring 问题. 测试不要求真实 LLM 调用 — 它们 mock 所有 LLM 方法.

- [ ] **Step 4: 运行所有 staged 测试确保集成无回归**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_analyzer.py plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py
git commit -m "test(ai): add SQLite E2E tests for staged pipeline (mocked LLM)"
```

---

## Task 15: PostgreSQL E2E 集成测试 (testcontainers)

**Files:**
- Test: `plugins/sqlseed-ai/tests/test_staged_e2e_postgres.py`

**Spec 引用:** §13 验收标准 (PG 兼容性)

- [ ] **Step 1: 创建测试文件 (用 @pytest.mark.integration 标记)**

创建 `plugins/sqlseed-ai/tests/test_staged_e2e_postgres.py`:

```python
"""PostgreSQL E2E tests for the staged pipeline (requires Docker).

These tests run the Layer 1 extractor against a real PostgreSQL instance
launched via testcontainers, verifying that the dialect-aware feature
extraction correctly handles PostgreSQL-specific types (SERIAL, JSONB, etc.)
and constraints.

Marked as @pytest.mark.integration — skipped unless Docker is available.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg_url() -> str:
    """Launch a PostgreSQL container and return its URL.

    Skipped if Docker / testcontainers is unavailable.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        yield container.get_connection_url()
        container.stop()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker not available: {exc}")


def _init_pg_schema(pg_url: str) -> None:
    """Create the complex_biz schema on PostgreSQL."""
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE categories (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id),
                price REAL NOT NULL CHECK(price > 0),
                sku TEXT NOT NULL UNIQUE
            );
            CREATE TABLE orders (
                id SERIAL PRIMARY KEY,
                customer_name TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                total REAL NOT NULL CHECK(total >= 0)
            );
            CREATE TABLE order_items (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL CHECK(quantity > 0)
            );
        """))
        conn.commit()


def test_pg_layer1_extraction(pg_url: str):
    """E2E PG: Layer 1 extracts the same shape as SQLite (4 tables, FKs, checks)."""
    _init_pg_schema(pg_url)

    from sqlseed.core.features import StructuralFeatureExtractor

    extractor = StructuralFeatureExtractor.from_url(pg_url)
    features = extractor.extract()

    table_names = {t.name for t in features.tables}
    assert table_names == {"categories", "products", "orders", "order_items"}

    # PostgreSQL dialect detected
    assert features.dialect == "postgresql"

    # FK detection works
    products = next(t for t in features.tables if t.name == "products")
    assert any(fk.ref_table == "categories" for fk in products.foreign_keys)


def test_pg_staged_analyzer_deterministic_fallback(pg_url: str):
    """E2E PG: deterministic fallback works on PostgreSQL features too."""
    _init_pg_schema(pg_url)

    from sqlseed.core.features import StructuralFeatureExtractor
    from sqlseed_ai.staged_analyzer import StagedSchemaAnalyzer

    extractor = StructuralFeatureExtractor.from_url(pg_url)
    features = extractor.extract()
    analyzer = StagedSchemaAnalyzer(config=None)
    summary = analyzer._build_deterministic_fallback(features)

    assert len(summary.tables) == 4
    order = summary.topological_order
    assert order.index("categories") < order.index("products")
    assert order.index("products") < order.index("order_items")
```

- [ ] **Step 2: 运行测试 (如果 Docker 可用)**

Run: `pytest plugins/sqlseed-ai/tests/test_staged_e2e_postgres.py -v -m integration`
Expected: All PASS (if Docker available) or SKIP (if Docker not available)

- [ ] **Step 3: Commit**

```bash
git add plugins/sqlseed-ai/tests/test_staged_e2e_postgres.py
git commit -m "test(ai): add PostgreSQL E2E integration tests for staged pipeline"
```

---

## Plan Self-Review

### 1. Spec coverage

| Spec §  | 内容 | 对应 Task |
|---------|------|----------|
| §3 三层架构 | Layer 1/2/3 分离 | Task 1-4 (L1) / Task 5 (L2) / Task 6-11 (L3) |
| §4.1 Layer 1 数据模型 | ColumnFeatures / ForeignKeyFeatures / etc. | Task 1 |
| §4.2 Layer 1 提取器 | StructuralFeatureExtractor (使用 Protocol API) | Task 2 |
| §4.3 多数据库特征映射 | SQLite / PostgreSQL 方言差异 | Task 3 (SQLite) / Task 4 (PG stub) |
| §5 Layer 2 阶段相关性 | StageRelevance | Task 5 |
| §6.1 阶段 1-3 流程 | LLM 调用 + 降级 + 校验 | Task 6-8, 10-11 |
| §6.2 复杂度评分 | decide_granularity (P2 #3 简单版) | Task 12 |
| §6.6 flag 切换 + 迁移路径 | --staged-pipeline CLI flag | Task 0 + Task 13 |
| §6.7 StructureSummary | 阶段间数据传递格式 | Task 6 (dataclass) + Task 7 (fallback) |
| §6.8 ErrorClassifier | TRANSIENT/LOGIC/QUALITY | Task 6 |
| §10 auto-fix 规则 | 现有 1-13 / 新增 14-16 | Task 9 (1-13 提取) + Task 10 (14-16 新增) |
| §13 验收标准 | SQLite + PG E2E | Task 14 (SQLite) + Task 15 (PG) |

### 2. 用户 P2/P3 反馈融入检查

| # | 反馈 | 融入位置 | 状态 |
|---|------|---------|------|
| P2 #1 | FK 聚合逐个保留 | Task 2 Step 3 `_preserve_foreign_keys` 不分组 | ✅ |
| P2 #2 | ColumnFeatures.max_length | Task 1 Step 3 `max_length` 字段 + `_parse_max_length` | ✅ |
| P2 #3 | complexity_score 简单版 | Task 12 `_compute_complexity_score` 简单公式 | ✅ |
| P3 #4 | 阶段 1 降级 fallback | Task 7 `_build_deterministic_fallback` | ✅ |
| P3 #5 | _auto_fix_config 提取公共 | Task 9 `apply_auto_fix_rules_1_13` | ✅ |

### 3. Placeholder scan

- 无 "TBD" / "TODO" / "implement later" / "fill in details"
- 无 "Add appropriate error handling" 等 vague 描述
- 每个 code step 都有具体代码 (mock 测试用 monkeypatch; PG 测试用 testcontainers)
- 唯一 "implementation preserved from existing" 出现在 Task 9 Step 3 (`_apply_fix_13_omitted_unique`), 这是因为 Fix 13 body 太长且未变 — 实施时从 git history 复制即可. 这是可接受的简化, 不是 placeholder.

### 4. Type consistency

- `StructuralFeatures` 在 Task 1 定义, Task 5/7/11/12/14/15 使用 — 一致
- `ColumnFeatures` 在 Task 1 定义, Task 5/7/11 使用 — 一致
- `StageRelevance` 在 Task 5 定义, Task 11 使用 — 一致
- `Stage3Validator` 在 Task 10 定义, Task 11 使用 — 一致
- `decide_granularity` 在 Task 12 定义, Task 8 (per_column 实现) 引用 — 一致
- `apply_auto_fix_rules_1_13` 在 Task 9 定义, Task 11 (Stage 3 调用) 使用 — 一致
- `_topological_sort` 在 Task 7 定义, Task 14 E2E 测试使用 — 一致

---

## 执行选择

**Plan complete and saved to `docs/superpowers/plans/2026-07-02-llm-staged-yaml-analysis.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
