# CLAUDE.md — sqlseed Claude 专用指令

本文件为 Claude（Anthropic）在 sqlseed 代码库中工作提供专用指令，补充 `AGENTS.md` 中的通用指令。

## 项目背景

sqlseed 是一个 Python 3.10+ 声明式 SQLite 测试数据生成工具包，使用 `src` 布局（`src/sqlseed/`）。构建后端为 `hatch`（`hatchling`），版本通过 VCS 管理（`hatch-vcs`）。`AGENTS.md` 包含完整的架构说明和设计决策。

许可证：AGPL-3.0-or-later。

## 如何参与本项目

### 修改前

1. 阅读 `AGENTS.md` 了解通用规范和架构
2. 检查 `tests/` 中的现有测试，了解测试模式
3. 修改前运行 `pytest` 验证基线

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

**禁止方向**：`generators` → `core`、`database` → `core`、`_utils` → 任何上层。

### 公共 API 表面

`src/sqlseed/__init__.py` 导出以下公共接口：

| API | 用途 |
|-----|------|
| `sqlseed.fill(db_path, *, table, count, ...)` | 单表零配置填充 |
| `sqlseed.connect(db_path, *, ...)` | 返回 `DataOrchestrator` 上下文管理器 |
| `sqlseed.preview(db_path, *, table, count, ...)` | 预览生成数据，不写入 |
| `sqlseed.fill_from_config(config_path)` | 从 YAML/JSON 配置批量填充 |
| `sqlseed.load_config(path)` | 加载配置文件为 `GeneratorConfig` |

导出的类型：`ColumnConfig`、`TableConfig`、`GeneratorConfig`、`ProviderType`、`DataOrchestrator`、`GenerationResult`。

### 配置模型层次结构

```
GeneratorConfig (全局)
├── db_path: str
├── provider: ProviderType  (base|faker|mimesis|custom|ai)
├── locale: str = "en_US"
├── tables: list[TableConfig]
├── associations: list[ColumnAssociation]  (跨表隐式关联)
├── optimize_pragma: bool = True
├── log_level: str = "INFO"
└── snapshot_dir: str | None

TableConfig (单表)
├── name: str
├── count: int = 1000
├── batch_size: int = 5000
├── columns: list[ColumnConfig]
├── clear_before: bool = False
├── seed: int | None
└── transform: str | None  (Python 脚本路径)

ColumnConfig (列级，支持两种互斥模式)
├── 源列模式: generator + params + null_ratio + provider
├── 派生列模式: derive_from + expression
└── constraints: ColumnConstraintsConfig | None
    ├── unique: bool
    ├── min_value / max_value
    ├── regex: str | None
    └── max_retries: int = 100
```

**模式互斥验证**：`derive_from` 和 `generator` 不可同时使用（Pydantic `model_validator`）。

### 核心编排流程

`DataOrchestrator.fill_table()` 是主入口，执行链路：

```
1. _ensure_connected()  → 连接数据库、加载插件、注册 Provider
2. optimize_for_bulk_write()  → 三级 PRAGMA 优化
3. SchemaInferrer.get_column_info()  → 推断 Schema
4. _resolve_user_configs()  → 合并用户 ColumnConfig 配置
5. ColumnMapper.map_columns()  → 8 级策略链映射
6. _resolve_foreign_keys()  → FK 解析 + SharedPool 隐式关联
7. _apply_ai_suggestions()  → AI Hook 分析（可选）
8. _apply_template_pool()  → AI 预计算模板池（可选）
9. ColumnDAG.build()  → 拓扑排序列依赖
10. DataStream.generate()  → 逐批 yield 数据
11. _apply_batch_transforms()  → 链式插件变换
12. batch_insert()  → 批量写入数据库
13. _register_shared_pool()  → 注册值到 SharedPool
```

### DataProvider Protocol 方法完整列表

