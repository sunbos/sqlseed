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

**重要**: 此模型基于现有 `DatabaseAdapter` Protocol (`src/sqlseed/database/_protocol.py`) 的实际 API 构建。Protocol 现有方法:
- `get_column_info(table)` → `list[ColumnInfo]` (含 name, type, nullable, default, is_primary_key, is_autoincrement, is_computed)
- `get_primary_keys(table)` → `list[str]`
- `get_foreign_keys(table)` → `list[ForeignKeyInfo]` (单列: column, ref_table, ref_column)
- `get_index_info(table)` → `list[IndexInfo]` (含 name, table, columns 元组, unique)
- `get_check_constraints(table)` → `list[CheckConstraintInfo]` (含 name, table, columns 元组, expression)
- `get_sample_rows(table, limit, columns)` → `list[dict]`

**Protocol 不提供但 spec 需要的能力** (通过方言扩展实现):
- 复合 FK: 现有 `ForeignKeyInfo` 是单列, 需在 `_extract_dialect_specific` 中按 FK name/id 聚合
- UNIQUE 约束: 现有 `IndexInfo.unique` 可派生, 但表级 UNIQUE 约束需 DDL 解析
- `partial_predicate`: 需方言扩展查询 (PRAGMA index_list.partial / pg_indexes WHERE)
- `collation`: 需方言扩展查询 (COLLATE 解析)
- `views`: Protocol 无 `get_view_names()`, 需方言扩展或省略

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ColumnFeatures:
    """归一化列特征, 方言无关.
    基于现有 ColumnInfo 扩展, collation 为可选扩展字段."""
    name: str
    type: str  # 归一化类型: "TEXT", "INTEGER", "REAL", "DATE", "BOOLEAN", "BLOB"
    nullable: bool
    default: Any  # 来自 ColumnInfo.default
    is_primary_key: bool
    is_autoincrement: bool
    is_computed: bool
    # 可选扩展 (方言扩展查询填充, 默认 None)
    collation: str | None = None  # SQLite: NOCASE/BINARY/RTRIM; PostgreSQL: COLLATION 名

@dataclass
class ForeignKeyFeatures:
    """归一化外键特征, 支持复合 FK.
    现有 ForeignKeyInfo 是单列, 此处聚合多列为复合 FK."""
    table: str
    columns: list[str]  # 复合 FK 支持多列 (单列 FK 时长度为 1)
    ref_table: str
    ref_columns: list[str]
    on_delete: str | None = None  # 需方言扩展, Protocol 不提供
    on_update: str | None = None  # 需方言扩展

@dataclass
class UniqueConstraintFeatures:
    """归一化 UNIQUE 约束, 支持复合.
    从 IndexInfo(unique=True) 派生 + DDL 解析表级 UNIQUE."""
    table: str
    columns: list[str]  # 复合 UNIQUE 支持多列
    is_index_based: bool  # True: 从 IndexInfo 派生; False: DDL 解析表级 UNIQUE
    partial_predicate: str | None = None  # 需方言扩展

@dataclass
class CheckConstraintFeatures:
    """归一化 CHECK 约束. 直接映射 CheckConstraintInfo."""
    table: str
    name: str
    expression: str  # 原始 SQL 表达式
    columns: list[str]  # 提取的列引用 (从 CheckConstraintInfo.columns 转换)

@dataclass
class IndexFeatures:
    """归一化索引. 基于 IndexInfo 扩展."""
    table: str
    name: str
    columns: list[str]  # 从 IndexInfo.columns 元组转换
    unique: bool
    partial_predicate: str | None = None  # 需方言扩展

@dataclass
class TableFeatures:
    """归一化表特征."""
    name: str
    columns: list[ColumnFeatures]
    primary_key: list[str]  # 复合 PK 支持多列 (来自 get_primary_keys)
    foreign_keys: list[ForeignKeyFeatures]  # 聚合后的复合 FK
    unique_constraints: list[UniqueConstraintFeatures]  # 派生 + 解析
    check_constraints: list[CheckConstraintFeatures]
    indexes: list[IndexFeatures]
    # SQLite 特有 (PG 中始终为默认值, 需方言扩展)
    is_strict: bool = False
    is_without_rowid: bool = False
    on_conflict: str | None = None

