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
2. 所有公共函数需要仅关键字参数（使用 `*` 分隔符）。`generate_choice(choices)` 是唯一例外（`choices` 是位置参数）。
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
├── transform: str | None  (Python 脚本路径)
└── enrich: bool = False

ColumnConfig (列级，支持两种互斥模式)
├── 源列模式: generator + params + null_ratio + provider
├── 派生列模式: derive_from + expression
└── constraints: ColumnConstraintsConfig | None
    ├── unique: bool
    ├── min_value / max_value
    ├── regex: str | None
    └── max_retries: int = 100
ColumnAssociation (跨表关联)
├── column_name: str
├── source_table: str
├── source_column: str | None = None  (源表列名，默认等于 column_name)
├── target_tables: list[str]
└── strategy: str = "shared_pool"
```

**模式互斥验证**：`derive_from` 和 `generator` 不可同时使用（Pydantic `model_validator`）。

### 核心编排架构

编排器使用两个 dataclass 组织内部状态：

```python
@dataclass
class CoreCtx:
    db: DatabaseAdapter | None
    schema: SchemaInferrer | None
    mapper: ColumnMapper
    relation: RelationResolver | None
    shared_pool: SharedPool

@dataclass
class ExtCtx:
    registry: ProviderRegistry
    plugins: PluginManager
    plugin_mediator: PluginMediator | None
    enrichment: EnrichmentEngine | None
    unique_adjuster: UniqueAdjuster | None
    metrics: MetricsCollector
```

`DataOrchestrator.__init__` 在构造时即创建 `CoreCtx` 和 `ExtCtx`，包括 DB 适配器和 `SchemaInferrer`。延迟连接在 `_ensure_connected()` 中完成。

### 核心编排流程

`DataOrchestrator.fill_table()` 是主入口，执行链路：

```
1.  _ensure_connected()         → 连接数据库、加载插件、注册 Provider、创建 PluginMediator
2.  optimize_for_bulk_write()   → 三级 PRAGMA 优化（如果 optimize_pragma=True）
3.  clear_table()               → 如果 clear_before=True，清空表
4.  _resolve_specs()            → 合并 Schema 推断 + 用户配置 + 映射 + 唯一性 + FK 解析
    4a. get_column_info()       → 推断 Schema
    4b. _resolve_user_configs() → 合并用户 ColumnConfig 配置
    4c. map_columns()           → 9 级策略链映射
    4d. detect_unique_columns() → 检测唯一列
    4e. EnrichmentEngine.apply() → [enrich=True] 数据分布推断
    4f. UniqueAdjuster.adjust() → 唯一列参数调整
    4g. resolve_foreign_keys()  → FK 解析 + SharedPool 隐式关联
    4h. apply_associations()    → [有 associations 配置时] 显式跨表关联（使用 source_column 查源表列）
5.  apply_ai_suggestions()      → AI Hook 分析（通过 PluginMediator）
6.  apply_template_pool()       → AI 预计算模板池（通过 PluginMediator）
7.  _build_stream()             → 创建 ColumnDAG、ExpressionEngine、ConstraintSolver、加载 Transform
8.  sqlseed_before_generate Hook
9.  DataStream.generate()       → 逐批 yield 数据
10. 每批：before_insert → apply_batch_transforms → batch_insert → after_insert
11. sqlseed_after_generate Hook
12. register_shared_pool()      → 注册值到 SharedPool（非 skip 列 + 自增主键列）
13. sqlseed_shared_pool_loaded Hook
14. restore_settings()          → [finally] 恢复 PRAGMA 设置
```

**注意**：`preview_table()` 不调用 AI 建议和模板池（步骤 5-6），不调用 before_generate/after_generate Hook，但**会**调用 `apply_batch_transforms()`。

### DataProvider Protocol

`DataProvider` Protocol 定义了统一的生成接口：

```python
@runtime_checkable
class DataProvider(Protocol):
    @property
    def name(self) -> str: ...
    def set_locale(self, locale: str) -> None: ...
    def set_seed(self, seed: int) -> None: ...
    def generate(self, type_name: str, **params: Any) -> Any: ...