`generate_string`、`generate_integer`、`generate_float`、`generate_boolean`、
`generate_bytes`、`generate_name`、`generate_first_name`、`generate_last_name`、
`generate_email`、`generate_phone`、`generate_address`、`generate_company`、
`generate_url`、`generate_ipv4`、`generate_uuid`、`generate_date`、
`generate_datetime`、`generate_timestamp`、`generate_text`、`generate_sentence`、
`generate_password`、`generate_choice`、`generate_json`、`generate_pattern`

另有：`name`（property）、`set_locale()`、`set_seed()`。

### DatabaseAdapter Protocol 方法完整列表

`connect`、`close`、`get_table_names`、`get_column_info`、`get_primary_keys`、
`get_foreign_keys`、`get_row_count`、`get_column_values`、`get_index_info`、
`get_sample_rows`、`batch_insert`、`clear_table`、`optimize_for_bulk_write`、
`restore_settings`、`__enter__`、`__exit__`

数据类：`ColumnInfo`、`ForeignKeyInfo`、`IndexInfo`（均为 `frozen` dataclass）。

### 插件 Hook 完整列表（11 个）

| Hook | firstresult | 调用位置 |
|------|-------------|----------|
| `sqlseed_register_providers(registry)` | ✗ | `_ensure_connected()` |
| `sqlseed_register_column_mappers(mapper)` | ✗ | `_ensure_connected()` |
| `sqlseed_ai_analyze_table(...)` | ✓ | `_apply_ai_suggestions()` |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | `fill_table()` 主循环前 |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | `fill_table()` 完成后 |
| `sqlseed_transform_row(table_name, row)` | ✗ | （定义在 hookspecs，热路径） |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `_apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | 每批写入前 |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | 每批写入后 |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | 表值池注册后 |
| `sqlseed_pre_generate_templates(...)` | ✓ | `_apply_template_pool()` |

### 测试结构

```
tests/
├── conftest.py               → 公共 fixtures（tmp_db, tmp_db_with_data, bank_cards_db）
├── test_public_api.py        → fill/connect/preview/fill_from_config
├── test_orchestrator.py      → DataOrchestrator 集成测试
├── test_mapper.py            → ColumnMapper 映射逻辑
├── test_relation.py          → RelationResolver + SharedPool
├── test_schema.py            → SchemaInferrer + profile
├── test_result.py            → GenerationResult
├── test_cli.py               → CLI 命令（CliRunner）
├── test_ai_plugin.py         → AI 插件集成（importorskip）
├── test_refiner.py           → AiConfigRefiner 自纠正
├── test_core/
│   └── test_expression.py    → ExpressionEngine + timeout
├── test_config/
│   ├── test_loader.py        → YAML/JSON 加载
│   ├── test_models.py        → Pydantic 模型验证
│   └── test_snapshot.py      → SnapshotManager
├── test_database/
│   ├── test_optimizer.py     → PragmaOptimizer
│   ├── test_raw_sqlite_adapter.py
│   ├── test_sqlite_utils_adapter.py
│   └── test_sql_safe.py      → quote_identifier 等
├── test_generators/
│   ├── test_base_provider.py
│   ├── test_faker_provider.py
│   ├── test_mimesis_provider.py
│   ├── test_registry.py     → ProviderRegistry
│   └── test_stream.py       → DataStream + 回溯
├── test_plugins/
│   ├── test_hookspecs.py    → Hook 定义和调用
│   └── test_manager.py      → PluginManager
└── test_utils/               → _utils 模块测试
```

### 测试模式

- **Fixtures**：公共 fixtures 在 `tests/conftest.py`（`tmp_db` 创建含 users/orders 两表的数据库，`bank_cards_db` 用于 DAG/约束场景）
- **适配器**：使用真实 SQLite 数据库测试（临时文件路径 via `tmp_path`）
- **CLI**：使用 `click.testing.CliRunner` — 禁止使用 subprocess
- **Provider**：独立测试每个 `generate_*` 方法
- **插件**：通过 `PluginManager` 测试 Hook 注册和调用
- **AI 测试**：需要 `sqlseed-ai` 插件的测试使用 `pytest.importorskip("sqlseed_ai")`

### 关键实现细节

- `DataOrchestrator.fill()` 是 `fill_table()` 的别名。`fill_table()` 是完整实现。
- `transform_batch` Hook 返回 `list[result]`（非 firstresult）。编排器通过 `_apply_batch_transforms()` 链式处理——遍历结果列表，最后一个非 None 的结果胜出。
- `DataStream` 使用自己的 `random.Random(seed)` 实例处理 `null_ratio`/`choice` 操作，与 Provider 的 RNG 分离。
- `PragmaOptimizer.restore()` 在应用 PRAGMA 值前用正则 `^[a-zA-Z0-9_-]+$` 验证（防 SQL 注入）。
- `_is_autoincrement` 检测集中在 `_utils/schema_helpers.py`，通过解析 `sqlite_master` 的 CREATE TABLE SQL 实现。
- `ExpressionEngine` 具有基于线程的超时机制（默认 5 秒），通过 `ExpressionTimeoutError`（继承自 `TimeoutError`）报告。
- `ExpressionEngine.SAFE_FUNCTIONS` 白名单包括：`len`、`int`、`str`、`float`、`hex`、`oct`、`bin`、`abs`、`min`、`max`、`upper`、`lower`、`strip`、`lstrip`、`rstrip`、`zfill`、`replace`、`substr`、`lpad`、`rpad`、`concat`。
- `relation.py` 中的 `SharedPool` 维护跨表值池以保持 FK 引用完整性。`merge()` 方法去重追加值。
- `DatabaseAdapter` Protocol 包含 `IndexInfo`、`get_index_info()` 和 `get_sample_rows()`。两个实现：`SQLiteUtilsAdapter`（默认）和 `RawSQLiteAdapter`（回退）。
- 插件系统有 11 个 Hook。`sqlseed_ai_analyze_table` 和 `sqlseed_pre_generate_templates` 是 `firstresult`。
- CLI `fill` 命令使用 `--config` 时 `db_path` 为可选（`required=False`）。
- AI 插件默认模型为 `qwen3-coder-plus`，可通过 `AIConfig` 、环境变量 `SQLSEED_AI_MODEL` / `SQLSEED_AI_API_KEY` / `SQLSEED_AI_BASE_URL` 或 CLI `--model`/`--api-key`/`--base-url` 配置。
- `ColumnMapper` 8 级链：用户配置 > 自定义精确匹配 > 内置精确匹配（67 条规则）> 自定义模式匹配 > 内置模式匹配（25 条正则）> 跳过（DEFAULT/NULL） > 类型忠实回退（22 种 SQL 类型）> 默认（`string`）。
- `AI_APPLICABLE_GENERATORS` 为 `frozenset({"string", "integer", "date", "datetime", "choice"})`，只有这些类型的列会触发 AI 分析。
- `ProviderRegistry.ensure_provider()` 按需惰性导入 Faker/Mimesis，失败时回退到 `base`。
- `DataStream._generate_row()` 支持全行级重试（最多 1000 次），约束回溯时通过 `_find_node_index()` 定位源列在 DAG 中的位置。
- `UnknownGeneratorError` 在 `generators/stream.py` 中定义，替代字符串匹配进行异常处理。
- `SnapshotManager` 默认保存到 `./snapshots/`，文件名格式 `{timestamp}_{table_name}.yaml`。
- `SchemaInferrer.profile_column_distribution()` 提取列分布画像（null_ratio、distinct_count、top_values、value_range），注入 AI 上下文。
- MCP 服务器 `_compute_schema_hash()` 使用 SHA256 前 16 字符作为 schema 指纹。
- `_resolve_implicit_associations()` 检查 SharedPool 中是否存在同名列值，实现无 FK 约束的隐式跨表关联。
- `generate_pattern(*, regex)` 使用 `rstr` 库（依赖项）从正则表达式生成匹配字符串。

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

### 依赖关系

**核心依赖**（始终安装）：
`sqlite-utils>=3.36`、`pydantic>=2.0`、`pluggy>=1.3`、`structlog>=24.0`、`pyyaml>=6.0`、`click>=8.0`、`rich>=13.0`、`typing_extensions>=4.0`、`simpleeval>=1.0`、`rstr>=3.2`

**可选依赖**：
- `faker>=30.0`（`pip install sqlseed[faker]`）
- `mimesis>=18.0`（`pip install sqlseed[mimesis]`）

**开发依赖**：
`pytest>=8.0`、`pytest-cov>=5.0`、`pytest-asyncio>=0.24`、`ruff>=0.5`、`mypy>=1.10`、`pre-commit>=3.0`

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

    # 实现 DataProvider Protocol 的所有 generate_* 方法
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

### 新 Hook 实现模板

```python
from __future__ import annotations
from typing import Any

