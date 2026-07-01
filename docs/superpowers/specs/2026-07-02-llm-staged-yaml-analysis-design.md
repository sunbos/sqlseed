# LLM 分阶段 YAML 驱动的数据库分析架构设计

**日期**: 2026-07-02
**分支**: `feat/llm-staged-yaml-analysis` (从 `feat/schema-driven-architecture` 拉取)
**目标分支**: 合并回 `feat/schema-driven-architecture`

---

## 1. 背景与问题陈述

### 1.1 当前架构

sqlseed-ai 插件当前的 `ai-analyze` 命令采用 **per-table 单阶段分析**：

- 遍历每张表，每表一次 LLM 调用
- 每次调用输入：1 张表的 DDL + FK 引用信息
- 每次调用输出：该表所有列的完整 config（generator + params + derive_from + expression）
- 失败时由 `AiConfigRefiner` 自纠错循环重试

### 1.2 失败现象

在 `complex_biz.db`（8 表）和 `hr_biz.db`（4 表）上用 Gemma-4-E2B（2B 参数本地模型）测试：

| 数据库 | 表 | 行数 | 失败原因 |
|--------|----|----|---------|
| complex_biz.db | items | 0 | LLM 5 次返回空 config（2B 模型推理能力不足） |
| complex_biz.db | sales | 100 | 100 条 FK 违规（items 表空，FK 无父表 PK 可引用） |
| hr_biz.db | projects | 0 | `word` 生成器 + `min_length` 参数不兼容（ConfigurationError） |
| hr_biz.db | tasks | 0 | projects 失败导致拓扑跳过（级联失败） |

### 1.3 根因分析

**瓶颈不是输入大小，是输出复杂度 + 推理负载**：

- 8 表完整 DDL 仅 ~2.5KB（~700 tokens），远在 8K 上下文窗口内
- 每表输出需 200-400 tokens 结构化 JSON（6 列 × 6 字段 = 36 个同时决策）
- 2B 模型的注意力机制在持有 36 个同时约束时退化：
  - 生成到第 5 列时忘记第 2 列的 CHECK 约束
  - 产出截断 JSON 或直接返回空输出

**核心矛盾**：per-table 模式输出小但失全局视角；whole-DB 模式有全局但输出超 2B 能力。需要折中。

### 1.4 调研结论

通过调研发现 **Least-to-Most Prompting**（Zhou et al. 2022, Google Brain）正是解决此问题的标准技术：

> "each step only adds a small amount of new reasoning on top of explicitly stated prior results, the model never has to reason about more than one additional step at a time"

在 SCAN 基准上，GPT-3 从 CoT 的 16% 跃升到 LtM 的 99%。这直接命中我们的瓶颈——把 36 个同时决策降为 N 个顺序决策，每个只 1 维度。

**GBNF 语法约束解码**：LM Studio 支持但明确警告 "<7B 模型可能不支持"，不能依赖。

**Feather-SQL / DB-Explore / Baidu Data Platform** 等小模型 NL2SQL 研究均采用类似策略：Schema Pruning（剪枝无关表）+ 两步式推理（先链接后生成）+ few-shot 示例。

---

## 2. 设计目标与约束

### 2.1 目标

1. **2B 本地模型必须可用**：保证 Gemma-4-E2B 能稳定分析数据库结构 + 业务逻辑，生成准确 YAML
2. **跨数据库兼容**：支持 SQLite + PostgreSQL，方言无关
3. **时间换空间**：接受更多 LLM 调用换取每阶段输出更小、推理负载更低
4. **最小临时文件**：默认不产生临时文件，YAML 作为最终文件
5. **只解决问题，不新增功能**：不添加触发器/视图数据生成、不添加 MySQL 支持

### 2.2 约束

- **核心代码无业务逻辑**：`src/sqlseed/` 只能有通用 schema 内省，不能有领域特定启发式
- **YAGNI**：Multi-candidate generation（多候选生成）等增强留作未来，本次不实施
- **不修改 `DatabaseAdapter` protocol**：通过新增类扩展，不破坏现有接口
- **不依赖 GBNF 语法约束**：纯 prompting 技术，确保 2B 必可用

---

## 3. 架构总览

### 3.1 三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: 方言感知特征提取 (Dialect-Aware Feature Extraction)      │
│  ├─ SQLite: PRAGMA + sqlite_master 解析                            │
│  ├─ PostgreSQL: pg_catalog + information_schema 查询               │
│  └─ 公共: SQLAlchemy inspect() 统一 API                            │
│  位置: src/sqlseed/core/features.py (核心层, 无业务逻辑)            │
│  输出: StructuralFeatures (归一化数据模型)                         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: 阶段相关性判断 (Stage Relevance Determination)           │
│  消费 StructuralFeatures → 输出 StageRelevance                      │
│  纯规则, 无 LLM, 确定性判断                                        │
│  位置: plugins/sqlseed-ai/stage_relevance.py (AI 插件)              │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: 分阶段 LLM 分析管线 (Staged LLM Analysis Pipeline)       │
│  ├─ 阶段 0 (可选): 数据采样 (部分满载时)                            │
│  ├─ 阶段 1: 结构分析 (1 次调用, 全库或按需范围)                      │
│  ├─ 决策点: 动态选择阶段 2 粒度 (无 LLM)                            │
│  ├─ 阶段 2: 列分析 (N 次调用, 粒度自适应)                           │
│  └─ 阶段 3: 校验 + Auto-fix (无 LLM, 纯规则)                       │
│  位置: plugins/sqlseed-ai/staged_analyzer.py (AI 插件)              │
│  输出: config.yaml (唯一磁盘文件)                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 核心原则

