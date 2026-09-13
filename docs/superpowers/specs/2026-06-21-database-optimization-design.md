# database/ 目录优化设计文档

**生成日期**：2026-06-21
**目录范围**：`src/sqlseed/database/`（11 个文件）
**方法论**：9 步法（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）

---

## 一、问题识别

### P0（Bug）
无。`optimizer.py` 中的 `sqlite3.DatabaseError` 捕获是正确的（`PragmaOptimizer` 仅用于 SQLite 方言，通过 raw DBAPI 连接执行 PRAGMA，异常类型匹配）。

### P1（重要 — docstring 缺失）
| 文件 | 缺失项 |
|------|--------|
| `__init__.py` | 模块 docstring |
| `_base_adapter.py` | 模块/类/方法 docstring |
| `_helpers.py` | 模块/函数 docstring |
| `_protocol.py` | 模块 docstring，3 个 dataclass docstring |
| `optimizer.py` | 模块/类/方法 docstring |
| `raw_sqlite_adapter.py` | 模块/类/方法 docstring |
| `sqlalchemy_adapter.py` | 部分方法缺 docstring |

### P2（设计 — AGENTS.md 过时）
- 缺少日期头
- STRUCTURE 表格缺失 6 个文件（`__init__.py`、`_bulk_optimizer.py`、`_dialect.py`、`_protocol.py`、`_type_normalizer.py`、`sqlalchemy_adapter.py`）
- WHERE TO LOOK 表格不完整
- CONVENTIONS 未提及 Dialect / BulkWriteOptimizer / TypeNormalizer 三大抽象

### P3（设计 — 命名误导与技术债务）

#### P3.1 `BaseSQLiteAdapter` 命名误导
**问题**：`BaseSQLiteAdapter` 暗示"所有 SQLite 适配器的基类"，但 `SQLAlchemyAdapter`（支持 SQLite 方言）并未继承它。唯一子类是 `RawSQLiteAdapter`。

**影响范围**（搜索确认）：
- `src/sqlseed/database/_base_adapter.py`（类定义）
- `src/sqlseed/database/raw_sqlite_adapter.py`（import + 继承）
- `src/sqlseed/database/AGENTS.md`（3 处引用）
- `CHANGELOG.md` / `CHANGELOG.zh-CN.md`（历史记录，**不修改**）
- **无测试文件引用**（安全）

#### P3.2 `SQLAlchemyAdapter` 重复逻辑
**问题**：`SQLAlchemyAdapter.optimize_for_bulk_write` 和 `restore_settings` 内联了 `preserve()/optimize()/restore()` 逻辑，与 `_helpers.py` 的 `apply_pragma_optimize`/`apply_pragma_restore` 完全重复。

#### P3.3 `_helpers.py` 函数命名误导
**问题**：`apply_pragma_optimize` / `apply_pragma_restore` 名称含 "pragma"，但该函数也用于 `PostgresBulkOptimizer`（使用 `SET synchronous_commit = OFF`，非 PRAGMA）。命名不准确。

#### P3.4 `_helpers.py` 类型注解过于宽松
**问题**：`optimizer: Any` 丢失类型安全。`PragmaOptimizer` 和 `BulkWriteOptimizer` 协议方法签名兼容，可统一类型。

---

## 二、设计方案

### 2.1 P3.1 重命名 `BaseSQLiteAdapter` → `BaseRawSQLiteAdapter`

**理由**：`BaseRawSQLiteAdapter` 明确表达"原始 sqlite3 访问的基类"，与 `SQLAlchemyAdapter`（通过 SQLAlchemy 抽象层访问）清晰区分。

**修改清单**：
1. `_base_adapter.py`：`class BaseSQLiteAdapter:` → `class BaseRawSQLiteAdapter:`
2. `raw_sqlite_adapter.py`：
   - `from sqlseed.database._base_adapter import BaseSQLiteAdapter` → `import BaseRawSQLiteAdapter`
   - `class RawSQLiteAdapter(BaseSQLiteAdapter):` → `class RawSQLiteAdapter(BaseRawSQLiteAdapter):`
3. `AGENTS.md`：3 处引用更新

**文件名保持**：`_base_adapter.py`（私有模块，下划线前缀，文件名无需跟随类名变更）

### 2.2 P3.2 + P3.3 重命名 helper 函数 + 复用

**重命名**：
- `apply_pragma_optimize` → `apply_bulk_optimize`（通用，适用于 PRAGMA 和 SET 两种优化策略）
- `apply_pragma_restore` → `apply_bulk_restore`

**修改清单**：
1. `_helpers.py`：函数定义重命名 + 类型注解改进 + docstring
2. `_base_adapter.py`：import 更新 + 调用点更新
3. `sqlalchemy_adapter.py`：复用 helper，消除重复逻辑：
   ```python
   # 修改前（内联）
   def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
       if self._optimizer is not None:
           self._optimizer.preserve()
           self._optimizer.optimize(expected_rows)

   def restore_settings(self) -> None:
       if self._optimizer is not None:
           self._optimizer.restore()

   # 修改后（复用 helper）
   def optimize_for_bulk_write(self, expected_rows: int | None = None) -> None:
       apply_bulk_optimize(self._optimizer, expected_rows)

   def restore_settings(self) -> None:
       apply_bulk_restore(self._optimizer)
   ```
4. `AGENTS.md`：引用更新

### 2.3 P3.4 类型注解改进

**`_helpers.py`** 类型注解：
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlseed.database._bulk_optimizer import BulkWriteOptimizer
    from sqlseed.database.optimizer import PragmaOptimizer

