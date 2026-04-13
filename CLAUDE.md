# CLAUDE.md — sqlseed Claude 专用指令

本文件为 Claude（Anthropic）在 sqlseed 代码库中工作提供专用指令，补充 `AGENTS.md` 中的通用指令。

## 项目背景

sqlseed 是一个 Python 3.10+ 库，使用 `src` 布局（`src/sqlseed/`）。本文件（`AGENTS.md`）包含完整的架构说明和设计决策。

## 如何参与本项目

### 修改前

1. 阅读 `AGENTS.md` 了解通用规范和架构
2. 检查 `tests/` 中的现有测试，了解测试模式
4. 修改前运行 `pytest` 验证基线

### 添加功能时

1. 遵循基于 Protocol 的设计模式。新的 Provider/Adapter 必须满足现有 Protocol。
2. 所有公共函数需要仅关键字参数（使用 `*` 分隔符）。
3. 任何新的配置结构使用 Pydantic BaseModel。
4. 通过现有的 Registry/Plugin 模式注册新组件。

### 修复 Bug 时

1. 先编写失败的测试
2. 修复 Bug
3. 验证所有测试通过（`pytest`）

## 技术细节

### 模块依赖（分层架构）

```
cli/ → core/ → generators/
                database/
                plugins/
                config/

_utils/ → （无内部依赖，被所有层使用）
```

### 测试模式

- **Fixtures**：公共 fixtures 在 `tests/conftest.py`（临时数据库路径、示例表）
- **适配器**：使用真实 SQLite 数据库测试（`:memory:` 和临时文件）
- **CLI**：使用 `click.testing.CliRunner` — 禁止使用 subprocess
- **Provider**：独立测试每个 generate_* 方法
- **插件**：通过 `PluginManager` 测试 Hook 注册和调用
- **AI 测试**：需要 `sqlseed-ai` 插件的测试使用 `@pytest.mark.skipif`

### 关键实现细节

- `DataOrchestrator.fill()` 是主要别名（匹配设计文档）。`fill_table()` 是原始实现。
- `transform_batch` Hook 返回 `list[result]`（非 firstresult）。编排器通过 `_apply_batch_transforms()` 链式处理。
- `DataStream` 使用自己的 `random.Random(seed)` 实例处理 null_ratio/choice 操作，与 Provider 的 RNG 分离。
- `PragmaOptimizer.restore()` 在应用 PRAGMA 值前用正则验证（安全措施）。
- `_is_autoincrement` 检测集中在 `_utils/schema_helpers.py`。
- `ExpressionEngine` 具有基于线程的超时机制（默认 5 秒），通过 `ExpressionTimeoutError` 报告。
- `relation.py` 中的 `SharedPool` 维护跨表值池以保持 FK 引用完整性。
- `DatabaseAdapter` Protocol 包含 `IndexInfo`、`get_index_info()` 和 `get_sample_rows()`。
- 插件系统有 10 个 Hook，包括 `sqlseed_ai_analyze_table`（firstresult）和 `sqlseed_shared_pool_loaded`。
- CLI `fill` 命令使用 `--config` 时 `db_path` 为可选。
- AI 插件默认模型为 `qwen3-coder-plus`，可通过 `AIConfig` 或环境变量配置。

### 代码风格

```python
# ✅ 好的
from __future__ import annotations
from typing import Any

def some_function(*, required_param: str, optional: int = 10) -> list[str]:
    ...

# ❌ 不好的
from typing import Union, List, Optional

def some_function(required_param, optional=10):
    ...
```

### 导入

```python
# ✅ 推荐：TYPE_CHECKING 守卫用于仅类型导入
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlseed.database._protocol import ColumnInfo

# ✅ 推荐：可选依赖的延迟导入
def method(self):
    import sqlite_utils  # 在此处导入，而非模块顶部
```

## 文件模板

### 新 Provider 模板

```python
from __future__ import annotations
from typing import Any

class NewProvider:
    def __init__(self) -> None:
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "new_provider"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        ...

    # 实现 DataProvider Protocol 的所有方法
    # 参见：src/sqlseed/generators/_protocol.py
```

### 新测试模板

```python
from __future__ import annotations
import pytest

class TestNewFeature:
    def test_basic_case(self, tmp_path):
        ...

    def test_edge_case(self):
        ...

    def test_error_case(self):
        with pytest.raises(ValueError, match="expected message"):
            ...
```

## 常见陷阱

1. **种子处理**：不要在编排器中设置 Provider 种子 — `DataStream.__init__` 负责处理
2. **Hook 返回值**：`pluggy` 对非 firstresult Hook 返回 `list[result]`，不是单个值
3. **sqlite-utils API**：`table.columns_dict` 返回 `{name: type}`，type 可能是 Python 类型类，不是字符串
4. **Mimesis 地区**：使用短代码（"en"、"zh"）而非 Faker 风格（"en_US"、"zh_CN"）— 参见 `MimesisProvider.set_locale()` 映射
5. **内存**：永远不要在写入前收集所有行 — 使用 `DataStream.generate()` 逐批 yield
6. **表达式超时**：使用 `ExpressionEngine.evaluate()` 时始终处理 `ExpressionTimeoutError`
7. **AI 插件测试**：需要可选 `sqlseed-ai` 依赖的测试使用 `@pytest.mark.skipif`

## 常用命令

```bash
# 运行特定测试文件
pytest tests/test_orchestrator.py -v

# 运行匹配模式的测试
pytest -k "test_fill" -v

# 完整输出运行
pytest --tb=long --no-header -v

# 检查特定模块覆盖率
pytest --cov=sqlseed.core.orchestrator --cov-report=term-missing

# 代码检查并自动修复
ruff check --fix src/ tests/
```