1. **YAML 作为状态机**：每阶段分析结果在内存中传递，仅最终 `config.yaml` 写磁盘
2. **结构性内容按需分析**：FK 关系、依赖图等结构信息缓存按 schema hash，未变化则跳过
3. **按需分析范围**：全表满载分析所有表；部分满载只分析目标表 + FK 父表传递闭包
4. **按需保留特征**：每阶段只保留该阶段需要的结构特征（详见 §5 阶段相关性矩阵）
5. **列级分解**：2B 模型采用 per-column 粒度（1 列/调用），最大化成功率

---

## 4. 多数据库兼容设计

### 4.1 归一化数据模型（方言无关）

位置：`src/sqlseed/core/features.py`（新增，核心层，纯数据结构）

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ColumnFeatures:
    """归一化列特征, 方言无关."""
    name: str
    type: str  # 归一化类型: "TEXT", "INTEGER", "REAL", "DATE", "BOOLEAN", "BLOB"
    nullable: bool
    default: str | None
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool
    computed_expression: str | None  # GENERATED ALWAYS AS (...) 表达式
    collation: str | None  # SQLite: NOCASE/BINARY/RTRIM; PostgreSQL: COLLATION 名

@dataclass
class ForeignKeyFeatures:
    """归一化外键特征, 支持复合 FK."""
    table: str
    columns: list[str]  # 复合 FK 支持多列
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None  # CASCADE/SET NULL/RESTRICT/NO ACTION/SET DEFAULT
    on_update: str | None

@dataclass
class UniqueConstraintFeatures:
    """归一化 UNIQUE 约束, 支持复合."""
    table: str
    columns: list[str]  # 复合 UNIQUE 支持多列
    is_index_based: bool  # True: CREATE UNIQUE INDEX; False: 表级 UNIQUE 约束
    partial_predicate: str | None  # 部分索引的 WHERE 谓词

@dataclass
class CheckConstraintFeatures:
    """归一化 CHECK 约束."""
    table: str
    name: str | None
    expression: str  # 原始 SQL 表达式
    columns: list[str]  # 提取的列引用

@dataclass
class IndexFeatures:
    """归一化索引."""
    table: str
    name: str
    columns: list[str]
    unique: bool
    partial_predicate: str | None

@dataclass
class TableFeatures:
    """归一化表特征."""
    name: str
    columns: list[ColumnFeatures]
    primary_key: list[str]  # 复合 PK 支持多列
    foreign_keys: list[ForeignKeyFeatures]
    unique_constraints: list[UniqueConstraintFeatures]
    check_constraints: list[CheckConstraintFeatures]
    indexes: list[IndexFeatures]
    # SQLite 特有 (PG 中始终为默认值)
    is_strict: bool  # SQLite STRICT 表
    is_without_rowid: bool  # SQLite WITHOUT ROWID 表
    on_conflict: str | None  # SQLite ON CONFLICT 子句: ROLLBACK/ABORT/FAIL/IGNORE/REPLACE

@dataclass
class DialectSpecificFeatures:
    """方言特有特征, 不在通用模型中."""
    dialect: str  # "sqlite" | "postgresql"
    features: dict[str, Any]  # 如 {"sqlite": {"type_affinity": {...}}, "postgresql": {"sequences": [...]}}

@dataclass
class StructuralFeatures:
    """完整的归一化 schema 特征, 方言无关."""
    dialect: str  # "sqlite" | "postgresql"
    tables: list[TableFeatures]
    views: list[str]
    dialect_specific: DialectSpecificFeatures | None
    schema_hash: str  # 用于缓存判断
