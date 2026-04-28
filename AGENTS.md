<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# sqlseed

## Purpose

声明式 SQLite 测试数据生成工具包。通过 YAML/JSON 配置或 Python API，自动推断数据库模式并生成高质量测试数据。

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | 项目元数据、依赖、构建配置（hatchling + hatch-vcs） |
| `AGENTS.md` | 本文件 — 项目级 AI 指令 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/sqlseed/` | 主包源码（见 `src/sqlseed/AGENTS.md`） |
| `plugins/sqlseed-ai/` | AI 数据生成插件（见 `plugins/sqlseed-ai/AGENTS.md`） |
| `plugins/mcp-server-sqlseed/` | MCP 服务器插件（见 `plugins/mcp-server-sqlseed/AGENTS.md`） |
| `tests/` | 测试套件（见 `tests/AGENTS.md`） |
| `.github/workflows/` | CI/CD 工作流（ci.yml, publish.yml） |
| `examples/` | 示例脚本 |

## Public API

`src/sqlseed/__init__.py` 导出以下公共接口：

| API | 签名 | 用途 |
|-----|------|------|
| `fill` | `(db_path, *, table, count=1000, columns=None, provider="mimesis", locale="en_US", seed=None, batch_size=5000, clear_before=False, optimize_pragma=True, enrich=False, transform=None, skip_ai=False) -> GenerationResult` | 单表零配置填充 |
| `connect` | `(db_path, *, provider="mimesis", locale="en_US", optimize_pragma=True) -> DataOrchestrator` | 返回 DataOrchestrator 上下文管理器 |
| `preview` | `(db_path, *, table, count=5, columns=None, provider="mimesis", locale="en_US", seed=None, enrich=False, transform=None) -> list[dict[str, Any]]` | 预览生成数据，不写入 |
| `fill_from_config` | `(config_path, *, skip_ai=False, clear_before=False, count=None, provider=None, seed=None, batch_size=None, locale=None) -> list[GenerationResult]` | 从 YAML/JSON 配置批量填充 |
| `load_config` | `(path) -> GeneratorConfig` | 加载配置文件为 GeneratorConfig |

导出的类型：`ColumnConfig`, `TableConfig`, `GeneratorConfig`, `ProviderType`, `DataOrchestrator`, `GenerationResult`, `__version__`。

## For AI Agents

### Working In This Directory

- 目标 Python 3.10+，保留 `from __future__ import annotations`，所有函数和类必须有完整类型注解
- 代码格式化使用 ruff（行宽 120），类型检查使用 mypy strict 模式
- 注释使用中文
- 可选依赖（faker, mimesis, sqlite-utils, sqlseed-ai, mcp）导入时必须 try/except，设置 `HAS_XXX` 标志，不能让核心包因可选依赖缺失而无法导入
- 日志统一使用 structlog，通过 `get_logger(__name__)` 获取
- SQL 标识符拼接必须使用 `_utils.sql_safe` 模块的函数（`quote_identifier`, `validate_table_name`, `build_insert_sql`），禁止 f-string 拼接
- 公共函数默认使用仅关键字参数；已知例外是 `generate_choice(choices)` 的 `choices` 是位置参数，不要修改
- 公开 API、CLI 参数、配置模型和 hook 签名属于外部契约，改动前先查对应测试
- 插件包是独立分发单元，不要把插件实现细节反向塞回主包

### Testing Requirements

```bash
pytest tests/                        # 运行全部测试
pytest --cov=sqlseed                 # 带覆盖率
ruff check .                         # 代码检查
ruff format .                        # 代码格式化
mypy src plugins                     # 类型检查
```

### Common Patterns

- 安装开发环境：`pip install -e ".[dev,all]"`
- 安装 AI 插件：`pip install -e "./plugins/sqlseed-ai"`
- 安装 MCP 插件：`pip install -e "./plugins/mcp-server-sqlseed"`
- 构建系统：hatchling + hatch-vcs，版本号由 git tag 自动生成，不要手动修改 `_version.py`
- AGENTS.md 已在 `pyproject.toml` 的 sdist exclude 列表中，不会打包到发行版

## Dependencies

### Internal

- `src/sqlseed/` 是核心包，`plugins/` 下的插件依赖核心包

### External

- 核心依赖：`sqlite-utils>=3.36`, `pydantic>=2.0`, `pluggy>=1.3`, `structlog>=24.0`, `pyyaml>=6.0`, `click>=8.0`, `rich>=13.0`, `typing_extensions>=4.4`, `simpleeval>=1.0`, `rstr>=3.2`
- 可选依赖：`faker>=30.0`, `mimesis>=18.0`
- 开发依赖：`pytest>=8.0`, `pytest-cov>=5.0`, `pytest-benchmark>=4.0`, `ruff>=0.5`, `mypy>=1.10`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