@dataclass
class DialectSpecificFeatures:
    """方言特有特征, 不在通用模型中."""
    dialect: str  # "sqlite" | "postgresql"
    features: dict[str, Any]

@dataclass
class StructuralFeatures:
    """完整的归一化 schema 特征, 方言无关."""
    dialect: str
    tables: list[TableFeatures]
    schema_hash: str  # 用于缓存判断
    dialect_specific: DialectSpecificFeatures | None = None
    # views 省略: Protocol 不提供 get_view_names(), 本次不生成视图数据
```

### 4.2 特征提取器

位置：`src/sqlseed/core/features.py`（新增，核心层）

**重要**: 使用实际 `DatabaseAdapter` Protocol API, 不调用不存在的方法。

```python
class StructuralFeatureExtractor:
    """从任何支持的数据库提取结构特征.
    使用 DatabaseAdapter Protocol 现有 API + 方言扩展."""

    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter
        # dialect 通过 hasattr 检测 (Protocol 不声明属性)
        self.dialect = getattr(adapter, "dialect", "sqlite")

    def extract(self, table_names: list[str] | None = None) -> StructuralFeatures:
        """
        提取结构特征.

        Args:
            table_names: None 提取所有表; 提供则只提取指定表 + FK 父表闭包 (按需分析)
        """
        # 1. 确定分析范围 (按需: 目标表 + FK 父表传递闭包)
        tables_to_analyze = self._resolve_scope(table_names)

        # 2. 公共提取 (通过现有 Protocol API)
        tables = [self._extract_table_common(name) for name in tables_to_analyze]

        # 3. 方言特有扩展 (填充 Protocol 不提供的字段)
        dialect_specific = self._extract_dialect_specific(tables_to_analyze)
        if dialect_specific:
            self._merge_dialect_specific(tables, dialect_specific)

        # 4. 计算 schema hash (用于缓存)
        schema_hash = self._compute_schema_hash(tables)

        return StructuralFeatures(
            dialect=self.dialect,
            tables=tables,
            schema_hash=schema_hash,
            dialect_specific=dialect_specific,
        )

    def _resolve_scope(self, table_names: list[str] | None) -> list[str]:
        """按需分析: 全表或目标表 + FK 父表传递闭包."""
        if table_names is None:
            return self.adapter.get_table_names()
        scope = set(table_names)
        changed = True
        while changed:
            changed = False
            for table in list(scope):
                # 使用现有 Protocol API get_foreign_keys
                fks = self.adapter.get_foreign_keys(table)
                for fk in fks:
                    if fk.ref_table not in scope:
                        scope.add(fk.ref_table)
                        changed = True
        return sorted(scope)

    def _extract_table_common(self, table_name: str) -> TableFeatures:
        """公共提取: 使用现有 Protocol API."""
        # 使用 get_column_info (不是 get_columns)
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
                # collation 由方言扩展填充, 默认 None
            )
            for ci in column_infos
        ]

        # 使用 get_primary_keys (不是 get_pk_constraint)
        pk = self.adapter.get_primary_keys(table_name)

        # 使用 get_foreign_keys + 聚合为复合 FK
        raw_fks = self.adapter.get_foreign_keys(table_name)
        fks = self._aggregate_foreign_keys(raw_fks, table_name)

        # 从 get_index_info 派生 UNIQUE 约束 (Protocol 无 get_unique_constraints)
        index_infos = self.adapter.get_index_info(table_name)
        unique_constraints = [
            UniqueConstraintFeatures(
                table=table_name,
                columns=list(idx.columns),
                is_index_based=True,
                # partial_predicate 由方言扩展填充
            )
            for idx in index_infos if idx.unique
        ]
        indexes = [
            IndexFeatures(
                table=table_name,
                name=idx.name,
                columns=list(idx.columns),
                unique=idx.unique,
                # partial_predicate 由方言扩展填充
            )
            for idx in index_infos
        ]

        # 使用 get_check_constraints (直接映射)
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
            # is_strict/is_without_rowid/on_conflict 由方言扩展填充
        )

    def _aggregate_foreign_keys(
        self, raw_fks: list[ForeignKeyInfo], table: str
    ) -> list[ForeignKeyFeatures]:
        """聚合单列 ForeignKeyInfo 为复合 ForeignKeyFeatures.
        现有 ForeignKeyInfo 是单列, 按 ref_table 分组聚合."""
        # 按 ref_table 分组 (简化: 假设同 ref_table 的 FK 为同一复合 FK)
        # 注: 完整实现需按 FK name/id 分组, 此处为 spec 级别示意
        groups: dict[str, list[ForeignKeyInfo]] = {}
        for fk in raw_fks:
            groups.setdefault(fk.ref_table, []).append(fk)

        return [
            ForeignKeyFeatures(
                table=table,
                columns=[fk.column for fk in group],
                ref_table=ref_table,
                ref_columns=[fk.ref_column for fk in group],
                # on_delete/on_update 由方言扩展填充
            )
            for ref_table, group in groups.items()
        ]

    def _extract_dialect_specific(self, tables: list[str]) -> DialectSpecificFeatures | None:
        """方言特有提取: 填充 Protocol 不提供的字段."""
        if self.dialect == "sqlite":
            return self._extract_sqlite_specific(tables)
        if self.dialect == "postgresql":
            return self._extract_postgresql_specific(tables)
        return None

    def _extract_sqlite_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """SQLite 特有: STRICT, WITHOUT ROWID, ON CONFLICT, COLLATE, 部分索引谓词.
        通过 PRAGMA + sqlite_master.sql 解析."""
        # 实现细节在 plan 中定义
        ...

    def _extract_postgresql_specific(self, tables: list[str]) -> DialectSpecificFeatures:
        """PostgreSQL 特有: SEQUENCE, EXCLUSION, PARTITION, INHERITANCE, COLLATION.
        通过 pg_catalog 查询."""
        # 实现细节在 plan 中定义
        ...

    def _merge_dialect_specific(
        self, tables: list[TableFeatures], dialect_specific: DialectSpecificFeatures
    ) -> None:
        """将方言特有字段合并到 TableFeatures 中."""
        # 填充 is_strict, is_without_rowid, on_conflict, collation, partial_predicate 等
        # 实现细节在 plan 中定义
        ...
