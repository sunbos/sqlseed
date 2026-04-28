<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# tests

## Purpose

项目测试套件。使用 pytest 框架，包含单元测试、集成测试和性能基准。

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | 全局 pytest fixture 和辅助函数 |
| `_helpers.py` | FK 完整性断言和配置填充验证辅助 |
| `test_public_api.py` | 公共 API 测试（fill/connect/preview/fill_from_config） |
| `test_orchestrator.py` | DataOrchestrator 集成测试 |
| `test_mapper.py` | ColumnMapper 映射逻辑测试 |
| `test_relation.py` | RelationResolver + SharedPool 测试 |
| `test_schema.py` | SchemaInferrer 测试 |
| `test_cli.py` | CLI 命令测试（CliRunner） |
| `test_ai_plugin.py` | AI 插件集成测试（importorskip） |
| `test_refiner.py` | AiConfigRefiner 自纠正测试 |
| `test_enrich_enum_detection.py` | 枚举列检测独立测试 |
| `test_result.py` | GenerationResult 数据类测试 |
| `test_cli_yaml_priority.py` | CLI 参数覆盖 YAML 配置的优先级测试 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test_core/` | 核心引擎组件测试（见 `test_core/AGENTS.md`） |
| `test_generators/` | 数据生成器测试（见 `test_generators/AGENTS.md`） |
| `test_database/` | 数据库适配层测试（见 `test_database/AGENTS.md`） |
| `test_config/` | 配置系统测试（见 `test_config/AGENTS.md`） |
| `test_plugins/` | 插件系统测试（见 `test_plugins/AGENTS.md`） |
| `test_utils/` | 工具模块测试（见 `test_utils/AGENTS.md`） |
| `benchmarks/` | 性能基准测试（见 `benchmarks/AGENTS.md`） |

## For AI Agents

### Working In This Directory

- 优先复用 `conftest.py` 中的 fixture（`tmp_db`, `tmp_db_with_data`, `bank_cards_db`, `raw_adapter`），只有现有 schema 不够时才新增
- 可选插件测试使用 `pytest.importorskip("sqlseed_ai")`，不让整个套件无条件依赖可选安装
- CLI 测试使用 `click.testing.CliRunner`，禁止使用 subprocess
- 所有 fixture 使用真实 SQLite 临时文件（`tmp_path`），不使用 mock 数据库

### Testing Requirements

```bash
pytest tests/                        # 运行全部测试
pytest tests/test_core/              # 只跑核心模块测试
pytest --cov=sqlseed                 # 带覆盖率
pytest -x                            # 遇到第一个失败就停止
```

### Common Patterns

- 断言风格：直接 `assert` + `pytest.raises()` + `pytest.approx()`
- Mock：`unittest.mock.patch` 用于 LLM 调用和 entry_points，`monkeypatch` 用于环境变量
- `conftest.py` 中的 `make_col()` 动态创建模拟 ColumnInfo 对象
- `autouse=True` 的 `_gc_between_tests` fixture 在每个测试前后强制 `gc.collect()`

## Dependencies

### Internal

- `src/sqlseed/`（被测代码）
- `plugins/sqlseed-ai/`（AI 插件测试，可选）

### External

- `pytest>=8.0`, `pytest-cov>=5.0`, `pytest-benchmark>=4.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
