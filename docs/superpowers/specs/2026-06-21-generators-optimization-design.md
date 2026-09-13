# generators/ 目录优化设计文档

**生成日期**：2026-06-21
**目录范围**：`src/sqlseed/generators/`（11 个文件）
**方法论**：9 步法（read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate）

---

## 一、问题识别

### P0（Bug）
无。

### P1（重要 — Bug + docstring 缺失）

#### P1.1 `base_provider.py` `_gen_date`/`_gen_datetime` 忽略 `start_year` 参数
**问题**：方法签名接受 `start_year` 和 `end_year` 参数但完全不用，硬编码 `datetime(2024, 1, 1)`。用户配置 `start_year=2010` 时仍返回 2024 年日期，是误导性 API。

**当前代码**：
```python
def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
    n = self._next_id()
    base = datetime(2024, 1, 1) + timedelta(days=n - 1)  # ← 硬编码 2024
    return base.strftime("%Y-%m-%d")
```

**修复方案**：将 `datetime(2024, 1, 1)` 改为 `datetime(start_year, 1, 1)`，尊重用户配置，保持计数器递增设计。`end_year` 仍不使用（base provider 递增设计不需要上界，与 faker/mimesis 的随机设计不同）。

#### P1.2 全部 11 个文件缺模块 docstring
| 文件 | 缺失项 |
|------|--------|
| `__init__.py` | 模块 docstring |
| `_protocol.py` | 模块 + 3 个异常类 + `DataProvider` 协议 docstring |
| `_dispatch.py` | 模块 + `GeneratorDispatchMixin` 类 + `generate` 方法 docstring |
| `_json_helpers.py` | 模块 + 函数 docstring |
| `_string_helpers.py` | 模块 + 函数 docstring |
| `base_provider.py` | 模块 docstring；类 docstring 英文（遵循 PEP 8/257）；方法缺 docstring |
| `faker_provider.py` | 模块 docstring；类 docstring 英文（遵循 PEP 8/257）；方法缺 docstring |
| `mimesis_provider.py` | 模块 docstring；类 docstring 英文（遵循 PEP 8/257）；方法缺 docstring |
| `registry.py` | 模块 + `ProviderRegistry` 类 + 方法 docstring |
| `stream.py` | 模块 + `DataStream` 类 + 方法 docstring |

### P2（设计 — AGENTS.md 过时）
- 缺少日期头
- STRUCTURE 表格缺失 `__init__.py`

### P3（风格 — 技术债务）

#### P3.1 冗余 pylint 注释
**问题**：`_dispatch.py` 第 54 行和 `base_provider.py` 第 243 行有 `# pylint: disable=import-outside-toplevel`，但项目使用 ruff 不使用 pylint，且已有 `# noqa: PLC0415` 替代。

**修复方案**：删除 `# pylint: disable=import-outside-toplevel` 注释，保留 `# noqa: PLC0415`。

#### P3.2 `_json_helpers.py` 类型注解过松
**问题**：`provider: Any` 丢失类型安全。

**修复方案**：改为 `DataProvider` 协议类型，通过 `TYPE_CHECKING` 导入避免循环依赖。

---

## 二、设计方案

### 2.1 P1.1 修复 `_gen_date`/`_gen_datetime`

**`base_provider.py` 修改**：
```python
# 修改前
def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
    n = self._next_id()
    base = datetime(2024, 1, 1) + timedelta(days=n - 1)
    return base.strftime("%Y-%m-%d")

def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
    n = self._next_id()
    base = datetime(2024, 1, 1) + timedelta(hours=n - 1)
    return base.strftime("%Y-%m-%d %H:%M:%S")

# 修改后
def _gen_date(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
    n = self._next_id()
    base = datetime(start_year, 1, 1) + timedelta(days=n - 1)
    return base.strftime("%Y-%m-%d")

def _gen_datetime(self, *, start_year: int = 2000, end_year: int | None = None) -> str:
    n = self._next_id()
    base = datetime(start_year, 1, 1) + timedelta(hours=n - 1)
    return base.strftime("%Y-%m-%d %H:%M:%S")
```

**测试影响**：Agent C 需检查 `tests/test_generators/` 中是否有测试断言硬编码 2024 日期，如有则更新为使用 `start_year` 默认值 2000。

### 2.2 P1.2 docstring 补充（英文）

所有 11 个文件补充模块/类/方法级英文 docstring。遵循 Python PEP 8/257 规范，docstring 统一使用英文。

### 2.3 P3.1 删除冗余 pylint 注释

