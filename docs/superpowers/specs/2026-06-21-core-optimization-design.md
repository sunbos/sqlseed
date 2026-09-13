# core/ 目录优化设计文档

**生成日期**: 2026-06-21
**目标目录**: `src/sqlseed/core/`
**方法论**: 9 步流程（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）
**前序参考**: `2026-06-21-utils-optimization-design.md`、`2026-06-21-cli-optimization-design.md`、`2026-06-21-config-optimization-design.md`

---

## 1. 背景

`_utils/`、`cli/`、`config/` 优化已完成并通过验证。用户要求将相同方法论应用到 `core/` 目录。`core/` 目录包含 13 个 Python 文件 + 1 个 AGENTS.md，是 sqlseed 的核心编排层，负责 schema 推断、列映射、约束求解、数据流等。

### 1.1 用户对齐答复

| 问题 | 用户选择 |
|------|----------|
| `sqlite3` 异常捕获失效 | 改为 `sqlalchemy.exc` 异常 |
| `_prepare_specs` 逻辑混乱 | 简化逻辑 |
| `ColumnConstraints` 重复定义 | 保持现状（分层设计） |
| 3 智能体介入时机 | 方案对齐后执行 |

### 1.2 关键调研结论

**sqlite3 异常捕获问题**：
- `orchestrator.py:411` 捕获 `sqlite3.IntegrityError`，但 SQLAlchemy 适配器抛出 `sqlalchemy.exc.IntegrityError`
- `relation.py:301,376,380,386` 和 `plugin_mediator.py:177` 在 `contextlib.suppress` 中使用 `sqlite3.OperationalError`
- `SQLAlchemyBatchInserter` 使用 SQLAlchemy 的 `bulk_insert_mappings`，抛出 `sqlalchemy.exc.*` 异常
- `sqlite3.IntegrityError` 和 `sqlalchemy.exc.IntegrityError` 不是父子关系，`except sqlite3.IntegrityError` 无法捕获后者

**`_prepare_specs` 逻辑分析**（orchestrator.py:252-305）：
```python
# 当前逻辑（混乱）：
if enrich and clear_before:
    specs, ... = self._resolve_specs(...)  # 第一次 resolve（读现有数据）
if clear_before:
    self._db.clear_table(table_name)
if not (enrich and clear_before):
    specs, ... = self._resolve_specs(...)  # 第二次 resolve（表已空）
```
- 当 `enrich=True, clear_before=True`：先 resolve（读数据），再 clear，不再 resolve（但 specs 是清空前的）
- 当 `enrich=False, clear_before=True`：先 clear，再 resolve
- 当 `enrich=True, clear_before=False`：直接 resolve
- 当 `enrich=False, clear_before=False`：直接 resolve

**简化后逻辑**：
```python
# 简化逻辑：
if enrich and clear_before:
    # 先 resolve（读取现有数据用于 enrich），再 clear
    specs, ... = self._resolve_specs(...)
    self._db.clear_table(table_name)
else:
    if clear_before:
        self._db.clear_table(table_name)
    specs, ... = self._resolve_specs(...)
```

---

## 2. 影响分析

### 2.1 受影响文件

| 文件 | 变更类型 | 影响范围 |
|------|----------|----------|
| `orchestrator.py` | 修改 | 异常捕获改 sqlalchemy.exc、_prepare_specs 简化、模块/类 docstring |
| `relation.py` | 修改 | 异常捕获改 sqlalchemy.exc、模块/类 docstring |
| `plugin_mediator.py` | 修改 | 异常捕获改 sqlalchemy.exc、模块/类 docstring |
| `transform.py` | 修改 | Callable 导入修复、模块/函数 docstring |
| `column_dag.py` | 修改 | 模块/类/方法 docstring |
| `constraints.py` | 修改 | 模块/类/方法 docstring |
| `enrichment.py` | 修改 | 模块/类/方法 docstring |
| `expression.py` | 修改 | 模块/类 docstring |
| `mapper.py` | 修改 | 模块/类/方法 docstring |
| `result.py` | 修改 | 模块/类 docstring |
| `schema.py` | 修改 | 模块/类/方法 docstring |
| `unique_adjuster.py` | 修改 | 模块/类/方法 docstring |
| `__init__.py` | 不变 | 无需修改 |
| `AGENTS.md` | 修改 | 日期头、STRUCTURE 补充 result.py、Key Files 补充 __init__.py |

### 2.2 破坏性变更评估