```

### 4.2 特征提取器

位置：`src/sqlseed/core/features.py`（新增，核心层）

```python
class StructuralFeatureExtractor:
    """从任何支持的数据库提取结构特征."""

    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter
        self.dialect = adapter.dialect  # "sqlite" | "postgresql"

    def extract(self, table_names: list[str] | None = None) -> StructuralFeatures:
        """
        提取结构特征.

        Args:
            table_names: None 提取所有表; 提供则只提取指定表 + FK 父表闭包 (按需分析)
        """
        # 1. 确定分析范围 (按需: 目标表 + FK 父表传递闭包)
        tables_to_analyze = self._resolve_scope(table_names)

        # 2. 公共提取 (通过 SQLAlchemy inspect(), 所有方言通用)
        tables = [self._extract_table_common(name) for name in tables_to_analyze]

        # 3. 方言特有扩展
        dialect_specific = self._extract_dialect_specific(tables_to_analyze)

        # 4. 计算 schema hash (用于缓存)
        schema_hash = self._compute_schema_hash(tables)

        return StructuralFeatures(
            dialect=self.dialect,
            tables=tables,
            views=self.adapter.get_view_names(),
            dialect_specific=dialect_specific,
            schema_hash=schema_hash,
        )

    def _resolve_scope(self, table_names: list[str] | None) -> list[str]:
        """按需分析: 全表或目标表 + FK 父表传递闭包."""
        if table_names is None:
            return self.adapter.get_table_names()
        # 传递闭包: 收集所有 FK 父表
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
        """公共提取: 通过 SQLAlchemy inspect(), 所有方言通用."""
        columns = self._normalize_columns(self.adapter.get_columns(table_name))
        pk = self.adapter.get_pk_constraint(table_name).get("constrained_columns", [])
        fks = self._normalize_foreign_keys(self.adapter.get_foreign_keys(table_name))
        unique_constraints = self._normalize_unique(self.adapter.get_unique_constraints(table_name))
        check_constraints = self._normalize_check(self.adapter.get_check_constraints(table_name))
        indexes = self._normalize_indexes(self.adapter.get_indexes(table_name))

        return TableFeatures(
            name=table_name,
            columns=columns,
            primary_key=pk,
            foreign_keys=fks,
            unique_constraints=unique_constraints,
            check_constraints=check_constraints,
            indexes=indexes,
            is_strict=False,  # 默认, SQLite 特有扩展覆盖
            is_without_rowid=False,  # 默认, SQLite 特有扩展覆盖
            on_conflict=None,  # 默认, SQLite 特有扩展覆盖
        )

    def _extract_dialect_specific(self, tables: list[str]) -> DialectSpecificFeatures | None:
        """方言特有提取."""
        if self.dialect == "sqlite":
            return self._extract_sqlite_specific(tables)
        if self.dialect == "postgresql":
            return self._extract_postgresql_specific(tables)
        return None

    def _extract_sqlite_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """SQLite 特有: STRICT, WITHOUT ROWID, ON CONFLICT, 类型亲和性."""
        features: dict[str, Any] = {}
        # 解析 sqlite_master.sql 获取 STRICT/WITHOUT ROWID/ON CONFLICT
        for table in tables:
            ddl = self._get_create_table_sql(table)
            if ddl:
                features.setdefault("table_flags", {})[table] = {
                    "is_strict": "STRICT" in ddl,
                    "is_without_rowid": "WITHOUT ROWID" in ddl,
                    "on_conflict": self._parse_on_conflict(ddl),
                }
        # 类型亲和性计算
        features["type_affinity"] = self._compute_type_affinity(tables)
        return DialectSpecificFeatures(dialect="sqlite", features=features)

    def _extract_postgresql_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """PostgreSQL 特有: SEQUENCE, EXCLUSION, PARTITION, INHERITANCE."""
        features: dict[str, Any] = {}
        # 查询 pg_sequences
        features["sequences"] = self._query_pg_sequences(tables)
        # 查询 EXCLUSION 约束
        features["exclusion_constraints"] = self._query_exclusion_constraints(tables)
        # 分区表检测
        features["partitioned_tables"] = self._query_partitioned_tables(tables)
        # 表继承
        features["inheritance"] = self._query_inheritance(tables)
        return DialectSpecificFeatures(dialect="postgresql", features=features)
