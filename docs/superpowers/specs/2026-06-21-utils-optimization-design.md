# `_utils` 模块代码优化设计文档

**日期**: 2026-06-21
**范围**: `src/sqlseed/_utils/` 全部 7 个文件 + `AGENTS.md`
**类型**: 代码质量优化 + Bug 修复 + 安全行为调整
**状态**: 已批准，待执行

***

## 1. 背景与目标

`_utils` 是项目最底层工具层，被几乎所有其他模块依赖。本次优化目标：

1. **修复潜在 Bug**：`schema_helpers.py` 的 `split(",")` 误切割含逗号的类型定义
2. **安全行为调整**：`sql_safe.py` 移除 `-` 危险字符限制（带引号后安全）
3. **代码质量提升**：语义顺序、代码逻辑、格式统一、排版布局、代码解释注释
4. **文档同步**：更新 `AGENTS.md` 反映当前实现

## 2. 影响分析（破坏性变更前置）

| API                    | 调用方模块                                               | 变更类型             | 风险       |
| ---------------------- | --------------------------------------------------- | ---------------- | -------- |
| `get_logger`           | 几乎所有模块                                              | 签名不变             | 零        |
| `configure_logging`    | cli/main.py                                         | 签名不变             | 零        |
| `MetricsCollector`     | core/orchestrator.py                                | 内部优化             | 零        |
| `get_cache_dir`        | config/snapshot.py, plugins/sqlseed-ai              | 签名不变             | 零        |
| `create_progress`      | core/orchestrator.py                                | 签名不变             | 零        |
| `detect_autoincrement` | database/\_base\_adapter.py, sqlalchemy\_adapter.py | 签名不变，逻辑修正        | 低（行为更正确） |
| `quote_identifier`     | database 层广泛使用                                      | **行为变更**（允许 `-`） | 中（需审查）   |
| `validate_table_name`  | database 层、core/schema.py                           | **行为变更**（允许 `-`） | 中（需审查）   |
| `build_insert_sql`     | database/raw\_sqlite\_adapter.py                    | 签名不变             | 零        |

**结论**：唯一行为变更在 `sql_safe.py`，需第 3 智能体专项安全审查。

## 3. 优化范围与决策

| 文件                  | 优化类型          | 破坏性     | 决策                  |
| ------------------- | ------------- | ------- | ------------------- |
| `__init__.py`       | 无需改动          | 否       | 保持现状                |
| `logger.py`         | 文档+排版         | 否       | 补 docstring + 分组注释  |
| `metrics.py`        | 逻辑+文档         | 否       | 单次遍历重构              |
| `paths.py`          | 微调文档          | 否       | 补注释                 |
| `progress.py`       | mypy 修复+文档    | 否       | 修复 `get_ipython` 类型 |
| `schema_helpers.py` | **Bug 修复**+文档 | 否（行为修正） | 括号感知分割器             |
| `sql_safe.py`       | **行为变更**+文档   | 是       | 移除 `-` + 审查         |
| `AGENTS.md`         | 文档更新          | 否       | 日期+描述同步             |

## 4. 详细方案

### 4.1 `__init__.py`

**决策**：保持现状，不调整。导出策略合理（logger/schema\_helpers 故意不导出，避免误用）。

### 4.2 `logger.py`

**问题**：

* 缺少模块级 docstring

* 缺少函数 docstring

* processors 列表无分组注释

**优化**：

* 添加模块 docstring 说明 structlog 配置策略

* 为 `configure_logging` 和 `get_logger` 添加 docstring

* processors 列表添加分组注释（时间戳 / 日志级别 / 调用方 / 格式化）

* **保留**模块级自动配置（有意为之，`import sqlseed` 即生效）

* `get_logger` 返回类型保持 `Any`（structlog 动态代理特性，强类型化收益低）

### 4.3 `metrics.py`

**问题**：

* `summary()` 遍历两次（先分组再统计）