| 变更 | 破坏性 | 缓解措施 |
|------|--------|----------|
| `sqlite3.OperationalError` → `sqlalchemy.exc.OperationalError` | 低：异常捕获范围扩大 | 正面变更，修复潜在 Bug |
| `sqlite3.IntegrityError` → `sqlalchemy.exc.IntegrityError` | 低：同上 | 正面变更 |
| `_prepare_specs` 逻辑简化 | 低：行为不变，代码更清晰 | 需确保所有分支行为一致 |
| `transform.py` Callable 导入 | 无：`collections.abc.Callable` 与 `typing.Callable` 兼容 | 移除 `# noqa: UP035` |

---

## 3. 详细优化计划

### 3.1 P0: sqlite3 异常捕获改为 sqlalchemy.exc

#### 3.1.1 orchestrator.py

**问题**：
- 第 4 行 `import sqlite3`
- 第 411 行 `except (ValueError, RuntimeError, OSError, sqlite3.OperationalError, sqlite3.IntegrityError)`
- 第 412 行 `isinstance(e, sqlite3.IntegrityError)`
- 第 483, 488, 492 行 `contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError)`

**修复**：
- 移除 `import sqlite3`
- 增加 `from sqlalchemy.exc import IntegrityError as SAIntegrityError, OperationalError as SAOperationalError`（延迟导入或顶部导入）
- 替换所有 `sqlite3.OperationalError` → `SAOperationalError`
- 替换所有 `sqlite3.IntegrityError` → `SAIntegrityError`

**导入策略**：在 `orchestrator.py` 顶部导入（因为 sqlalchemy 是核心依赖，且多处使用）。

#### 3.1.2 relation.py

**问题**：
- 第 4 行 `import sqlite3`
- 第 301, 376, 380, 386 行 `contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError)`

**修复**：
- 移除 `import sqlite3`
- 增加 `from sqlalchemy.exc import OperationalError as SAOperationalError`
- 替换所有 `sqlite3.OperationalError` → `SAOperationalError`

#### 3.1.3 plugin_mediator.py

**问题**：
- 第 4 行 `import sqlite3`
- 第 177 行 `contextlib.suppress(ValueError, OSError, RuntimeError, sqlite3.OperationalError)`

**修复**：
- 移除 `import sqlite3`
- 增加 `from sqlalchemy.exc import OperationalError as SAOperationalError`
- 替换 `sqlite3.OperationalError` → `SAOperationalError`

### 3.2 P0: _prepare_specs 逻辑简化（orchestrator.py:252-305）

**当前代码**：
```python
def _prepare_specs(self, ...):
    t_resolve = time.monotonic()
    if enrich and clear_before:
        specs, user_configs, unique_columns = self._resolve_specs(...)
    if clear_before:
        self._db.clear_table(table_name)
    if not (enrich and clear_before):
        specs, user_configs, unique_columns = self._resolve_specs(...)
    ...
```

**简化后**：
```python
def _prepare_specs(self, ...):
    t_resolve = time.monotonic()
    if enrich and clear_before:
        # enrich 模式需要先读取现有数据，再清空表
        specs, user_configs, unique_columns = self._resolve_specs(
            table_name, count, columns, column_configs, enrich
        )
        self._db.clear_table(table_name)
    else:
        # 非 enrich+clear 场景：先清空（如果需要），再 resolve
        if clear_before:
            self._db.clear_table(table_name)
        specs, user_configs, unique_columns = self._resolve_specs(
            table_name, count, columns, column_configs, enrich
        )
    logger.debug("resolve_specs", table_name=table_name, elapsed=f"{time.monotonic() - t_resolve:.3f}s")
    ...
```

**行为不变性验证**：
- `enrich=True, clear_before=True`：resolve → clear（不变）
- `enrich=False, clear_before=True`：clear → resolve（不变）
- `enrich=True, clear_before=False`：resolve（不变）
- `enrich=False, clear_before=False`：resolve（不变）

### 3.3 P0: transform.py Callable 导入修复

**当前代码**：
```python
from typing import Any, Callable  # noqa: UP035
```

**修复**：
```python
from collections.abc import Callable
from typing import Any
```

移除 `# noqa: UP035`。

### 3.4 P1: 模块级 docstring 补充

为以下 12 个文件添加模块级 docstring：

- `column_dag.py`: 列依赖图（DAG）构建与拓扑排序
- `constraints.py`: 约束求解器，支持回溯和复合唯一约束
- `enrichment.py`: 数据富化引擎，19 种枚举模式识别
- `expression.py`: 表达式求值引擎，simpleeval 沙箱
- `mapper.py`: 列映射器，9 级策略链
- `orchestrator.py`: 数据编排器，主引擎
- `plugin_mediator.py`: 插件中介者，插件 ↔ 核心桥接
- `relation.py`: 关系解析器，外键解析 + SharedPool
- `result.py`: 生成结果数据类
- `schema.py`: Schema 推断器，列信息、索引、分布
- `transform.py`: 用户变换脚本加载器
- `unique_adjuster.py`: 唯一约束自动调整器