```

### 4.3 多数据库特征映射表

| 特征 | SQLite 来源 | PostgreSQL 来源 | SQLAlchemy API | 归一化字段 |
|------|------------|----------------|----------------|-----------|
| 表列表 | sqlite_master | pg_class/pg_tables | get_table_names() | `tables: list[str]` |
| 列信息 | PRAGMA table_info | information_schema.columns | get_columns() | `ColumnFeatures` |
| 主键 | PRAGMA table_info.pk | pg_constraint | get_pk_constraint() | `primary_key: list[str]` |
| 外键 | PRAGMA foreign_key_list | pg_constraint | get_foreign_keys() | `ForeignKeyFeatures` |
| UNIQUE 约束 | sqlite_master 解析 | pg_constraint | get_unique_constraints() | `UniqueConstraintFeatures` |
| UNIQUE 索引 | PRAGMA index_list.unique | pg_indexes | get_indexes() | `IndexFeatures.unique` |
| CHECK 约束 | sqlite_master 解析 | pg_constraint | get_check_constraints() | `CheckConstraintFeatures` |
| 生成列 | PRAGMA table_xinfo.hidden | information_schema | get_columns() computed | `is_computed` |
| AUTOINCREMENT | sqlite_master 解析 | SERIAL/IDENTITY | autoincrement flag | `is_autoincrement` |
| DEFAULT 值 | PRAGMA table_info.dflt_value | information_schema | get_columns() default | `default` |
| 视图 | sqlite_master type='view' | pg_views | get_view_names() | `views: list[str]` |
| FK ON DELETE/UPDATE | PRAGMA foreign_key_list | pg_constraint | get_foreign_keys() options | `on_delete/on_update` |
| 部分索引谓词 | PRAGMA index_list.partial | pg_indexes WHERE | 需方言扩展查询 | `partial_predicate` |
| 复合 UNIQUE | sqlite_master 解析 | pg_constraint | get_unique_constraints() | `columns: list[str]` |
| 复合 FK | PRAGMA foreign_key_list | pg_constraint | get_foreign_keys() | `columns: list[str]` |
| COLLATE | COLLATE per column | COLLATION per column | 需方言扩展查询 | `collation` |

### 4.4 方言特有特征处理策略

| 特征 | SQLite | PostgreSQL | 处理策略 |
|------|--------|------------|---------|
| STRICT 表 | ✓ CREATE TABLE ... STRICT | ✗ (PG 总是严格) | 仅 SQLite 检测 |
| WITHOUT ROWID | ✓ | ✗ | 仅 SQLite 检测 |
| ON CONFLICT 子句 | ✓ | ✗ (PG 语法不同) | 仅 SQLite 检测 |
| 类型亲和性 | ✓ | ✗ | 仅 SQLite 计算 |
| EXCLUSION 约束 | ✗ | ✓ | 仅 PG 检测 |
| SEQUENCE 对象 | ✗ | ✓ SERIAL/IDENTITY | 仅 PG 检测 |
| 分区表 | ✗ | ✓ PARTITION BY | 仅 PG 检测 |
| 表继承 | ✗ | ✓ INHERITS | 仅 PG 检测 |

---

## 5. 阶段相关性矩阵

### 5.1 核心原则

**数据库结构在创建时固定** → 前置条件可确定性判断每阶段需要什么。这是纯规则判断，无 LLM 参与，基于 schema 实际内容决定。

### 5.2 完整相关性矩阵

| 结构特征 | 阶段 1 (结构) | 阶段 2 (列) | 阶段 3 (校验) | 判断依据 |
|---------|:---:|:---:|:---:|---------|
| 表名/列名 | ✓ 保留 | ✓ 保留 | — | S1: 拓扑+命名约定; S2: 语义推断 |
| 列类型 | ✓ 保留 | ✓ 保留 | — | S1: 复杂度评分; S2: 生成器路由 |
| NOT NULL | ✗ 省略 | ✓ 保留 | ✓ 保留 | S1: 非结构信息; S2: null_ratio; S3: 校验 |
| DEFAULT 值 | ✗ 省略 | ✓ 保留 | ✗ 省略 | S1: 非结构; S2: L4 默认策略关键; S3: 已应用无需再校验 |
| PK (单列) | ✓ 保留 | ✓ 保留 | — | S1: FK 目标识别; S2: L1 跳过 |
| AUTOINCREMENT | ✗ 省略 | ✓ 保留 | — | S1: 非结构; S2: 跳过生成 |
| GENERATED 标志 | ✗ 省略 | ✓ 保留 | — | S1: 非结构; S2: 跳过生成 |
| GENERATED 表达式 | ✗ 省略 | ✗ 省略 | ✗ 省略 | YAGNI: 生成器不计算表达式 |
| FK (单列) | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: fk_graph; S2: fk_reference 生成器; S3: FK 完整性校验 |
| FK ON DELETE/UPDATE | ✗ 省略 | ✗ 省略 | ✗ 省略 | 不影响数据生成（仅影响删除/更新行为） |
| 复合 FK | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: 结构; S2: 元组绑定; S3: 校验元组 |
| CHECK 表达式 | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: 模式检测(derive_from); S2: 参数约束; S3: 校验满足 |
| 跨列 CHECK | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: derive_from 模式; S2: derive_from 决策; S3: 校验跨列 |
| UNIQUE (单列) | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: 复杂度; S2: 唯一标志; S3: 唯一性校验 |
| 复合 UNIQUE | ✓ 保留 | ✓ 保留 | ✓ 保留 | S1: 复杂度; S2: 复合唯一; S3: 复合唯一性校验 |
| 非 UNIQUE 索引 | ✗ 省略 | ✗ 省略 | ✗ 省略 | 纯性能优化，无约束影响 |
| 部分 UNIQUE 谓词 | ✗ 省略 | ✓ 保留 | ✓ 保留 | S1: 非结构; S2: 作用域唯一性; S3: 校验作用域 |
| 索引排序顺序 | ✗ 省略 | ✗ 省略 | ✗ 省略 | 数据生成无关 |
| COLLATE (per-column) | ✗ 省略 | ✓ 保留 | ✓ 保留 | S1: 非结构; S2: NOCASE 影响唯一性语义; S3: 大小写不敏感校验 |
| 触发器 | ✗ 省略 | ✗ 省略 | ✗ 省略 | 不生成触发器数据; 本次不处理 |
| 视图 | ✗ 省略 | ✗ 省略 | ✗ 省略 | 不生成视图数据 |
| WITHOUT ROWID | ✗ 省略 | ✗ 省略 | ✗ 省略 | 边界情况（罕见） |
| STRICT 标志 | ✗ 省略 | ✓ 保留 | ✓ 保留 | S1: 非结构; S2: 严格类型匹配; S3: 校验类型严格性 |
| ON CONFLICT 子句 | ✗ 省略 | ✗ 省略 | ✓ 保留 | S1: 非结构; S2: 不影响生成; S3: REPLACE/IGNORE 行为感知 |
| 类型亲和性 | ✗ 省略 | ✗ 省略 | ✗ 省略 | 原始类型足够，生成器处理类型 |
| 表 DDL 原文 | ✓ 保留(解析) | ✗ 省略 | ✗ 省略 | S1 解析 DDL 提取上述; S2/S3 用结构化数据 |

### 5.3 阶段相关性判断器

位置：`plugins/sqlseed-ai/stage_relevance.py`（新增，AI 插件 Layer 2）

```python
from __future__ import annotations
from dataclasses import dataclass
from sqlseed.core.features import StructuralFeatures

@dataclass
class StageRelevance:
    """各阶段特征相关性, 分析前确定性判断."""
    stage1: dict[str, bool]  # 结构分析需要
    stage2: dict[str, bool]  # 列分析需要
    stage3: dict[str, bool]  # 校验需要

def determine_stage_relevance(features: StructuralFeatures) -> StageRelevance:
    """
    前置条件判断: 确定每阶段需要哪些特征.
    纯确定性规则, 无 LLM, 方言无关 (基于归一化 StructuralFeatures).
    """
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

---

## 6. 分阶段分析管线设计

### 6.1 管线总览