* 缺少 docstring

* `MetricEntry.timestamp` 用 `time.monotonic()`，需说明用途

**优化**：

* 添加完整 docstring（模块/类/方法）

* `summary()` 重构为单次遍历（边分组边累计 count/sum/min/max）

* 添加 `__repr__` 便于调试

**实现代码**（用户确认）：

```python
def summary(self) -> dict[str, Any]:
    """按指标名称汇总统计：count / total / min / max / avg。"""
    if not self._entries:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for entry in self._entries:
        name = entry.name
        val = entry.value
        if name not in result:
            result[name] = {
                "count": 1,
                "total": val,
                "min": val,
                "max": val,
            }
        else:
            stats = result[name]
            stats["count"] += 1
            stats["total"] += val
            if val < stats["min"]:
                stats["min"] = val
            if val > stats["max"]:
                stats["max"] = val

    for stats in result.values():
        stats["avg"] = stats["total"] / stats["count"]

    return result
```

### 4.4 `paths.py`

**问题**：质量已较高，仅微调。

**优化**：

* 补充一行注释说明 `SQLSEED_CACHE_DIR` 优先级最高

* 其他保持不变

### 4.5 `progress.py`

**问题**：

* **mypy 错误**：`get_ipython()` 未定义，mypy strict 下报 `name-defined`

* `RichProgressBackend` / `TqdmNotebookBackend` 方法缺少 docstring

* `_detect_environment` 逻辑复杂，缺少注释

**优化**：

* 修复 `get_ipython()` 的 mypy 问题：添加 `# type: ignore[name-defined]`

* 为三个 Backend 类的公共方法补充 docstring

* `_detect_environment` 添加内联注释说明每个 shell class 的含义

* 排版：保持现有分区注释结构

### 4.6 `schema_helpers.py` ⚠️ 含 Bug 修复

**当前 Bug**：

```python
for part in sql_upper.split(","):  # 会切断 DECIMAL(10,2) / CHECK(x IN (1,2))
```

**优化方案**：用括号感知分割器替代 `split(",")`

**实现代码**（用户确认）：

```python
def _split_sql_definitions(sql: str) -> list[str]:
    """提取 CREATE TABLE 语句中最外层括号内的独立列或约束定义。

    通过括号深度感知，避免切割 DECIMAL(10,2) / CHECK(x IN (1,2)) 等
    含逗号的类型或约束。
    """
    start = sql.find("(")
    end = sql.rfind(")")
    if start == -1 or end == -1:
        return []
    content = sql[start + 1:end]

    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in content:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts
```

**调用逻辑**：

```python
col_upper = column_name.upper()
for part in _split_sql_definitions(sql_upper):
    if (
        re.search(rf"\b{re.escape(col_upper)}\b", part)
        and "INTEGER" in part
        and "PRIMARY" in part
        and "AUTOINCREMENT" in part
    ):
        return True
```

**其他优化**：

* 添加模块 docstring 说明"仅支持 SQLite"

* `execute_fn` 类型注解改为 `Callable[..., Any]`

* 添加详细注释说明解析逻辑

### 4.7 `sql_safe.py` ⚠️ 破坏性变更

**当前问题**：

1. `_DANGEROUS_CHARS_RE = re.compile(r"[;\n\r'\-]")` 中的 `-` 过度严格
2. `quote_identifier` docstring 说"Uses SQLite's double-quote escaping rules"，但项目支持多 DB
3. `validate_table_name` 用 `logger.warning("...%s...", name)`，structlog 推荐关键字参数
4. 缺少模块 docstring

**优化方案**：

* **移除** **`-`** **from** **`_DANGEROUS_CHARS_RE`** → `re.compile(r"[;\n\r']")`

  * 理由：`quote_identifier` 已用双引号包裹并转义内部双引号，`-` 在引号内安全

* 更新 docstring 反映多 DB 支持（SQLite/PG 用双引号）