```

### 4.3 多数据库特征映射表

**重要**: 此表使用 `DatabaseAdapter` Protocol (位于 `src/sqlseed/database/_protocol.py`) 的实际 API,
不再引用 SQLAlchemy Inspector 的方法名. Protocol 不提供的能力标记为"需方言扩展".

| 特征 | SQLite 来源 | PostgreSQL 来源 | Protocol API | 归一化字段 |
|------|------------|----------------|-------------|-----------|
| 表列表 | sqlite_master | pg_class/pg_tables | `get_table_names()` | `tables: list[str]` |
| 列信息 | PRAGMA table_info | information_schema.columns | `get_column_info()` | `ColumnFeatures` |
| 主键 | PRAGMA table_info.pk | pg_constraint | `get_primary_keys()` | `primary_key: list[str]` |
| 外键 (单列) | PRAGMA foreign_key_list | pg_constraint | `get_foreign_keys()` | `ForeignKeyFeatures` (聚合后) |
| UNIQUE 索引 | PRAGMA index_list.unique | pg_indexes | `get_index_info()` filter unique | `UniqueConstraintFeatures` (派生) |
| 全部索引 | PRAGMA index_list | pg_indexes | `get_index_info()` | `IndexFeatures` |
| CHECK 约束 | sqlite_master 解析 | pg_constraint | `get_check_constraints()` | `CheckConstraintFeatures` |
| 生成列 | PRAGMA table_xinfo.hidden | information_schema | `get_column_info()` is_computed | `is_computed` |
| AUTOINCREMENT | sqlite_master 解析 | SERIAL/IDENTITY | `get_column_info()` is_autoincrement | `is_autoincrement` |
| DEFAULT 值 | PRAGMA table_info.dflt_value | information_schema | `get_column_info()` default | `default` |
| 视图 | sqlite_master type='view' | pg_views | **Protocol 不提供** | 省略 (本次不处理) |
| 采样行 | SELECT ... LIMIT | SELECT ... LIMIT | `get_sample_rows()` | few-shot 注入 (阶段 0) |
| FK ON DELETE/UPDATE | PRAGMA foreign_key_list | pg_constraint | **Protocol 不提供** | 需方言扩展 |
| 部分索引谓词 | PRAGMA index_list.partial | pg_indexes WHERE | **Protocol 不提供** | 需方言扩展 |
| 复合 UNIQUE | sqlite_master 解析 | pg_constraint | 从 `get_index_info()` 多列索引派生 | `columns: list[str]` |
| 复合 FK | PRAGMA foreign_key_list | pg_constraint | 从 `get_foreign_keys()` 聚合 (按 ref_table) | `columns: list[str]` |
| 表级 UNIQUE 约束 | sqlite_master 解析 | pg_constraint | **Protocol 不提供** | 需方言扩展 (DDL 解析) |
| COLLATE | COLLATE per column | COLLATION per column | **Protocol 不提供** | 需方言扩展 |

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
│          + 同表所有跨列 CHECK 约束 (避免上下文丢失)               │
│    输出: {column, generator, params, derive_from, expression}    │
│    跳过: PK/AUTOINCREMENT/DEFAULT/GENERATED (已有 auto-fix 处理)  │
│    跨列 CHECK 处理 (关键):                                        │
│      问题: 单列分析看不到其他列, 无法处理 start_date ≤ end_date   │
│      方案: 每列分析时注入同表所有跨列 CHECK 表达式 + 涉及列名+类型│
│      让 LLM 自行决定: 若本列被跨列 CHECK 引用, 输出 derive_from; │
│      否则输出独立 generator                                        │
│      例: 分析 end_date 列时, prompt 包含:                        │
│        "跨列约束: end_date >= start_date (start_date: DATE)"      │
│        LLM 输出: {derive_from: [start_date], expression: "value"}│
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
│  应用: 现有 auto-fix 规则 #1-#13 (已存在, 位于 schema_analyzer.py │
│        SchemaSemanticAnalyzer._auto_fix_config) + 新增规则 #14-#16 │
│                                                                   │
│  现有规则 (已存在, 不重复实现, 阶段 3 调用即可):                   │
│    #1: 互斥性 (generator+derive_from 共存 → derive_from 胜出)     │
│    #2: choice+weighted_choices → weighted_choice                  │
│    #3: 单列 derive_from 的 value[0] → value                       │
│    #4: 源列名当 value 关键字用 → 替换为 value                      │
│    #5: GENERATED 列移除                                            │
│    #6: UNIQUE 索引强制 constraints.unique=true                    │
│    #7: 孤儿 expression 清理                                        │
│    #8: 跨列 CHECK 转换为 derive_from (上下界两种模式)              │
│    #9: *_name 列生成器修正 (string/text → name/first_name/company)│
│    #10: integer 缺 max_value 自动补充                              │
│    #11: *_email/phone 列强制语义生成器                             │
│    #12: phone+regex 不兼容 → 转为 pattern                          │
│    #13: UNIQUE NOT NULL 列遗漏检测 + template 补充                 │
│                                                                   │
│  新增规则 (本次新增, 在 staged_analyzer.Stage3Validator 实现):     │
│    #14: GENERATOR_PARAMS 校验 — 校验 (generator, param_key) 对    │
│        是否在该生成器签名内, 不兼容则降级 (如 word+min_length      │
│        → 移除 min_length, 保留 word; string+max_length 合法保留)   │
│    #15: 无界正则加上界 — regex 中 {N,} (无上界) 替换为 {N,N+5}    │
│        避免 ReDoS 或生成超长字符串违反列长度约束                    │
│    #16: template 前缀从表名派生 — 若 template 前缀为通用占位符    │
│        (如 "PREFIX-"/"XXXX-") 或与已用前缀冲突, 则按表名派生        │
│        (merchants→MER-, products→PROD-, orders→ORD-)              │
│  注: FK 级联检查在阶段 1 fk_graph 中处理 (非 auto-fix 规则)        │
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

### 6.6 StagedSchemaAnalyzer 与现有 Analyzer 的关系

**现有 Analyzer 类** (不修改, 保留向后兼容):

| 类名 | 位置 | 职责 | 是否修改 |
|------|------|------|---------|
| `SchemaSemanticAnalyzer` | `schema_analyzer.py:55` | per-table 单阶段 LLM 分析 (现有 `ai-analyze` 入口) | 不修改, 保留兼容 |
| `SchemaAnalyzer` | `analyzer/__init__.py:37` | 底层 LLM 调用 + refiner 自纠错循环 | 不修改, 被 StagedSchemaAnalyzer 复用 |
| `AiConfigRefiner` | `refiner.py:62` | LLM 输出验证 + 重试循环 | 不修改, 阶段 2 per_column 调用复用 |

**新增 StagedSchemaAnalyzer** (`staged_analyzer.py`):

```python
class StagedSchemaAnalyzer:
    """分阶段 LLM 分析入口.

    替代 SchemaSemanticAnalyzer.analyze() 的新入口点, 但不删除现有类.
    通过 AIConfig.use_staged_pipeline flag 切换:
      - use_staged_pipeline=False (默认): 走现有 SchemaSemanticAnalyzer (向后兼容)
      - use_staged_pipeline=True: 走分阶段管线 (本次新增)

    复用关系:
      - 阶段 1/2 的 LLM 调用: 复用现有 SchemaAnalyzer._call_llm_once() (底层客户端)
      - 阶段 2 per_column 失败重试: 复用现有 AiConfigRefiner 的重试逻辑
      - 阶段 3 auto-fix: 调用现有 SchemaSemanticAnalyzer._auto_fix_config (规则 1-13)
                        + 新增 Stage3Validator (规则 14-16)

    迁移路径 (未来, 本次不做):
      1. 灰度阶段: flag 默认 False, 用户显式开启试用
      2. 验证阶段: 收集 2B 模型稳定性数据, 与现有方案对比
      3. 切换阶段: flag 默认 True, 现有 SchemaSemanticAnalyzer 标记 deprecated
      4. 移除阶段: 删除旧代码 (本次不做, 留作未来增强)
    """