```

`generate()` 方法通过 `GeneratorDispatchMixin._GENERATOR_MAP` 分派到 24 个内部方法：

`string`、`integer`、`float`、`boolean`、`bytes`、`name`、`first_name`、`last_name`、
`email`、`phone`、`address`、`company`、`url`、`ipv4`、`uuid`、`date`、
`datetime`、`timestamp`、`text`、`sentence`、`password`、`choice`、`json`、`pattern`

未知 `type_name` 会抛出 `UnknownGeneratorError`（定义在 `generators/_protocol.py`）。

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
| `sqlseed_ai_analyze_table(...)` | ✓ | `apply_ai_suggestions()` |
| `sqlseed_before_generate(table_name, count, config)` | ✗ | `fill_table()` 主循环前 |
| `sqlseed_after_generate(table_name, count, elapsed)` | ✗ | `fill_table()` 完成后 |
| `sqlseed_transform_row(table_name, row)` | ✗ | （定义在 hookspecs，热路径） |
| `sqlseed_transform_batch(table_name, batch)` | ✗ | `apply_batch_transforms()` |
| `sqlseed_before_insert(table_name, batch_number, batch_size)` | ✗ | 每批写入前 |
| `sqlseed_after_insert(table_name, batch_number, rows_inserted)` | ✗ | 每批写入后 |
| `sqlseed_shared_pool_loaded(table_name, shared_pool)` | ✗ | `register_shared_pool()` 后 |
| `sqlseed_pre_generate_templates(...)` | ✓ | `apply_template_pool()` |

### ColumnMapper 9 级策略链

| 优先级 | 级别 | 规则数量 | 说明 |
|--------|------|----------|------|
| 1 | 自增主键 | — | PK + 自增/INTEGER → `skip` |
| 2 | 用户配置 | — | `ColumnConfig.generator` + params |
| 3 | 自定义精确匹配 | 动态 | `register_exact_rule()` 注册 |
| 4 | 内置精确匹配 | 68 规则 | `EXACT_MATCH_RULES` + `EXACT_MATCH_PARAMS`（28 预设） |
| 5 | DEFAULT 检查 | — | `default is not None` → `skip`/`__enrich__` |
| 6 | 自定义模式匹配 | 动态 | `register_pattern_rule()` 注册 |
| 7 | 内置模式匹配 | 25 正则 | `PATTERN_MATCH_RULES` |
| 8 | NULLABLE 回退 | — | `nullable` → `skip`/`__enrich__` |
| 9 | 类型忠实回退 | 22 类型 | `TYPE_FALLBACK_RULES`，解析 `VARCHAR(32)` 等括号参数 |

### 测试结构

```
tests/
├── conftest.py               → 公共 fixtures（tmp_db, tmp_db_with_data, bank_cards_db, card_info_db 辅助）
├── test_public_api.py        → fill/connect/preview/fill_from_config
├── test_orchestrator.py      → DataOrchestrator 集成测试
├── test_mapper.py            → ColumnMapper 映射逻辑
├── test_relation.py          → RelationResolver + SharedPool
├── test_schema.py            → SchemaInferrer + profile
├── test_result.py            → GenerationResult
├── test_cli.py               → CLI 命令（CliRunner）
├── test_ai_plugin.py         → AI 插件集成（importorskip）
├── test_refiner.py           → AiConfigRefiner 自纠正
├── test_enrich_enum_detection.py → 枚举列检测独立测试
├── test_core/
│   ├── test_expression.py    → ExpressionEngine + timeout
│   ├── test_constraints.py   → ConstraintSolver + RegisterResult
│   ├── test_column_dag.py    → ColumnDAG 拓扑排序
│   ├── test_transform.py     → Transform 脚本加载
│   ├── test_enrichment.py    → EnrichmentEngine
│   ├── test_unique_adjuster.py → UniqueAdjuster
│   └── test_plugin_mediator.py → PluginMediator
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
├── test_utils/               → _utils 模块测试
└── benchmarks/               → 性能基准测试
```

### 测试模式

- **Fixtures**：公共 fixtures 在 `tests/conftest.py`（`tmp_db` 创建含 users/orders 两表的数据库，`bank_cards_db` 用于 DAG/约束场景，`create_card_info_db()` 辅助函数用于多索引测试）
- **适配器**：使用真实 SQLite 数据库测试（临时文件路径 via `tmp_path`）
- **CLI**：使用 `click.testing.CliRunner` — 禁止使用 subprocess
- **Provider**：通过统一 `generate(type_name, **params)` 接口测试各类型
- **插件**：通过 `PluginManager` 测试 Hook 注册和调用
- **AI 测试**：需要 `sqlseed-ai` 插件的测试使用 `pytest.importorskip("sqlseed_ai")`
- **基准测试**：使用 `pytest-benchmark`，位于 `tests/benchmarks/`

### 关键实现细节

- `DataOrchestrator.fill()` 是 `fill_table()` 的别名。`fill_table()` 是完整实现。
- `DataOrchestrator` 在 `__init__` 中使用 `CoreCtx` 和 `ExtCtx` dataclass 组织状态。`CoreCtx` 持有 DB 适配器、Schema 推断器、列映射器、关系解析器和共享池。`ExtCtx` 持有 Provider 注册表、插件管理器、中介器、增强引擎和指标收集器。
- `DataOrchestrator.__init__` 接受 `associations: list[Any] | None = None` 参数，构造时传递给 `RelationResolver.set_associations()`。`from_config()` 会自动从 `GeneratorConfig.associations` 传入。
- `DataOrchestrator._create_adapter()` 检测 `sqlite-utils` 是否可用（通过 `database/_compat.py` 的 `HAS_SQLITE_UTILS`），不可用则回退到 `RawSQLiteAdapter`。
- `transform_batch` Hook 返回 `list[result]`（非 firstresult）。编排器通过 `PluginMediator.apply_batch_transforms()` 链式处理——遍历结果列表，最后一个非 None 的结果胜出。
- `DataStream` 使用自己的 `random.Random(seed)` 实例处理 `null_ratio`/`choice` 操作，与 Provider 的 RNG 分离。
- `PragmaOptimizer.restore()` 在应用 PRAGMA 值前用正则 `^[a-zA-Z0-9_-]+$` 验证（防 SQL 注入），同时支持 `int`/`float` 类型值的直接写入。
- `_is_autoincrement` 检测集中在 `_utils/schema_helpers.py`，通过解析 `sqlite_master` 的 CREATE TABLE SQL 实现。
- `ExpressionEngine.evaluate()` 对每次调用创建独立的 `simpleeval.SimpleEval()` 实例，避免竞态条件。超时机制使用独立线程（默认 5 秒），通过 `ExpressionTimeoutError`（继承自 `TimeoutError`）报告。**注意**：线程超时后无法被强制终止，超时线程仍在后台运行。
- `ExpressionEngine.SAFE_FUNCTIONS` 白名单包括 21 个函数：`len`、`int`、`str`、`float`、`hex`、`oct`、`bin`、`abs`、`min`、`max`、`upper`、`lower`、`strip`、`lstrip`、`rstrip`、`zfill`、`replace`、`substr`、`lpad`、`rpad`、`concat`。
- `relation.py` 中的 `SharedPool` 维护跨表值池以保持 FK 引用完整性。`merge()` 方法使用 `set()` 进行去重追加，对不可哈希值（如 `dict`/`list`）通过 `try/except TypeError` 回退到线性扫描。
- `DatabaseAdapter` Protocol 包含 `IndexInfo`、`get_index_info()` 和 `get_sample_rows()`。两个实现：`SQLiteUtilsAdapter`（默认）和 `RawSQLiteAdapter`（回退）。
- 插件系统有 11 个 Hook。`sqlseed_ai_analyze_table` 和 `sqlseed_pre_generate_templates` 是 `firstresult`。
- CLI `fill` 命令使用 `--config` 时 `db_path` 为可选（`required=False`）。
- CLI `fill` 命令在非 `--config` 模式下 `--count` 为必填参数；使用 `--config` 时 count 来自配置文件。
- CLI 默认日志级别为 `WARNING`，通过环境变量 `SQLSEED_LOG_LEVEL` 控制（如 `SQLSEED_LOG_LEVEL=DEBUG`）。
- AI 插件默认模型为 `None`（自动选择），通过 `_model_selector.select_best_free_model()` 动态获取 OpenRouter 最受欢迎的免费模型。默认 base_url 为 `https://openrouter.ai/api/v1`。可通过 `AIConfig`、环境变量 `SQLSEED_AI_MODEL` / `SQLSEED_AI_API_KEY` / `SQLSEED_AI_BASE_URL` / `SQLSEED_AI_TIMEOUT`（也支持 `OPENAI_API_KEY` / `OPENAI_BASE_URL`）或 CLI `--model`/`--api-key`/`--base-url` 配置。用户显式指定 `--model` 或 `SQLSEED_AI_MODEL` 时跳过自动选择。`AIConfig.resolve_model()` 在首次需要模型时调用，结果缓存 1 小时。`call_llm()` 实现超时回退：OpenAI 客户端 timeout 默认 60 秒，`APITimeoutError`/`APIConnectionError` 时自动回退到优先级列表中的下一个模型（最多 3 个），其他错误不回退。
- `AI_APPLICABLE_GENERATORS` 为 `frozenset({"string", "integer", "date", "datetime", "choice"})`，只有这些类型的列会触发 AI 分析。
- `ProviderRegistry.ensure_provider()` 按需惰性导入 Faker/Mimesis，失败时回退到 `base`。
- `DataStream._generate_row()` 支持全行级重试（最多 1000 次），约束回溯时通过 `_find_node_index()` 定位源列在 DAG 中的位置。
- `UnknownGeneratorError` 在 `generators/_protocol.py` 中定义；`DataStream._apply_generator()` 只对 `choice` 和 `foreign_key` 做本地兜底，其余未知生成器会继续抛出该异常。
- `SnapshotManager` 默认保存到 `./snapshots/`，文件名格式 `{timestamp}_{table_name}.yaml`，时间戳格式为 `%Y-%m-%d_%H%M%S`。
- `SchemaInferrer.profile_column_distribution()` 提取列分布画像（null_ratio、distinct_count、top_values、value_range），注入 AI 上下文。
- MCP 服务器 `_compute_schema_hash()` 使用 SHA256 前 16 字符作为 schema 指纹。
- `resolve_implicit_associations()` 检查 SharedPool 中是否存在同名列值，实现无 FK 约束的隐式跨表关联。仅对 `foreign_key_or_integer` 类型的 spec 进行隐式关联。
- `generate_pattern(*, regex)` 使用 `rstr` 库（核心依赖）从正则表达式生成匹配字符串，在 `BaseProvider._gen_pattern()` 中创建局部 `rstr.Rstr(self._rng)` 实例。
- `ConstraintSolver._is_seen()` 仅检查值是否存在，**不会隐式注册**。`check_and_register()` 先调用 `_is_seen()`，再显式调 `_register()`。两者是独立操作。
- `ConstraintSolver.check_and_register()` 对 `value=None` 直接返回 `True`（跳过注册），与 `try_register()` 行为一致。
- `ConstraintSolver` 支持 `probabilistic=True` 模式，使用 SHA256 hash-based 去重降低内存占用（适用于 >100K 行），以及 `check_and_register_composite()` 复合唯一约束。
- `register_shared_pool()` 在 `fill_table()` 完成后调用，遍历所有非 `skip` 的列以及自增主键列（`skip` + PK），从数据库查询值（`limit=10000`）并合并到 `SharedPool`。自增主键的值也会被注册，以便其他表的 FK 引用可以找到这些值。
- `BaseProvider.FIRST_NAMES` 和 `LAST_NAMES` 各含 60 个条目，`generate_name()`、`generate_first_name()`、`generate_last_name()` 均使用同一组列表。
- `GeneratorDispatchMixin._GENERATOR_MAP` 包含 24 个生成器类型到内部方法的映射。

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
`pytest>=8.0`、`pytest-cov>=5.0`、`pytest-asyncio>=0.24`、`pytest-benchmark>=4.0`、`ruff>=0.5`、`mypy>=1.10`、`pre-commit>=3.0`