**`_dispatch.py` 第 53-55 行**：
```python
# 修改前
    # Imports inside function to avoid circular dependency at module load time.
    # pylint: disable=import-outside-toplevel
    from sqlseed.generators.base_provider import BaseProvider  # noqa: PLC0415

# 修改后
    # Import inside function to avoid circular dependency at module load time
    from sqlseed.generators.base_provider import BaseProvider  # noqa: PLC0415
```

**`base_provider.py` 第 242-244 行**：
```python
# 修改前
        try:
            # Optional dependency — import inside function to defer ImportError.
            # pylint: disable=import-outside-toplevel
            import rstr as _rstr  # noqa: PLC0415

# 修改后
        try:
            # Optional dependency — import inside function to defer ImportError
            import rstr as _rstr  # noqa: PLC0415
```

### 2.4 P3.2 `_json_helpers.py` 类型注解改进

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from sqlseed.generators._protocol import DataProvider

def generate_json_from_schema(
    provider: DataProvider,
    schema: dict[str, Any] | None,
    get_array_count: Callable[[], int],
) -> str:
    ...

def _generate_from_schema(
    provider: DataProvider,
    schema: dict[str, Any],
    get_array_count: Callable[[], int],
) -> Any:
    ...
```

**循环依赖分析**（安全）：
- `_json_helpers.py` →（TYPE_CHECKING）→ `_protocol.py`
- `_protocol.py` 无其他 sqlseed 导入
- 无循环依赖

### 2.5 P2 AGENTS.md 更新
- 添加 `**Generated:** 2026-06-21` 日期头
- STRUCTURE 表格添加 `__init__.py` 行

---

## 三、3 智能体分工

### Agent A（独立辅助文件 — docstring + 类型注解 + pylint 清理）
**文件**：
- `__init__.py`：模块 docstring
- `_protocol.py`：模块 + 3 个异常类 + `DataProvider` 协议 docstring
- `_string_helpers.py`：模块 + 函数 docstring
- `_json_helpers.py`：模块 + 函数 docstring + `provider: Any` → `DataProvider` 类型改进
- `_dispatch.py`：模块 + 类 + 方法 docstring + 删除 pylint 注释

**约束**：仅添加 docstring 和类型注解改进，不修改业务逻辑。

### Agent B（Provider 文件 — Bug 修复 + docstring 补充）
**文件**：
- `base_provider.py`：修复 `_gen_date`/`_gen_datetime` + 类 docstring 英文（遵循 PEP 8/257）+ 方法 docstring + 删除 pylint 注释
- `faker_provider.py`：类 docstring 英文（遵循 PEP 8/257）+ 方法 docstring
- `mimesis_provider.py`：类 docstring 英文（遵循 PEP 8/257）+ 方法 docstring

**约束**：
- `_gen_date`/`_gen_datetime` 仅将 `datetime(2024, 1, 1)` 改为 `datetime(start_year, 1, 1)`
- 不修改其他业务逻辑
- 英文 docstring 保持英文，补充缺失的英文 docstring

### Agent C（registry + stream + AGENTS.md + 审查 + 验证）
**任务**：
1. `registry.py`：模块 + `ProviderRegistry` 类 + 方法 docstring
2. `stream.py`：模块 + `DataStream` 类 + 方法 docstring
3. `AGENTS.md`：添加日期头 + STRUCTURE 补全 `__init__.py`
4. 审查 Agent A 和 B 的修改
5. 运行 `ruff check src/sqlseed/generators/`
6. 运行 `mypy src/sqlseed/generators/`
7. 运行 `python -m pytest tests/test_generators/ -x --tb=short`
8. 修复任何验证失败（特别是 `_gen_date` 修复可能影响的测试）

---

## 四、验证标准

| 命令 | 预期结果 |
|------|----------|
| `ruff check src/sqlseed/generators/` | All checks passed |
| `mypy src/sqlseed/generators/` | Success: no issues found |
| `python -m pytest tests/test_generators/ -x --tb=short` | All tests passed |

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| `_gen_date` 修复改变默认日期范围（2024→2000） | 中 | 依赖 2024 年日期的测试可能失败 | Agent C 需检查并更新相关测试断言 |
| `end_year` 参数仍不生效 | 低 | 误导性 API | 在 docstring 中明确说明 base provider 使用递增设计，不需要上界 |
| docstring 英文翻译不准确 | 低 | 语义偏差 | 保持原意，使用标准 Python docstring 风格 |

---

## 五、不修改项

- `_random_date` / `_resolve_date_range` 方法：虽然 `_random_date` 在 `BaseProvider` 中未被调用，但 `_resolve_date_range` 被 `FakerProvider`/`MimesisProvider` 使用，保留不动
- `CHANGELOG.md` / `CHANGELOG.zh-CN.md`：历史记录
- 业务逻辑（除 `_gen_date`/`_gen_datetime` Bug 修复外）