```

**关系图**:
```
ai-analyze CLI command
       │
       ▼
AIConfig.use_staged_pipeline?
   ├── False ─→ SchemaSemanticAnalyzer.analyze() (现有, 不变)
   └── True  ─→ StagedSchemaAnalyzer.analyze() (新增)
                    │
                    ├─ 阶段 1 ─→ SchemaAnalyzer._call_llm_once() (复用)
                    ├─ 阶段 2 ─→ SchemaAnalyzer._call_llm_once() (复用)
                    │            + AiConfigRefiner (复用重试逻辑)
                    └─ 阶段 3 ─→ SchemaSemanticAnalyzer._auto_fix_config (规则 1-13, 复用)
                                 + Stage3Validator (规则 14-16, 新增)
```

### 6.7 阶段间数据传递格式 (StructureSummary)

**问题**: 阶段 1 输出的"结构摘要"包含什么没有定义, 阶段 2 无法稳定消费.

**方案**: 定义 `StructureSummary` dataclass 作为阶段 1 → 阶段 2/3 的内存传递格式.

位置: `plugins/sqlseed-ai/staged_analyzer.py` (新增, AI 插件)

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class TableStructureSummary:
    """单表结构摘要, 阶段 1 输出, 阶段 2 per_column 输入."""

    name: str
    purpose: str                    # LLM 推断的表用途 (如 "员工薪酬管理")
    anchor_columns: list[str]       # 锚定列 (PK + UNIQUE 列, 决定生成策略)
    naming_prefix: str              # 命名前缀 (如 "EMP-" for employees, 从表名派生)
    complexity: int                # 复杂度评分 (列数 × 约束数)
    cross_column_checks: list[dict] = field(default_factory=list)
    # 跨列 CHECK 表达式 + 涉及列名+类型, 用于 per_column 模式上下文注入
    # 例: [{"expression": "end_date >= start_date",
    #       "columns": {"start_date": "DATE", "end_date": "DATE"}}]
    fk_references: list[dict] = field(default_factory=list)
    # 同表 FK 引用信息 (本表作为父表被引用的列)
    # 例: [{"column": "id", "ref_count": 3}]

@dataclass
class StructureSummary:
    """阶段 1 完整输出, 内存中传递给阶段 2/3.

    这是 "YAML 状态机" 的阶段 1 状态, 默认不写磁盘 (--cache-analysis 时写).
    """

    schema_hash: str                # 用于缓存键
    topological_order: list[str]    # 表填充顺序 (拓扑排序)
    fk_graph: list[dict]            # FK 依赖图 [{parent, child, col, on_delete}]
    tables: list[TableStructureSummary]  # 各表结构摘要
    naming_conventions: dict[str, str]    # {table_name: prefix}
    complexity_score: dict               # {tables, avg_columns, avg_constraints}
    dialect: str                   # 方言 (sqlite/postgresql)
```

