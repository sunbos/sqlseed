# AGENTS.md — tests

## 作用域

- 本目录拥有整个 pytest 测试套件、共享 fixtures，以及少量性能基准。

## 布局规则

- 顶层 `test_*.py` 主要覆盖公共 API、CLI 和跨模块集成行为。
- `test_core/`、`test_generators/`、`test_database/`、`test_plugins/`、`test_config/`、`test_utils/` 对应主包的局部单测。
- `benchmarks/` 是性能基准，不是默认正确性断言入口。

## 文件清单与测试数量

### 顶层测试

| 文件 | 测试类数 | 测试函数数 | 覆盖范围 |
|------|----------|-----------|----------|
| `test_public_api.py` | 1 | 10 | fill/connect/preview/fill_from_config |
| `test_orchestrator.py` | 4 | 34 | DataOrchestrator 集成（Basic/Plugins/Unique/Enrichment） |
| `test_mapper.py` | 1 | 16 | ColumnMapper 映射逻辑 |
| `test_relation.py` | 4 | 35 | RelationResolver + SharedPool + ColumnAssociation |
| `test_schema.py` | 1 | 11 | SchemaInferrer + profile |
| `test_result.py` | 1 | 4 | GenerationResult |
| `test_cli.py` | 7 | 19 | CLI 命令（Fill/Preview/Inspect/Init/Replay/Main/AISuggest） |
| `test_ai_plugin.py` | 3 | 18 | AI 插件集成（importorskip） |
| `test_refiner.py` | 3 | 14 | AiConfigRefiner 自纠正 |
| `test_enrich_enum_detection.py` | 2 | 18 | 枚举列检测独立测试 |

### 子目录测试

| 目录 | 文件数 | 测试函数数 | 覆盖范围 |
|------|--------|-----------|----------|
| `test_core/` | 7 | 60 | column_dag/constraints/expression/enrichment/plugin_mediator/transform/unique_adjuster |
| `test_generators/` | 5 | 80+ | base/faker/mimesis provider + registry + stream（含 _mixin.py 复用） |
| `test_database/` | 4 | 44 | optimizer/raw_sqlite_adapter/sql_safe/sqlite_utils_adapter |
| `test_plugins/` | 2 | 20 | hookspecs/manager |
| `test_config/` | 3 | 23 | loader/models/snapshot |
| `test_utils/` | 1 | 6 | metrics |
| `benchmarks/` | 1 | 3 | fill 1K/10K + preview 5 行 |

**总计**：约 38 个测试类，约 480+ 个测试函数。

## 共享 Fixtures（conftest.py）

| Fixture | 作用域 | 说明 |
|---------|--------|------|
| `_gc_between_tests` | `autouse=True` | 每个测试前后强制 `gc.collect()`，防止 SQLite 连接泄漏 |
| `tmp_db` | 普通 | 创建含 `users` + `orders` 两表的临时 SQLite 数据库 |
| `tmp_db_with_data` | 普通 | 在 `tmp_db` 基础上插入 10 条 users 数据 |
| `bank_cards_db` | 普通 | 创建含 `bank_cards` 表 + 2 个 UNIQUE INDEX 的数据库 |
| `raw_adapter` | 普通 | 创建并连接 `RawSQLiteAdapter`，yield 后自动关闭 |
| `raw_adapter_with_data` | 普通 | 创建并连接带数据的 `RawSQLiteAdapter` |

## 辅助函数

| 函数 | 位置 | 说明 |
|------|------|------|
| `make_col(name, col_type, nullable, default, is_pk, is_auto)` | `conftest.py` | 动态创建模拟 ColumnInfo 对象 |
| `create_simple_db(db_path, table_ddl)` | `conftest.py` | 用指定 DDL 创建简单数据库 |
| `apply_enrichment(db_path, table_name, provider_name)` | `conftest.py` | 创建编排器执行 enrichment |
| `create_card_info_db(db_path, ...)` | `conftest.py` | 创建 card_info 表 + 4 个索引 |

## test_core/ 子目录 Fixtures

| Fixture | 说明 |
|---------|------|
| `enrich_ctx` | 创建 `EnrichmentContext`（SQLiteUtilsAdapter + EnrichmentEngine + SchemaInferrer） |
| `mediator_ctx` | 创建 `MediatorContext`（SQLiteUtilsAdapter + PluginMediator + SchemaInferrer） |

## 本目录规则

- 优先复用 `tests/conftest.py` 里的 `tmp_db`、`tmp_db_with_data`、`bank_cards_db` fixtures；只有在现有 schema 不够表达需求时再新增 fixture。
- 新测试文件尽量跟源码职责对齐：核心逻辑放 `tests/test_core/`，生成器放 `tests/test_generators/`，数据库层放 `tests/test_database/`，以此类推。
- 可选插件相关测试继续使用 `pytest.importorskip(...)`，不要让整个测试套件无条件依赖可选安装。
- 断言优先描述可观察行为。若生产代码约定是返回 `GenerationResult.errors` 而非抛异常，测试也应锁定这个契约。
- 改 CLI 或公共 API 时，通常需要同步更新 `tests/test_cli.py` 和 `tests/test_public_api.py`。
- 改编排顺序、hook 负载、SharedPool/FK 行为时，只补单测不够，至少再补一条集成覆盖。

## 测试模式

- **真实数据库**：所有 fixture 使用真实 SQLite 临时文件（`tmp_path`），不使用 mock。
- **Mixin 复用**：`test_generators/_mixin.py` 定义 4 个 Mixin 类（`CoreProviderTestMixin`、`IdentityProviderTestMixin`、`TemporalProviderTestMixin`、`JsonSchemaTestMixin`），通过多重继承在 Provider 测试中复用。
- **条件跳过**：`pytest.importorskip("sqlseed_ai")` — AI 插件测试；`pytest.skip("Faker is not installed")` — 可选依赖测试。
- **CLI 测试**：使用 `click.testing.CliRunner`，禁止使用 subprocess。
- **断言风格**：直接 `assert` 语句 + `pytest.raises()` + `pytest.approx()`。
- **Mock**：`unittest.mock.patch` 用于模拟 LLM 调用、entry_points 等；`monkeypatch` 用于环境变量测试。
- **基准测试**：使用 `pytest-benchmark`，标记 `@pytest.mark.benchmark(group="fill")`。

## 验证

- 全量：`pytest`
- 定向：`pytest tests/test_core`, `pytest tests/test_generators`, `pytest tests/test_database`, `pytest tests/test_plugins`, `pytest tests/test_config`