* 修复 structlog 日志调用：`logger.warning("Table name contains special characters", table_name=name)`

* 添加模块 docstring 说明三层防护设计

**安全审查要点**（第 3 智能体专项）：

* 确认移除 `-` 后，SQL 注入防护仍有效

* 确认 `;` `\n` `\r` `'` 仍能阻止经典注入

* 确认双引号转义逻辑无绕过

**测试同步调整**：

* `test_sql_safe.py` 中 `test_quote_identifier_rejects_dash` → `test_quote_identifier_allows_dash`

* 断言 `"my-table"` 成功被转义为 `'"my-table"'`

### 4.8 `AGENTS.md`

**当前问题**：

1. 日期 `2026-04-29` 需更新为 `2026-06-21`
2. `progress.py` 描述"rich 进度条工厂"不准确，实际支持 3 后端
3. `schema_helpers.py` 描述"数据库模式检测共享逻辑"过于宽泛
4. Dependencies 缺少 `tqdm`
5. Common Patterns 可补充

**优化方案**：

* 更新日期为 `2026-06-21`

* 更新各文件描述使其精确

* 补充 `tqdm` 可选依赖

* 补充 Common Patterns（三后端进度条选择逻辑）

## 5. 新增测试文件

### `tests/test_utils/test_schema_helpers.py`

专门测试 `detect_autoincrement` 的复杂 CREATE TABLE SQL 变体：

* 基础：`id INTEGER PRIMARY KEY AUTOINCREMENT`

* 含逗号类型：`price DECIMAL(10,2)` + `id INTEGER PRIMARY KEY AUTOINCREMENT`

* 含 CHECK 约束：`status CHECK(status IN (1,2,3))` + autoincrement

* 不同大小写：`integer primary key autoincrement`

* 多行换行：跨行定义

* 非 autoincrement：普通 `INTEGER PRIMARY KEY`（应返回 False）

* 嵌套括号：`CHECK(x IN (SELECT y FROM t))` + autoincrement

## 6. 3 个智能体执行计划

### 智能体 A（交叉执行 1）

* 独立实现全部 7 个文件 + AGENTS.md 的优化

* 严格按本设计文档执行

* 输出：完整的文件修改

### 智能体 B（交叉执行 2）

* 独立实现同一份方案的优化

* 严格按本设计文档执行

* 输出：完整的文件修改

### 智能体 C（检查）

* 对比 A 和 B 的实现差异

* 专项审查：

  * `sql_safe.py` 移除 `-` 后的安全性

  * `schema_helpers.py` 括号感知分割器的正确性

  * 两个实现的一致性差异

* 输出：最终合并版本 + 审查报告

### 整合与验证

* 我整合智能体 C 的结果，应用修改

* 运行验证：

  * `ruff check src/sqlseed/_utils/`

  * `ruff format --check src/sqlseed/_utils/`

  * `mypy src/sqlseed/_utils/`

  * `pytest tests/test_utils/`

## 7. 验收标准

1. 所有 7 个文件 + AGENTS.md 按方案优化完成
2. `ruff check` 无错误
3. `ruff format --check` 无差异
4. `mypy` 无错误（特别是 `progress.py` 的 `get_ipython` 修复）
5. `pytest tests/test_utils/` 全部通过
6. 新增 `test_schema_helpers.py` 覆盖复杂 SQL 变体
7. `test_sql_safe.py` 中 dash 测试已调整
8. `sql_safe.py` 移除 `-` 经第 3 智能体安全审查通过

## 8. 不做的事（YAGNI）

* 不改 `__init__.py` 导出策略

* 不改 `logger.py` 为延迟初始化

* 不强类型化 `get_logger` 返回值

* 不改公共 API 签名（除 `sql_safe.py` 行为变更外）

* 不重构 `progress.py` 的三后端架构

* 不扩展 `schema_helpers.py` 支持多 DB（仅修复 SQLite 解析 Bug）