**数据流**:
```
阶段 1 LLM 输出 (JSON)
       │
       ▼ (parse + validate)
StructureSummary (内存对象)
       │
       ├──→ 阶段 2 per_column: 每列分析时注入
       │    - TableStructureSummary.naming_prefix (生成 template 前缀)
       │    - TableStructureSummary.cross_column_checks (跨列上下文)
       │    - StructureSummary.fk_graph (FK 引用上下文)
       │
       └──→ 阶段 3: 校验时注入
            - StructureSummary.topological_order (FK 级联检查)
            - StructureSummary.fk_graph (FK 完整性校验)
```

### 6.8 错误分类器具体规则

**问题**: transient/logic/quality 三分类无具体实现规则, 无法编码.

**方案**: 定义明确的分类规则, 基于异常类型 + 输出特征.

位置: `plugins/sqlseed-ai/staged_analyzer.py` 中的 `ErrorClassifier` 类

```python
from __future__ import annotations
from enum import Enum

class ErrorCategory(Enum):
    TRANSIENT = "transient"   # 临时性 (重试可解决)
    LOGIC = "logic"           # 逻辑错误 (换 prompt/策略)
    QUALITY = "quality"       # 质量不足 (降级处理)

class ErrorClassifier:
    """LLM 调用失败分类器, 纯规则, 无 LLM."""

    @staticmethod
    def classify(error: Exception, output: str | None = None) -> ErrorCategory:
        """根据异常类型 + 输出内容分类."""

        # === TRANSIENT (临时性, 重试可解决) ===
        # 1. 网络超时 (LM Studio/Ollama 响应慢)
        if isinstance(error, TimeoutError):
            return ErrorCategory.TRANSIENT
        # 2. 连接错误 (服务未启动/端口占用)
        from openai import APIConnectionError, APITimeoutError
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            return ErrorCategory.TRANSIENT
        # 3. 服务端临时错误 (5xx, 限流)
        from openai import InternalServerError, RateLimitError
        if isinstance(error, (InternalServerError, RateLimitError)):
            return ErrorCategory.TRANSIENT
        # 4. GPU 显存临时不足 (LM Studio 切换模型时)
        if "out of memory" in str(error).lower() or "cuda" in str(error).lower():
            return ErrorCategory.TRANSIENT

        # === LOGIC (逻辑错误, 换 prompt/策略重试) ===
        # 1. JSON 解析失败 (输出不是有效 JSON)
        if isinstance(error, (ValueError, json.JSONDecodeError)):
            return ErrorCategory.LOGIC
        # 2. JSON 有效但 schema 不匹配 (缺字段/类型错)
        if "schema" in str(error).lower() and "mismatch" in str(error).lower():
            return ErrorCategory.LOGIC
        # 3. 列数不匹配 (LLM 输出 5 列, 实际表有 6 列)
        if output and output.strip().startswith("{"):
            try:
                parsed = json.loads(output)
                if isinstance(parsed, dict) and "columns" in parsed:
                    # 列数检查在外部完成, 此处只标记分类
                    return ErrorCategory.LOGIC
            except Exception:
                pass
        # 4. generator 名称非法 (LLM 编造不存在的生成器)
        if "unknown generator" in str(error).lower() or "invalid generator" in str(error).lower():
            return ErrorCategory.LOGIC
        # 5. params 类型错误 (integer 给了字符串)
        if "param" in str(error).lower() and "type" in str(error).lower():
            return ErrorCategory.LOGIC

        # === QUALITY (质量不足, 降级处理) ===
        # 1. 空输出 (LLM 直接返回 "" 或 "{}")
        if output is None or output.strip() in ("", "{}"):
            return ErrorCategory.QUALITY
        # 2. 输出过短 (有效 JSON 但内容空洞, 如 {"name": "users", "columns": []})
        if output and len(output.strip()) < 50:
            return ErrorCategory.QUALITY
        # 3. 所有列都是默认值 (LLM 没有真正分析, 全部 fallback)
        if output and '"generator": "string"' in output.lower():
            # 检测是否所有列都是 string (典型的"放弃"模式)
            import re
            string_count = output.lower().count('"generator": "string"')
            total_count = output.lower().count('"generator":')
            if total_count > 0 and string_count / total_count > 0.8:
                return ErrorCategory.QUALITY
        # 4. RuntimeError 兜底 (未知错误, 视为质量不足, 降级)
        # 注: 不抛出, 让管线继续而非崩溃

        # === 默认: 未知错误归为 QUALITY (降级, 不让管线崩溃) ===
        return ErrorCategory.QUALITY
```