```
┌─────────────────────────────────────────────────────────────────┐
│  预检查 (无 LLM, 纯规则)                                          │
│  1. 确定分析范围: 全表 / 部分表 + FK 父表传递闭包                  │
│  2. 结构特征提取 (Layer 1) → StructuralFeatures                   │
│  3. 阶段相关性判断 (Layer 2) → StageRelevance                     │
│  4. 缓存检查: schema_hash 是否命中缓存                            │
│     命中 → 跳过阶段 1                                            │
│     未命中 → 执行阶段 1                                           │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 0 (可选): 数据采样                                          │
│  触发条件: 部分满载 + 父表已有数据                                 │
│  操作: 采样父表 3 行真实数据 → 注入阶段 1 作为 few-shot            │
│  无 LLM 调用 (纯 SQL 查询)                                        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 1: 结构分析 (0 或 1 次 LLM 调用)                            │
│  触发: 缓存未命中                                                 │
│  输入:                                                            │
│    - StructuralFeatures (仅 stage1=True 的特征)                   │
│    - 阶段 0 采样数据 (如有)                                       │
│  temperature=0, 严格 JSON schema 校验                            │
│  失败处理: 重试 3 次 (换 prompt), 仍失败降级为 DDL-only 摘要       │
│  输出 (内存):                                                     │
│    - tables: [{name, purpose, anchor_columns}]                    │
│    - fk_graph: [{parent, child, col, on_delete}]                  │
│    - topological_order: [table_names]                             │
│    - naming_conventions: {prefix_map: {table → prefix}}           │
│    - complexity_score: {tables, avg_columns, avg_constraints}      │
│  缓存: 可选写入 $SQLSEED_CACHE_DIR/analysis/{db}_{hash}/          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  决策点: 动态选择阶段 2 粒度 (无 LLM)                              │
│  基于: model_params + complexity_score                            │
│  输出: granularity ∈ {per_column, per_table, per_db}              │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 2: 列分析 (按需, 仅目标表, N 次 LLM 调用)                   │
│  粒度: per_column (2B) / per_table (7B+) / per_db (云端)          │
│                                                                   │
│  per_column 模式 (2B 本地, 推荐):                                  │
│    输入: 1 列的 constraints (仅 stage2=True 的特征) + 结构摘要      │
│    输出: {column, generator, params, derive_from, expression}    │
│    跳过: PK/AUTOINCREMENT/DEFAULT/GENERATED (已有 auto-fix 处理)  │
│    失败分类:                                                       │
│      transient (超时/网络) → 重试                                 │
│      logic (JSON 无效/列数不匹配) → 换 prompt 重试 3 次             │
│      quality (空输出/语义错误) → 降级为最小 config                 │
│                                                                   │
│  per_table 模式 (7B+ 本地):                                       │
│    输入: 1 表所有列 + 结构摘要                                     │
│    输出: 全表列 configs                                            │
│                                                                   │
│  per_db 模式 (云端 70B+):                                         │
│    输入: 全库 + 结构摘要                                           │
│    输出: 全库列 configs                                            │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  阶段 3: 校验 + Auto-fix (无 LLM, 纯规则)                         │
│  读: 阶段 2 输出 (内存) + StructuralFeatures (仅 stage3=True)     │
│  应用: auto-fix 规则 #1-#19                                       │
│    - #11: email/phone 语义强制                                    │
│    - #12: phone+regex → pattern                                   │
│    - #13: phone 列 → phone 生成器                                 │
│    - #14: 无界正则加上界 ({N,} → {N,N+5})                         │
│    - #15: name 列 → name/company 生成器                           │
│    - #16: template 前缀从表名派生                                  │
│    - #17: GENERATOR_PARAMS 校验 (新)                              │
│    - #18: 复合 CHECK 模式检测 (新)                                │
│    - #19: FK 级联检查 (新)                                        │
│  输出: config.yaml (唯一磁盘文件)                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 动态粒度决策

```python
def decide_granularity(model_params: int, complexity: dict) -> str:
    """
    动态决策: 基于模型参数量 + 数据库复杂度决定阶段 2 粒度.

    Args:
        model_params: LLM 参数量 (如 2_000_000_000 for 2B)
        complexity: {tables: int, avg_columns: int, avg_constraints: int}
    """
    complexity_score = (
        complexity["tables"]
        * complexity["avg_columns"]
        * (1 + complexity["avg_constraints"])
    )

    if model_params >= 70_000_000_000:  # 70B+ 或云端
        return "per_db"  # 1 次调用
    if model_params >= 7_000_000_000:  # 7B+
        return "per_table"  # N 次调用
    # <7B (包含 2B)
    if complexity_score <= 20:  # 简单 DB
        return "per_table"  # N 次调用, 2B 可承受
    # 中等/复杂 DB
    return "per_column"  # N×C 次调用, 最大化成功率