from sqlseed.plugins.hookspecs import hookimpl

class MyPlugin:
    @hookimpl
    def sqlseed_before_generate(
        self,
        table_name: str,
        count: int,
        config: Any,
    ) -> None:
        ...
```

## 常见陷阱

1. **种子处理**：不要在编排器中设置 Provider 种子 — `DataStream.__init__` 负责处理（`self._provider.set_seed(seed)` 仅在 `seed is not None` 时调用）
2. **Hook 返回值**：`pluggy` 对非 `firstresult` Hook 返回 `list[result]`，不是单个值
3. **sqlite-utils API**：`table.columns_dict` 返回 `{name: type}`，type 可能是 Python 类型类，不是字符串
4. **Mimesis 地区**：使用短代码（`"en"`、`"zh"`）而非 Faker 风格（`"en_US"`、`"zh_CN"`）— 参见 `MimesisProvider.set_locale()` 映射
5. **内存**：永远不要在写入前收集所有行 — 使用 `DataStream.generate()` 的 `Iterator[list[dict]]` 逐批 yield
6. **表达式超时**：使用 `ExpressionEngine.evaluate()` 时始终处理 `ExpressionTimeoutError`
7. **AI 插件测试**：需要可选 `sqlseed-ai` 依赖的测试使用 `pytest.importorskip("sqlseed_ai")`
8. **约束回溯**：`ConstraintSolver.try_register()` 返回 `RegisterResult`，当派生列 UNIQUE 约束失败时回溯到源列重新生成
9. **缓存校验**：`AiConfigRefiner` 的文件缓存包含 schema hash，schema 变更时自动失效
10. **Provider 回退**：`_ensure_connected()` 中 Provider 加载失败会静默回退到 `"base"`，不会抛异常
11. **PRAGMA 恢复**：`restore_settings()` 必须在 `finally` 块中调用，否则数据库可能处于不安全状态
12. **entry-points 注册**：Provider 通过 `pyproject.toml` 的 `[project.entry-points."sqlseed"]` 自动发现，`register_from_entry_points()` 在 `_ensure_connected()` 中调用
13. **`_apply_batch_transforms` 链式语义**：遍历所有 Hook 返回的结果列表，最后一个非 `None` 的结果覆盖 —— 不是累积合并
14. **选择生成器的 `_rng`**：`DataStream._apply_generator()` 中 `choice` 和 `foreign_key` 用流自身的 `self._rng`，而非 Provider 的 RNG
15. **`generate_pattern` 依赖**：`rstr` 是核心依赖，`BaseProvider.generate_pattern()` 内部按需导入

## 常用命令

```bash
# 运行全部测试（含覆盖率报告）
pytest

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

# 类型检查
mypy src/sqlseed/

# 开发模式安装
pip install -e ".[dev,all]"

# 安装 AI 插件
pip install -e "./plugins/sqlseed-ai"

# 安装 MCP 服务器
pip install -e "./plugins/mcp-server-sqlseed"
```