**分类后的处理策略**:

| 类别 | 处理策略 | 重试上限 | 降级动作 |
|------|---------|---------|---------|
| TRANSIENT | 同 prompt 重试 | 3 次 | 仍失败 → 跳过该表, 记录 warning |
| LOGIC | 换 prompt (更简单) 重试 | 3 次 | 仍失败 → 降级为类型默认生成器 |
| QUALITY | 不重试, 直接降级 | 0 次 | 降级为最小 config (类型路由生成器) |

**降级 config 示例** (per_column QUALITY 失败):
```python
# 失败的列: {name: "discount_rate", type: "REAL", nullable: False}
# 降级输出: 按类型路由的最小 config
{
    "name": "discount_rate",
    "generator": "float",       # 按类型路由
    "params": {"min_value": 0, "max_value": 1},  # 保守默认值
    "constraints": {"nullable": False},
}
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
| 解决 projects 表 word+min_length 不兼容 | ✓ 阶段 3 新增 auto-fix #14 GENERATOR_PARAMS 校验 |
| 解决 sales FK 级联违规 | ✓ 部分满载 FK 父表闭包 + 级联检测 |
| 解决 full_name 用 word 生成器 | ✓ 阶段 3 现有 auto-fix #9 语义名强制 (已存在) |
| 解决 phone 无界正则 | ✓ 阶段 3 新增 auto-fix #15 无界正则加上界 |
| 解决 template 前缀复用 | ✓ 阶段 3 新增 auto-fix #16 前缀从表名派生 |
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
  analyzer/__init__.py                          # 导出 StagedSchemaAnalyzer (新增导出, 不破坏现有导出)
  config.py                                     # 新增 AIConfig.use_staged_pipeline: bool = False 字段
  cli/ai_commands.py                             # ai-analyze 命令接入分阶段管线 (flag 切换)
```

