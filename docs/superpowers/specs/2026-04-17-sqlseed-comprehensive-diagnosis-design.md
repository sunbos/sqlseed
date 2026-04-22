# sqlseed 全面诊断与渐进式改进设计

**日期**：2026-04-17
**版本**：v0.1.10 → v0.2.0
**状态**：已确认

---

## 摘要

对 sqlseed 项目进行全面深度诊断，发现 3 个严重 Bug、1 个架构问题（God Class）、3 个测试覆盖缺口和若干代码规范问题。采用渐进式修复策略，分 4 个 Phase 依次推进：Bug 修复 → 测试补全 → 架构重构 → 规范增强。

---

## 诊断发现

### 严重 Bug（3 个）

1. **CLI `transform_fn` 未传递**：`sqlseed.fill()` API 没有 `transform` 参数，CLI `fill` 命令加载了 `transform_fn` 但无法传递给 `api_fill()`，用户看到 "Transform applied" 但实际未生效。
   - 文件：`src/sqlseed/__init__.py:33-61`、`src/sqlseed/cli/main.py:62-83`

2. **`fill_from_config` FK 顺序**：配置文件中表的排列顺序决定填充顺序，如果 FK 子表在父表之前，FK 解析失败。项目已有 `RelationResolver.topological_sort()` 但未使用。
   - 文件：`src/sqlseed/__init__.py:79-100`

3. **`ConstraintSolver` hash() 缺陷**：概率模式使用 `hash()` 对整数是恒等映射、跨会话不稳定、假阳性方向错误，且 `_hash_seen` 内存未真正优化。
   - 文件：`src/sqlseed/core/constraints.py:35-43`

### 中等 Bug（1 个）

4. **`SharedPool._pools` 封装破坏**：`relation.py:114` 和 `orchestrator.py:649` 直接访问 `_pools` 私有属性。

### 架构问题

`DataOrchestrator`（851 行）承担 10 项职责，违反单一职责原则：
- 枚举列检测 + Enrichment 逻辑（~150 行）
- 唯一约束调整（~100 行）
- FK 解析 + 隐式关联（~80 行）
- AI 建议（~60 行）
- 模板池（~40 行）
- 唯一列检测（~20 行）

### 测试覆盖缺口

| 模块 | 当前覆盖率 | 目标 |
|------|-----------|------|
| `core/transform.py` | 33% | 85%+ |
| `core/constraints.py` | 53% | 85%+ |
| `generators/stream.py` | 67% | 85%+ |
| `core/column_dag.py` | 81% | 85%+ |

完全缺失的测试文件：`test_column_dag.py`、`test_constraints.py`、`test_transform.py`

### 代码规范问题

- 8 个 `__init__.py` 缺少 `from __future__ import annotations`
- `_utils/sql_safe.py` 和 `_utils/schema_helpers.py` 使用 `logging` 而非 `structlog`
- CLI `inspect` 命令直接访问 `orch._db`、`orch._schema`、`orch._mapper` 私有属性
- `FakerProvider.generate_pattern` 和 `MimesisProvider.generate_pattern` 使用 `import random` 而非 Provider 的 `_rng`
- `ConstraintSolver.reset_column` 概率模式下未清除 `_hash_seen`

### 根目录散落文件

5 个临时调试脚本（`test_default.py`、`test_default_raw.py`、`test_insert.py`、`test_raw.py`、`test_sqlite_utils.py`）不属于正式测试套件，应清理。

---

## Phase 1 — Bug 修复

### 修复 1：CLI `transform_fn` 未传递

**变更文件**：
- `src/sqlseed/__init__.py`：给 `fill()` 和 `preview()` 添加 `transform: str | None = None` 参数，传递给 `orch.fill_table(transform=transform)` / `orch.preview_table(transform=transform)`
- `src/sqlseed/cli/main.py`：删除多余的 `transform_fn` 加载逻辑，改为 `transform=transform_path` 传给 `api_fill`

### 修复 2：`fill_from_config` FK 顺序

**变更文件**：
- `src/sqlseed/__init__.py`：在 `fill_from_config` 中，通过 `DataOrchestrator` 公共接口获取拓扑排序后的表名顺序再填充

```python
table_names = [tc.name for tc in config.tables]
sorted_names = orch.get_topological_table_order(table_names)
name_to_config = {tc.name: tc for tc in config.tables}
for name in sorted_names:
    table_config = name_to_config[name]
    result = orch.fill_table(...)
```

### 修复 3：`ConstraintSolver` hash() 缺陷