```

**决策矩阵**:

| 模型 | DB 复杂度 | 粒度 | 估计调用数 (8 表 × 6 列) |
|------|-----------|------|--------------------------|
| 2B Gemma | Simple (score ≤20) | per_table | 1 + 8 = 9 |
| 2B Gemma | Medium/Complex | per_column | 1 + 48 = 49 |
| 7B+ local | Any | per_table | 1 + 8 = 9 |
| Cloud (70B+) | Any | per_db | 1 |

### 6.3 满载 vs 部分满载处理

| 场景 | 阶段 0 | 阶段 1 输入 | 阶段 2 范围 | FK 采样 |
|------|--------|-------------|-------------|---------|
| 全表满载（空 DB） | 跳过 | 仅 DDL | 所有表所有列 | 无（无存量数据） |
| 部分满载（父表有数据） | 采样父表 3 行 | DDL + 采样数据 | 仅目标表列 | 读父表现有 PK |
| 部分满载（父表为空） | 跳过 | DDL | 目标表 + 父表（级联） | 无（需先填父表） |

**部分满载 FK 级联处理**:

```
fill -t items (categories 为空):
  1. 检测 items.category_id → categories.id, categories 为空
  2. 扩展分析范围: [items, categories]
  3. 阶段 2: 先分析 categories 列, 再分析 items 列
  4. 阶段 3: config.yaml 包含 categories + items 两个表配置
  5. fill 时按拓扑序: 先填 categories, 再填 items
```

### 6.4 临时文件最小化

```
默认模式 (无 --cache-analysis):
  阶段 1 → 内存中 structure 对象 (不写磁盘)
  阶段 2 → 内存中 columns 列表 (不写磁盘)
  阶段 3 → 唯一磁盘文件: config.yaml (最终文件)

  临时文件: 0 个
  最终文件: 1 个 (config.yaml)

可选模式 (--cache-analysis):
  阶段 1 → 写入 $SQLSEED_CACHE_DIR/analysis/{db}_{hash}/structure.yaml
  阶段 2 → 写入 $SQLSEED_CACHE_DIR/analysis/{db}_{hash}/columns.jsonl
  阶段 3 → 写入 config.yaml

  临时文件: 2 个 (隐藏在 cache 目录, 用户可安全删除)
  最终文件: 1 个 (config.yaml)
  用途: 二次运行时跳过 LLM 调用, 支持中断后恢复

flag 语义:
  --cache-analysis: 启用缓存写入 + 读取 (默认关闭)
  无 flag: 纯内存模式, 0 临时文件
```

**默认不产生临时文件**, 仅用户显式要求缓存/恢复时才写。

### 6.5 缓存策略

```
缓存触发条件:
  1. 首次分析该 DB (缓存未命中)
  2. Schema DDL hash 变化 (用户 ALTER TABLE 了)
  3. 用户显式 --reanalyze 强制重分析

缓存命中: 跳过阶段 1, 直接读缓存的 structure 对象

缓存目录结构:
  $SQLSEED_CACHE_DIR/
  └── analysis/
      └── complex_biz_a1b2c3d4/          # {db_name}_{schema_hash}
          ├── structure.yaml              # 阶段 1 输出 (可选)
          └── columns/
              ├── items_id.jsonl          # 阶段 2 输出 (可选)
              └── ...

性能优化效果:
  首次全表满载 (2B): 1 + 48 = 49 调用 (无优化)
  二次全表满载 (2B, schema 未变): 0 + 0 = 0 调用 (100% 缓存命中)
  部分满载 items (2B, categories 已有数据): 1 + 6 = 7 调用 (86% 减少)