**文档依赖**：
`mkdocs-material>=9.0`、`mkdocstrings[python]>=0.25`

## 文件模板

### 新 Provider 模板

```python
from __future__ import annotations
from typing import Any

from sqlseed.generators._dispatch import GeneratorDispatchMixin


class NewProvider(GeneratorDispatchMixin):
    def __init__(self) -> None:
        self._locale: str = "en_US"

    @property
    def name(self) -> str:
        return "new_provider"

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def set_seed(self, seed: int) -> None:
        ...

    # 实现 _gen_* 方法（对应 _GENERATOR_MAP 中的 24 种类型）
    # generate() 方法由 GeneratorDispatchMixin 提供
    # 参见：src/sqlseed/generators/base_provider.py
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
12. **entry-points 注册**：Provider 通过 `pyproject.toml` 的 `[project.entry-points."sqlseed"]` 自动发现，`register_from_entry_points()` 在 `_ensure_connected()` 中调用。非 provider 入口点（如 `sqlseed_ai:plugin`）会被静默跳过，不产生 warning
13. **`apply_batch_transforms` 链式语义**：遍历所有 Hook 返回的结果列表，最后一个非 `None` 的结果覆盖 —— 不是累积合并
14. **选择生成器的 `_rng`**：`DataStream._apply_generator()` 中 `choice` 和 `foreign_key` 用流自身的 `self._rng`，而非 Provider 的 RNG
15. **`generate_pattern` 依赖**：`rstr` 是核心依赖，`BaseProvider._gen_pattern()` 内部创建局部 `rstr.Rstr(self._rng)` 实例
16. **SharedPool Hook**：`sqlseed_shared_pool_loaded` 会在 `register_shared_pool()` 后触发，修改 payload 或调用时机时要同步检查插件测试
17. **Transform ctx 语义**：`DataStream` 传给 `transform_fn` 的 `ctx` 同时包含 `row_number` 和 `retry_count`，不要把两者混为一谈
18. **Provider 接口变更**：Provider 不再暴露独立的 `generate_string()`、`generate_integer()` 等方法，统一使用 `generate(type_name, **params)` → 内部分派到 `_gen_*` 方法
19. **sqlite-utils 可选性**：`database/_compat.py` 控制 `HAS_SQLITE_UTILS` 标志，编排器根据此标志选择适配器。不要在核心路径中直接 `import sqlite_utils`

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

# 性能基准测试
pytest tests/benchmarks/ --benchmark-only
```