**变更文件**：
- `src/sqlseed/core/constraints.py`：
  - 将 `_is_seen` 概率模式的 `hash(value)` 替换为 `hashlib.sha256` 确定性哈希
  - 修复 `reset_column` 遗漏 `_hash_seen` 的问题

```python
import hashlib

def _deterministic_hash(self, value: Any) -> int:
    data = f"{value!r}".encode("utf-8")
    return int(hashlib.sha256(data).hexdigest()[:16], 16)
```

### 修复 4：`SharedPool` 封装 + CLI 私有属性访问

**变更文件**：
- `src/sqlseed/core/relation.py`：给 `SharedPool` 添加 `items()` 方法和 `__bool__` 协议（`__bool__` 委托给 `has()` 逻辑）
- `src/sqlseed/core/relation.py`：`load_shared_pool` 改用 `shared_pool.items()`
- `src/sqlseed/core/orchestrator.py`：`_resolve_implicit_associations` 改用 `bool(self._shared_pool)` 替代 `self._shared_pool._pools`
- `src/sqlseed/core/orchestrator.py`：添加公共方法 `get_table_names()`、`get_column_info()`、`get_foreign_keys()`、`map_column()`、`get_topological_table_order()`
- `src/sqlseed/cli/main.py`：`inspect` 命令改用公共方法

### 修复 5：`generate_pattern` 使用 `import random`

**变更文件**：
- `src/sqlseed/generators/faker_provider.py`：`generate_pattern` 改用 `self._rng`
- `src/sqlseed/generators/mimesis_provider.py`：同上

```python
def generate_pattern(self, *, regex: str) -> str:
    import rstr
    return rstr.Rstr(self._rng).xeger(regex)
```

---

## Phase 2 — 测试补全

### 2.1 新增测试文件

**`tests/test_core/test_column_dag.py`**：

| 测试场景 | 说明 |
|----------|------|
| `test_build_simple_columns` | 无依赖列的 DAG 构建 |
| `test_build_with_derived_column` | 派生列排在源列之后 |
| `test_build_with_unique_constraint` | `unique_columns` 正确设置约束 |
| `test_build_with_column_config_constraints` | `ColumnConfig.constraints` 正确传递 |
| `test_topological_sort_order` | 多级依赖拓扑排序 |
| `test_circular_dependency_raises` | 循环依赖抛出 `ValueError` |
| `test_is_skip_property` | `generator_name="skip"` 时 `is_skip=True` |

**`tests/test_core/test_constraints.py`**：

| 测试场景 | 说明 |
|----------|------|
| `test_check_and_register_non_unique` | 非唯一列始终允许 |
| `test_check_and_register_unique_first_time` | 首次注册成功 |
| `test_check_and_register_unique_duplicate` | 重复值被拒绝 |
| `test_try_register_returns_backtrack` | 唯一约束失败时 `need_backtrack=True` |
| `test_try_register_none_value_allowed` | `None` 值始终允许 |
| `test_unregister_then_reregister` | 注销后可重新注册 |
| `test_check_composite_unique` | 复合唯一约束 |
| `test_check_composite_with_null` | 含 NULL 的复合元组允许 |
| `test_reset_clears_all` | `reset()` 清除所有 |
| `test_reset_column` | `reset_column()` 只清除指定列 |
| `test_probabilistic_mode_basic` | 概率模式基本功能 |
| `test_probabilistic_reset_column` | 概率模式 `reset_column` 同时清除 `_hash_seen` |

**`tests/test_core/test_transform.py`**：

| 测试场景 | 说明 |
|----------|------|
| `test_load_valid_transform` | 加载含 `transform_row` 的脚本 |
| `test_load_missing_file` | 文件不存在抛出 `FileNotFoundError` |
| `test_load_missing_function` | 缺少 `transform_row` 抛出 `AttributeError` |
| `test_load_invalid_syntax` | 语法错误抛出 `ImportError` |

### 2.2 补全现有测试

- `tests/test_generators/test_stream.py`：回溯、最大重试、`UnknownGeneratorError`
- `tests/test_public_api.py`：`fill_from_config` FK 顺序测试
- `tests/test_cli.py`：`--transform` 端到端测试

### 2.3 清理根目录散落文件

- 将 `test_default.py` 和 `test_default_raw.py` 中有价值的 DEFAULT 值映射测试迁入 `tests/test_database/`
- 删除全部 5 个根目录文件

---

## Phase 3 — 架构重构

### 3.1 提取 `EnrichmentEngine`