```

---

## 7. 风险缓解措施

### 7.1 已识别的 8 个风险及缓解

| # | 风险 | 来源 | 严重度 | 缓解措施 (已融入设计) |
|---|------|------|--------|---------------------|
| R1 | 错误传播 (compounding error) — 阶段 1 摘要错误污染所有下游 | LtM 失败模式文献 | 致命 | 阶段 1 严格 JSON schema 校验 + 失败换 prompt 重试 + temperature=0 |
| R2 | 过度分解 — 拆太细增加延迟和错误累积 | theneuralbase.com | 中 | 保持 3 阶段 (1+2+3), 不拆 10+ |
| R3 | 上下文窗口增长 — 50+ 步链时 prior response 撑爆上下文 | theneuralbase.com | 低 | 最多 5 阶段, 传摘要不传全文 |
| R4 | 弱验证 — 二元 pass/fail 抓不住部分正确 | theneuralbase.com | 高 | 每阶段 schema 校验 + 语义校验 (列数匹配、generator 合法性) |
| R5 | 错误类型不分类 — 重试幻觉只会产生 3 个自信的错误答案 | clarion.ai | 高 | 分类: transient (重试) / logic (换策略) / quality (降级) |
| R6 | 无状态恢复 — 阶段 N 失败需从阶段 1 重启 | LangGraph, TME 论文 | 高 | YAML 即 checkpoint (可选模式), 每列写入即持久化, 支持从最后成功列恢复 |
| R7 | 温度设置 — 随机输出导致下游难调试故障 | theneuralbase.com | 中 | 所有 LLM 调用 temperature=0 |
| R8 | 故障隔离不足 — 单阶段失败级联到整管线 | clarion.ai, LangGraph | 高 | 每阶段独立 error handler + 失败阶段降级为最小 config |

### 7.2 已识别的 5 个遗漏及补充

| # | 遗漏 | 补充方案 (已融入设计) |
|---|------|---------------------|
| G1 | 并行执行 — 阶段 2 per_column 调用相互独立 | 阶段 1 后并行执行阶段 2 (2B 仍串行避免显存竞争) |
| G2 | 缓存 — 同库重跑应复用阶段 1 摘要 | 按 schema DDL hash 缓存阶段 1 输出到 SQLSEED_CACHE_DIR (可选) |
| G3 | 每阶段 few-shot 示例 | 阶段 1: schema 摘要示例; 阶段 2: 列分析示例; 每阶段不同 |
| G4 | 部分满载未处理 | 阶段 0 (可选): 采样每表 3 行真实数据, 作为 few-shot 注入阶段 1 |
| G5 | 2B 模型特定关注 | 阶段 1 输出必须 SHORT + STRUCTURED (严格 JSON, 非自由文本) |

---

## 8. 最佳实践覆盖评估

### 8.1 调研发现的 8 项最佳实践

| # | 最佳实践 | 来源 | 我们的方案是否覆盖 | 评估 |
|---|---------|------|------------------|------|
| 1 | Few-shot 示例 | VLDB 2025 QDB | ✓ 已规划 (G3) | 覆盖 |
| 2 | Schema Linking/Pruning | 矩阵起源 NL2SQL | ✓ 阶段 1 按需分析 (部分满载只分析相关表 + FK 父表) | 覆盖 |
| 3 | 两步式推理 | 矩阵起源 NL2SQL | ✓ 阶段 1 (结构) → 阶段 2 (列) | 覆盖 |
| 4 | Multi-candidate generation | Feather-SQL | ✗ 未覆盖 | 留作未来增强 (YAGNI) |
| 5 | DB Graph | DB-Explore | ✓ structure 对象的 fk_graph 即此 | 覆盖 |
| 6 | Progressive synthesis | DB-Explore | ✓ 阶段 1 → 阶段 2 由简到繁 | 覆盖 |
| 7 | 统计预分析 | Baidu Data Platform | ✓ 阶段 0 数据采样 (部分满载) | 覆盖 |
| 8 | 语法约束解码 | LM Studio GBNF | △ 可选 best-effort (2B 可能不支持) | 可选 |

**覆盖 7/8 项最佳实践**。Multi-candidate generation 留作未来增强。

### 8.2 替代方案评估（确认 LtM 仍最佳）

| 方案 | 适合 2B? | 评估 |
|------|-----------|------|
| **Least-to-Most** | ✓ | 推荐——直击推理负载瓶颈, 纯 prompting 不依赖模型能力 |
| ReAct (推理+行动) | ✗ | 需 tool-calling 能力, 2B 模型不可靠 |
| Self-Consistency | ✗ | N× 成本 (3× × 5 阶段 × 8 表 = 120 次调用), 2B 太慢 |
| Tree of Thoughts | ✗ | 探索多分支, 复杂度过高 |
| Plan-and-Execute | ≈ | 与 LtM 等价, LtM 更成熟 |

---

## 9. 性能预估

### 9.1 调用次数与时间

**测试数据库**: complex_biz.db (8 表 × 6 列 = 48 列)

| 模式 | 调用次数 | 2B @ 14s/次 | 云端 @ 2s/次 |
|------|---------|-------------|--------------|
| per_column (2B, 首次) | 1 + 48 = 49 | ~11 分钟 | — |
| per_column (2B, 缓存命中) | 0 + 0 = 0 | 0 秒 | — |
| per_table (7B+) | 1 + 8 = 9 | — | ~18 秒 |
| per_db (cloud) | 1 | — | ~2 秒 |

### 9.2 用户接受度

用户明确接受"时间复杂度换空间复杂度"。2B 模式 11 分钟可接受, 且:
- 每列分析独立, 可中断恢复 (可选模式)
- 缓存命中后 0 调用
- 部分满载仅分析目标表, 大幅减少调用

---

## 10. 架构合规性

### 10.1 层级分布

层级编号与 §3.1 三层架构一致:

| 层 | 位置 | 是否核心? | 理由 |
|----|------|-----------|------|
| Layer 1: 特征提取 + 归一化模型 | `src/sqlseed/core/features.py` | ✓ 核心 | 通用 schema 内省 + 纯数据结构, 无业务逻辑 |
| Layer 2: 阶段相关性判断 | `plugins/sqlseed-ai/stage_relevance.py` | ✗ AI 插件 | LLM 分析优化专用, 纯规则无 LLM |
| Layer 3: 分阶段 LLM 管线 | `plugins/sqlseed-ai/staged_analyzer.py` | ✗ AI 插件 | LLM 分析优化专用, 含阶段 0-3 |

### 10.2 核心原则验证

- **核心无业务逻辑**: Layer 1 是通用 schema 内省 + 纯数据结构, 不含领域特定启发式
- **AI 优化在插件层**: Layer 2-3 仅为 LLM 分析优化, 核心不依赖
- **不修改 DatabaseAdapter protocol**: 通过新增 `StructuralFeatureExtractor` 类扩展
- **不添加新数据库支持**: SQLite + PostgreSQL 已支持, MySQL 仍延期
- **不添加新功能**: 不添加触发器/视图数据生成, 仅优化现有 `ai-analyze` 稳定性

### 10.3 "只解决问题，不新增功能"验证

| 检查项 | 状态 |
|-------|------|
| 解决 items 表空输出问题 | ✓ 列级分解降低推理负载 |
| 解决 projects 表 word+min_length 不兼容 | ✓ 阶段 3 auto-fix #17 GENERATOR_PARAMS 校验 |
| 解决 sales FK 级联违规 | ✓ 部分满载 FK 父表闭包 + 级联检测 |
| 解决 full_name 用 word 生成器 | ✓ 阶段 3 auto-fix #15 语义名强制 |
| 解决 phone 无界正则 | ✓ 阶段 3 auto-fix #14 无界正则加上界 |
| 解决 template 前缀复用 | ✓ 阶段 3 auto-fix #16 前缀从表名派生 |
| 不添加 MySQL 支持 | ✓ MySQL 仍延期 |
| 不添加触发器/视图生成 | ✓ 本次不处理 |
| 不添加 Multi-candidate generation | ✓ 留作未来增强 (YAGNI) |

---

## 11. 文件结构变更

### 11.1 新增文件

```
src/sqlseed/core/features.py                    # Layer 1: 特征提取 + 归一化模型
plugins/sqlseed-ai/src/sqlseed_ai/
  stage_relevance.py                             # Layer 2: 阶段相关性判断
  staged_analyzer.py                            # Layer 3: 分阶段 LLM 管线
  _stage_prompts.py                             # 各阶段 prompt 模板 + few-shot 示例