### 3.5 P1: 类/函数 docstring 补充

为以下类/函数添加 docstring（仅公共 API，私有方法 `_` 前缀的可选）：

- `ColumnDAG` 类及 `build` 方法
- `ConstraintSolver` 类（已有简短 docstring，可保留）
- `EnrichmentEngine` 类
- `ExpressionEngine` 类
- `ExpressionTimeoutError` 类
- `ColumnMapper` 类
- `DataOrchestrator` 类
- `PluginMediator` 类
- `RelationResolver` 类
- `SchemaInferrer` 类
- `UniqueAdjuster` 类
- `GenerationResult` 类
- `SharedPool` 类（已有 docstring）
- `load_transform` 函数

### 3.6 P1: orchestrator.py fill 别名位置

**当前**：`fill = fill_table` 在第 586 行（类定义中间）。

**决策**：保持现状，避免不必要的变更（YAGNI）。此条目标记为 P1 但实际无需修复，降级为"不做"。

### 3.7 P2: AGENTS.md 更新

- 增加日期头：`**Generated:** 2026-06-21`
- STRUCTURE 补充 `result.py`（已有但未列出）
- Key Files 补充 `__init__.py` 行
- CONVENTIONS 更新：异常捕获用 `sqlalchemy.exc.*`（非 `sqlite3.*`）
- ANTI-PATTERNS 更新：`sqlite3.OperationalError` → `sqlalchemy.exc.OperationalError`

---

## 4. 3 智能体交叉执行计划

### 4.1 智能体分工

| 智能体 | 职责 | 范围 |
|--------|------|------|
| **Agent A** | 异常捕获修复 + docstring（前半部分） | relation.py、plugin_mediator.py、transform.py 异常修复 + column_dag.py、constraints.py、enrichment.py、expression.py docstring |
| **Agent B** | docstring（后半部分） | mapper.py、result.py、schema.py、unique_adjuster.py docstring |
| **Agent C** | orchestrator.py 全部修改 + AGENTS.md + 审查合并 + 验证 | orchestrator.py 异常修复 + _prepare_specs 简化 + docstring + AGENTS.md 更新 + 审查 A/B + ruff/mypy/pytest |

### 4.2 执行顺序

1. **A/B 并行执行**（独立文件，无冲突）
2. **C 执行 orchestrator.py 修改**（A/B 完成后，避免冲突）
3. **C 审查 A/B 结果**
4. **C 更新 AGENTS.md**
5. **C 运行验证**

### 4.3 冲突预防

- A 和 B 操作不同文件，无直接冲突
- C 独占 orchestrator.py，避免与 A/B 冲突
- AGENTS.md 由 C 统一更新

---

## 5. 验收标准

### 5.1 功能验收

- [ ] `sqlite3.IntegrityError` 异常能被正确捕获（通过 SQLAlchemy 适配器）
- [ ] `_prepare_specs` 所有分支行为不变
- [ ] `transform.py` 的 `Callable` 从 `collections.abc` 导入
- [ ] 所有现有测试通过

### 5.2 代码质量验收

- [ ] `ruff check .` 变更文件全部通过
- [ ] `ruff format .` 无需格式化
- [ ] `mypy src plugins` 无错误
- [ ] `python -m pytest` 全部通过（不含 Docker 环境错误）
- [ ] 12 个 Python 文件有模块级 docstring
- [ ] 公共类有 docstring
- [ ] AGENTS.md 有日期头

---

## 6. YAGNI 清单（不做）

- ❌ 不合并 `ColumnConstraints` 和 `ColumnConstraintsConfig`（分层设计有意为之）
- ❌ 不移动 `fill = fill_table` 别名位置（影响小）
- ❌ 不为私有方法（`_` 前缀）添加 docstring（可选，非必需）
- ❌ 不重构 `mapper.py` 的 `EXACT_MATCH_RULES` 和 `EXACT_MATCH_PARAMS`（YAGNI）
- ❌ 不重构 `SharedPool.merge` 的 TypeError 处理（YAGNI）

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `sqlalchemy.exc` 导入失败 | 低 | sqlalchemy 是核心依赖 | 确保导入正确 |
| `_prepare_specs` 简化后行为变化 | 中 | enrich 模式失效 | Agent C 需验证所有分支 |
| 异常捕获范围扩大导致隐藏错误 | 低 | 正面影响 | `SAOperationalError` 更精确 |
| docstring 添加过多导致代码膨胀 | 低 | 只添加公共 API | 私有方法可选 |