**新文件**：`src/sqlseed/core/enrichment.py`（~150 行）

迁移内容：
- `_ENUM_NAME_PATTERNS` → `EnrichmentEngine.ENUM_NAME_PATTERNS`
- `_SMALL_INT_TYPES` → `EnrichmentEngine.SMALL_INT_TYPES`
- `_is_enumeration_column()` → `EnrichmentEngine.is_enumeration_column()`
- `_apply_enrich()` → `EnrichmentEngine.apply()`
- `_build_enriched_spec()` → `EnrichmentEngine._build_enriched_spec()`

接口：

```python
class EnrichmentEngine:
    def __init__(self, db: DatabaseAdapter, mapper: ColumnMapper, schema: SchemaInferrer) -> None: ...

    def apply(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
        column_infos: list[ColumnInfo],
        unique_columns: set[str] | None = None,
    ) -> dict[str, GeneratorSpec]: ...
```

### 3.2 提取 `UniqueAdjuster`

**新文件**：`src/sqlseed/core/unique_adjuster.py`（~100 行）

迁移内容：
- `_adjust_specs_for_unique()` → `UniqueAdjuster.adjust()`

接口：

```python
class UniqueAdjuster:
    def __init__(self, mapper: ColumnMapper) -> None: ...

    def adjust(
        self,
        specs: dict[str, GeneratorSpec],
        unique_columns: set[str],
        count: int,
        column_infos: list[ColumnInfo] | None = None,
    ) -> dict[str, GeneratorSpec]: ...
```

### 3.3 提取唯一列检测到 `SchemaInferrer`

迁移内容：
- `_detect_unique_columns()` → `SchemaInferrer.detect_unique_columns()`

### 3.4 重构原则

- **不改变公共 API**：`fill()`、`connect()`、`preview()`、`fill_from_config()` 签名和行为不变
- **不改变插件 Hook**：11 个 Hook 的调用时机和参数不变
- **不改变数据流**：`GeneratorSpec` → `ColumnNode` → `DataStream` 管线不变
- **每个提取模块都有独立测试**

---

## Phase 4 — 规范与增强

### 4.1 代码规范修复

- 8 个 `__init__.py` + `_version.py` 补全 `from __future__ import annotations`
- `_utils/sql_safe.py` 和 `_utils/schema_helpers.py` 的 `logging` → `structlog`
- CLI `inspect` 改用 `DataOrchestrator` 公共方法

### 4.2 性能基准测试框架

**新文件**：`tests/benchmarks/bench_fill.py`

基准场景：
- 1K / 10K / 100K 行单表填充
- 含 UNIQUE 约束的 10K 行填充
- 含 FK 关联的多表填充
- 预览 5 行的延迟

依赖：`pytest-benchmark`（添加到 dev 依赖）

### 4.3 列映射规则外部化（可选）

- 支持 YAML 文件加载自定义映射规则
- CLI 添加 `--mapping-rules` 选项
- `GeneratorConfig` 添加 `mapping_rules` 字段

---

## 实施顺序与 PR 规划

| Phase | PR | 内容 | 预计变更文件数 |
|-------|-----|------|--------------|
| 1 | #1 | 修复 CLI transform_fn | 3 |
| 1 | #2 | 修复 fill_from_config FK 顺序 | 2 |
| 1 | #3 | 修复 ConstraintSolver + SharedPool + generate_pattern + reset_column | 5 |
| 2 | #4 | 新增 test_column_dag.py | 2 |
| 2 | #5 | 新增 test_constraints.py + test_transform.py | 3 |
| 2 | #6 | 补全 stream/public_api/cli 测试 + 清理根目录 | 8 |
| 3 | #7 | 提取 EnrichmentEngine | 4 |
| 3 | #8 | 提取 UniqueAdjuster + detect_unique_columns | 4 |
| 4 | #9 | 代码规范修复（future import + structlog + CLI 公共 API） | 12 |
| 4 | #10 | 性能基准测试框架 | 3 |

---

## 验收标准

- [ ] 全部 3 个严重 Bug 修复，有对应回归测试
- [ ] 测试覆盖率 ≥ 85%（当前 90%，但关键模块低于 85%）
- [ ] `DataOrchestrator` 行数 ≤ 550 行
- [ ] 新增模块（`EnrichmentEngine`、`UniqueAdjuster`）覆盖率 ≥ 90%
- [ ] 根目录无散落测试文件
- [ ] 所有 `__init__.py` 包含 `from __future__ import annotations`
- [ ] `ruff check` 和 `mypy` 通过