```

### 11.2 修改文件

```
plugins/sqlseed-ai/src/sqlseed_ai/
  analyzer/                                      # 现有 SchemaAnalyzer 保留, 新增分阶段入口
    __init__.py                                  # 导出 StagedSchemaAnalyzer
  ai_mediator.py                                # auto-fix 规则 #17-#19 新增
  cli/ai_commands.py                             # ai-analyze 命令接入分阶段管线
```

### 11.3 不修改文件

```
src/sqlseed/database/_protocol.py                # DatabaseAdapter protocol 不变
src/sqlseed/database/sqlalchemy_adapter.py       # 现有适配器不变
src/sqlseed/database/raw_sqlite_adapter.py        # 测试适配器不变
src/sqlseed/core/schema.py                       # SchemaInferrer 保留兼容
src/sqlseed/core/mapper.py                        # ColumnMapper 不变
src/sqlseed/generators/                           # 生成器不变
```

---

## 12. 测试策略

### 12.1 单元测试

- `tests/test_core/test_features.py`: 特征提取 + 归一化模型
- `plugins/sqlseed-ai/tests/test_stage_relevance.py`: 阶段相关性判断
- `plugins/sqlseed-ai/tests/test_staged_analyzer.py`: 分阶段管线

### 12.2 集成测试

- `plugins/sqlseed-ai/tests/test_staged_e2e_sqlite.py`: SQLite 端到端
- `plugins/sqlseed-ai/tests/test_staged_e2e_postgres.py`: PostgreSQL 端到端 (需 testcontainers)
- 使用 `complex_biz.db` 和 `hr_biz.db` 作为测试 fixture

### 12.3 验收标准

| 测试项 | 验收标准 |
|-------|---------|
| 2B 模型 items 表 | 不再返回空 config, 生成有效 YAML |
| 2B 模型 projects 表 | 不再因 word+min_length 崩溃 |
| FK 级联 | sales.item_id 引用存在的 items.id |
| 跨表一致性 | 前缀不复用 (departments→DEPT-, merchants→MER-) |
| 业务字段语义 | full_name 用 name 生成器, phone 长度合理 |
| 多数据库 | SQLite + PostgreSQL 均通过 |
| 临时文件 | 默认模式仅 config.yaml |
| 缓存命中 | 二次运行 0 LLM 调用 |

---

## 13. 实施顺序建议

1. **Phase 1 (P0)**: Layer 1 特征提取 + 归一化模型 (`src/sqlseed/core/features.py`)
2. **Phase 2 (P0)**: Layer 2 阶段相关性判断 (`plugins/sqlseed-ai/stage_relevance.py`)
3. **Phase 3 (P0)**: Layer 3 分阶段管线 + 阶段 1 结构分析
4. **Phase 4 (P0)**: 阶段 2 列分析 (per_column 模式)
5. **Phase 5 (P0)**: 阶段 3 auto-fix 规则 #17-#19
6. **Phase 6 (P1)**: 动态粒度决策 + per_table/per_db 模式
7. **Phase 7 (P1)**: 缓存策略 + 可选 --cache-analysis 模式
8. **Phase 8 (P2)**: 集成测试 + E2E 验证

---

## 14. 未来增强（不在本次范围）

- Multi-candidate generation (Feather-SQL 风格)
- 触发器感知 (INSERT 副作用检测)
- 视图数据生成
- MySQL 支持 (已延期)
- GBNF 语法约束 (best-effort, 当模型支持时)

---

## 15. 参考资料

1. **Least-to-Most Prompting**: Zhou et al. 2022, Google Brain. "Least-to-Most Prompting Enables In-Context Learning for Complex Reasoning." SCAN 基准: GPT-3 从 16% → 99%.
2. **Feather-SQL**: Pei et al. 2025, IJCNLP. "Lightweight NL2SQL Framework with Dual-Model Collaboration for Small Language Models." Schema pruning + multi-candidate.
3. **DB-Explore**: Ma et al. 2025, arxiv. "Automated Database Exploration and Instruction Synthesis for Text-to-SQL." DB Graph + progressive synthesis.
4. **SLM-based Schema Auditing**: Seabra et al. 2025, VLDB QDB Workshop. Few-shot examples for SLM schema analysis.
5. **Baidu Data Platform**: 2025. "数据平台数据智能化入库." 统计预分析 + LLM 混合方法.
6. **LM Studio 结构化输出**: https://lm-studio.cn/docs/api/structured-output. GBNF grammar, <7B 警告.
7. **sqlseed 项目**: AGENTS.md, CLAUDE.md, ARCHITECTURE.md. 现有架构参考.

---

**文档版本**: 1.0
**创建日期**: 2026-07-02
**作者**: AI 辅助设计 (brainstorming skill)
**审核状态**: 待用户审核