注: `staged_analyzer.py` 是新增文件 (见 §11.1), 不在修改列表中.
     `Stage3Validator` 类位于 `staged_analyzer.py` 内 (与 `StagedSchemaAnalyzer` 同文件).

### 11.3 不修改文件

```
src/sqlseed/database/_protocol.py                # DatabaseAdapter protocol 不变
src/sqlseed/database/sqlalchemy_adapter.py       # 现有适配器不变
src/sqlseed/database/raw_sqlite_adapter.py        # 测试适配器不变
src/sqlseed/core/schema.py                       # SchemaInferrer 保留兼容
src/sqlseed/core/mapper.py                        # ColumnMapper 不变
src/sqlseed/generators/                           # 生成器不变
plugins/sqlseed-ai/src/sqlseed_ai/
  schema_analyzer.py                            # 现有 SchemaSemanticAnalyzer 保留, 阶段 3 调用其
                                                # _auto_fix_config (规则 1-13), 但不修改其代码
  analyzer/__init__.py 中的 SchemaAnalyzer      # 现有 SchemaAnalyzer 保留, 阶段 1/2 复用其
                                                # _call_llm_once(), 但不修改其代码
  refiner.py                                    # 现有 AiConfigRefiner 保留, 阶段 2 复用其重试逻辑
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
5. **Phase 5 (P0)**: 阶段 3 新增 auto-fix 规则 #14-#16 (Stage3Validator)
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

**文档版本**: 1.1 (P0/P1 修正版)
**创建日期**: 2026-07-02
**作者**: AI 辅助设计 (brainstorming skill)
**审核状态**: 待用户二次审核

**v1.1 变更摘要** (基于 v1.0 评审反馈):

P0 严重问题修正:
- §4.2: StructuralFeatureExtractor 改用实际 Protocol API (get_column_info/
  get_primary_keys/get_index_info/get_check_constraints), 不再调用不存在的
  get_columns/get_pk_constraint/get_unique_constraints
- §4.2: 新增 _aggregate_foreign_keys() 方法, 聚合单列 ForeignKeyInfo 为复合
  ForeignKeyFeatures (现有 Protocol FK 是单列)
- §6.1 阶段 3: auto-fix 规则编号修正——现有规则 1-13 (位于 schema_analyzer.py
  _auto_fix_config), 新增规则 14-16 (在 staged_analyzer.Stage3Validator).
  删除虚构的 "#11-#16 已存在" 和 "#17-#19 新增" 说法

P1 设计遗漏补充:
- §6.6: StagedSchemaAnalyzer 与现有 SchemaSemanticAnalyzer/SchemaAnalyzer/
  AiConfigRefiner 的关系定义 (通过 AIConfig.use_staged_pipeline flag 切换,
  现有类不修改, 新类复用现有底层方法)
- §6.7: StructureSummary dataclass 定义阶段 1 → 阶段 2/3 的内存传递格式
  (含 TableStructureSummary 子结构, 跨列 CHECK 上下文)
- §6.1 per_column 模式: 注入同表所有跨列 CHECK 表达式 + 涉及列名+类型
  作为上下文, 解决 start_date ≤ end_date 跨列 CHECK 无法处理问题
- §6.8: ErrorClassifier 具体分类规则 (基于异常类型 + 输出特征),
  TRANSIENT/LOGIC/QUALITY 三类有明确的处理策略和降级动作