def apply_bulk_optimize(
    optimizer: BulkWriteOptimizer | PragmaOptimizer | None,
    expected_rows: int | None = None,
) -> None:
    if optimizer is not None:
        optimizer.preserve()
        optimizer.optimize(expected_rows)

def apply_bulk_restore(
    optimizer: BulkWriteOptimizer | PragmaOptimizer | None,
) -> None:
    if optimizer is not None:
        optimizer.restore()
```

**循环依赖分析**（安全）：
- `_helpers.py` →（TYPE_CHECKING）→ `_bulk_optimizer.py` + `optimizer.py`
- `_bulk_optimizer.py` →（TYPE_CHECKING）→ `optimizer.py`
- `optimizer.py` → `_utils.logger` only
- 无循环依赖

**mypy 兼容性**：`PragmaOptimizer` 与 `BulkWriteOptimizer` 协议方法签名完全兼容（`preserve()/optimize(expected_rows)/restore()`），mypy 结构子类型识别通过。

### 2.4 P1 docstring 补充

所有 7 个缺 docstring 的文件补充模块/类/方法级英文 docstring。遵循 Python PEP 8/257 规范，docstring 统一使用英文。已有 docstring 的文件（`_bulk_optimizer.py`、`_dialect.py`、`_type_normalizer.py`、`sqlalchemy_adapter.py` 模块级）不修改。

### 2.5 P2 AGENTS.md 更新

- 添加 `**Generated:** 2026-06-21` 日期头
- STRUCTURE 表格补全 11 个文件
- WHERE TO LOOK 表格补全
- CONVENTIONS 新增：
  - **Dialect 抽象**：`Dialect` 协议封装方言差异（类型归一化、自增检测、标识符引用）
  - **BulkWriteOptimizer**：`BulkWriteOptimizer` 协议抽象批量写入优化（SQLite PRAGMA / PG SET）
  - **TypeNormalizer**：将数据库原始类型归一化为 sqlseed 内部类型
  - **异常捕获**：`PragmaOptimizer` 仅用于 SQLite，`sqlite3.DatabaseError` 捕获正确
- 更新 `BaseSQLiteAdapter` → `BaseRawSQLiteAdapter` 引用
- 更新 `apply_pragma_optimize`/`apply_pragma_restore` → `apply_bulk_optimize`/`apply_bulk_restore`

---

## 三、3 智能体分工

### Agent A（独立文件 docstring，无逻辑变更）
**文件**：
- `_protocol.py`：模块 + 3 个 dataclass docstring
- `optimizer.py`：模块 + `PragmaProfile`/`PragmaOptimizer` 类 + 方法 docstring
- `__init__.py`：模块 docstring

**约束**：仅添加 docstring，不修改任何逻辑代码、import、类型注解。

### Agent B（互联文件重构 + docstring）
**文件**：
- `_base_adapter.py`：类重命名 `BaseSQLiteAdapter` → `BaseRawSQLiteAdapter` + docstring
- `_helpers.py`：函数重命名 + 类型注解改进 + docstring
- `raw_sqlite_adapter.py`：更新 import + docstring
- `sqlalchemy_adapter.py`：复用 helper 消除重复 + 补充方法 docstring

**约束**：
- 重命名后确保所有 import 和调用点同步更新
- `sqlalchemy_adapter.py` 的 `optimize_for_bulk_write`/`restore_settings` 改为复用 `apply_bulk_optimize`/`apply_bulk_restore`
- 不修改 `CHANGELOG.md` / `CHANGELOG.zh-CN.md`（历史记录）

### Agent C（AGENTS.md + 审查 + 验证）
**任务**：
1. 更新 `AGENTS.md`（日期、STRUCTURE、WHERE TO LOOK、CONVENTIONS）
2. 审查 Agent A 和 B 的修改（读取文件验证）
3. 运行 `ruff check src/sqlseed/database/`
4. 运行 `mypy src/sqlseed/database/`
5. 运行 `pytest tests/test_database/ -x --tb=short`
6. 修复任何验证失败

---

## 四、验证标准

| 命令 | 预期结果 |
|------|----------|
| `ruff check src/sqlseed/database/` | All checks passed |
| `mypy src/sqlseed/database/` | Success: no issues found |
| `pytest tests/test_database/ -x --tb=short` | All tests passed |

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `BaseRawSQLiteAdapter` 重命名导致外部引用失败 | 低 | 类在私有模块 `_base_adapter.py` 中，无外部引用 | 搜索确认无测试文件引用 |
| `apply_bulk_*` 重命名遗漏调用点 | 极低 | 运行时 AttributeError | Agent B 需同步更新所有 import 和调用点 |
| `SQLAlchemyAdapter` 复用 helper 后行为变化 | 极低 | 逻辑等价，仅封装方式变化 | Agent C 需验证 |
| TYPE_CHECKING 导入在运行时不生效 | 无 | 仅服务于 mypy，Python 类型擦除 | 设计正确，无需缓解 |

---

## 五、不修改项

- `CHANGELOG.md` / `CHANGELOG.zh-CN.md`：历史记录，不修改
- `_bulk_optimizer.py` / `_dialect.py` / `_type_normalizer.py`：已有完整 docstring，不修改
- `optimizer.py` 中的 `sqlite3.DatabaseError` 捕获：正确（PragmaOptimizer 仅用于 SQLite）
- 文件名 `_base_adapter.py`：保持不变（私有模块）
