# PROJECT KNOWLEDGE BASE

**核验日期：** 2026-09-14

## 项目概览

sqlseed 是声明式测试数据生成工具：通过 Python API 或 YAML/JSON 配置推断 schema、选择 generator、流式写入数据并维护外键。支持 SQLite 与 PostgreSQL；MySQL 已移除，待 PostgreSQL 完整验证后再考虑。

技术栈：Python 3.10+、hatchling + hatch-vcs、SQLAlchemy、Pydantic、pluggy、structlog；ruff、mypy strict、pytest。许可证为 **AGPL-3.0-or-later**。

仓库现有五个独立 package：离线 core，以及 CLI、AI、MCP、Web 插件。Gemma 4 是 AI 插件的模型与协议方向，不是 backend 名称；配置与修复规则位于插件内。

## 开始工作

- 修改目录前，读取从根到目标目录沿途的 `AGENTS.md`；子级文件只补充本地差异。
- 修改包边界或 public API 前，阅读 [ARCHITECTURE.md](ARCHITECTURE.md)；修改 core 前，阅读 [CLAUDE.md](CLAUDE.md) 的 Never/Always 与 Critical Pitfalls。
- `ARCHITECTURE.md` 是架构决策依据，`CLAUDE.md` 是规则来源；[GEMINI.md](GEMINI.md) 只是指向后者。旧文档中的四包描述、文件统计等可能落后于代码；用 manifest、实现与 CI 核验现状，不把历史描述当成新增行为要求。
- 保留目录内的历史约束回归规则。新增 package 或重要职责边界时，评估并补充本地 `AGENTS.md`；不要给纯数据或薄封装目录添加重复指引。

## 目录与任务导航

| 工作范围 | 入口与本地指引 |
|---|---|
| Core public API | [src/sqlseed/AGENTS.md](src/sqlseed/AGENTS.md)、`src/sqlseed/__init__.py` |
| 编排、列映射、schema、CHECK、FK、流式生成 | [core/AGENTS.md](src/sqlseed/core/AGENTS.md)、`src/sqlseed/core/orchestrator/`、`mapper.py`、`schema.py`、`relation.py` |
| Provider 与 generator dispatch | [generators/AGENTS.md](src/sqlseed/generators/AGENTS.md) |
| SQLAlchemy adapters、dialect、批量写入 | [database/AGENTS.md](src/sqlseed/database/AGENTS.md) |
| 配置模型、加载、snapshot | [config/AGENTS.md](src/sqlseed/config/AGENTS.md) |
| pluggy hooks 与加载生命周期 | [plugins/AGENTS.md](src/sqlseed/plugins/AGENTS.md)；`PluginMediator` 在 `src/sqlseed/core/plugin_mediator.py` |
| 日志、metrics、SQL 安全、缓存路径、进度 | [_utils/AGENTS.md](src/sqlseed/_utils/AGENTS.md) |
| CLI：fill / preview / inspect / init / replay | [sqlseed-cli/AGENTS.md](plugins/sqlseed-cli/AGENTS.md) |
| AI：schema analysis、contract-driven self-healing | [sqlseed-ai/AGENTS.md](plugins/sqlseed-ai/AGENTS.md)，深入层次时读其 `src/sqlseed_ai/AGENTS.md` |
| MCP：规则生成 YAML 与 execute_fill | [mcp-server-sqlseed/AGENTS.md](plugins/mcp-server-sqlseed/AGENTS.md)；import 名称为 `mcp_server_sqlseed` |
| Web：工作台、配置、运行记录、设置与可选组件管理 | [sqlseed-web/AGENTS.md](plugins/sqlseed-web/AGENTS.md) |
| Core 与共享测试、集成测试、benchmark | [tests/AGENTS.md](tests/AGENTS.md)；插件测试在各自 `tests/` |
| README、MkDocs 与文档同步 | [docs/AGENTS.md](docs/AGENTS.md)、`examples/` |
| 校验、演示与发布验收脚本 | [scripts/AGENTS.md](scripts/AGENTS.md) |
| CI、依赖锁定、Pages 与 PyPI 发布 | [.github/AGENTS.md](.github/AGENTS.md) |

`scripts/sync_docs.py` 与 `scripts/_fact_extractors.py` 是正式文档校验工具；同目录的临时 `.db` / `.sql` / `.yaml`、回归日志与 ad-hoc harness 仅作参考，不作为产品稳定依赖。

## 全局规则

- 保持 core 离线、Python API 优先；CLI/AI/MCP/Web 行为留在插件，core 不依赖插件。
- 禁止 `sqlseed.generators` 或 `sqlseed.database` 导入 `sqlseed.core`；禁止 `sqlseed._utils` 导入任何上层。这些边界由 `pyproject.toml` 的 import-linter contracts 校验。
- Python 文件使用 `from __future__ import annotations`。日志经 `sqlseed._utils.logger.get_logger(__name__)`；SQL identifiers 经 `_utils/sql_safe.py` 的 `quote_identifier()`，不得直接拼接未引用的名称。
- Runtime validation 使用 `RuntimeError` / `ValueError`，不用 `assert`；不要以类型抑制掩盖错误。mypy strict 针对 source，排除 tests。
- Provider/adapter 满足现有 Protocol；可选依赖按已有模式 lazy import 并处理 `ImportError`。SQLAlchemy 与 Faker 是 core 必需依赖，Mimesis 是可选依赖。
- 生产数据库入口使用 `SQLAlchemyAdapter`；`RawSQLiteAdapter` 仅供测试。通过 context manager / finally 释放连接并恢复 PRAGMA。
- 保持 `DataStream.generate()` 的流式迭代，不把全量数据收集后再写库。seed、CHECK adaptation 与 FK 两阶段处理的细节见 core 子级指引。
- `fill` / `connect` / `preview` 的 `db_path` 与 `url` 互斥；`fill_from_config(config_path)` 和 `load_config(path)` 接收配置路径。
- `ColumnConfig` 的 source 模式（generator/params）与 derived 模式（derive_from/expression）互斥；修改时核对 `src/sqlseed/config/models.py` 的 validators。
- 测试用 `tmp_path` 创建真实 SQLite，不 mock 数据库行为。CLI 单元测试用 `click.testing.CliRunner`，已安装发行包的入口验收使用真实命令；AI 测试按可选插件安装状态跳过。
- 不写只验证 mock 设置的自证测试；应断言真实计算结果，如 `GeneratorSpec.params`。具体模式见 [test_core/AGENTS.md](tests/test_core/AGENTS.md)。

## 安装与运行

以下开发安装命令从仓库根、独立 virtualenv 中执行。在同一次解析中提供本地 Core 和所有插件，避免混用源码与 PyPI 包。CI 使用相同本地包集合，第三方依赖另按带哈希的锁定文件安装，见 `.github/AGENTS.md`。

```bash
python -m pip install -e ".[dev,all,docs]" -e "./plugins/sqlseed-cli" -e "./plugins/sqlseed-ai[dev]" -e "./plugins/mcp-server-sqlseed" -e "./plugins/sqlseed-web[dev]"
python -m pip check
```

Core 自身没有 console script；`sqlseed` 由 CLI package 提供。`sqlseed-web` 默认监听 `http://127.0.0.1:8630`，普通用户安装发行包后即可启动，不需要仓库辅助脚本。可直接执行的建表与生成示例见 [README.zh-CN.md](README.zh-CN.md)；`make help` 列出开发辅助命令。

## 验证与合并门禁

```bash
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/
mypy src/sqlseed/ plugins/
lint-imports
pytest
node --test plugins/sqlseed-web/tests/test_*.cjs
python scripts/sync_docs.py --check
make docs-build
make mutmut
```

- 以 [.github/workflows/ci.yml](.github/workflows/ci.yml)、[setup-env action](.github/actions/setup-env/action.yml) 和 [pyproject.toml](pyproject.toml) 为命令与依赖依据。
- 默认 `pytest` 收集 core、CLI、AI、MCP 和 Web；CI setup 安装所有包，Node 内置运行器单独验证 Web 前端回归。
- 定向验证按改动选择模块；边界/文档回归可运行 `pytest tests/test_architecture.py tests/test_package_boundaries.py tests/test_doc_sync.py`，这些用例也包含在完整 `pytest` 中。
- `make test-core` 只覆盖 Makefile 中列出的子目录，不涵盖 `tests/` 根层 API/编排回归及 `tests/test_utils/`；验证范围要覆盖实际改动。
- `make test-integration` 运行 `tests/integration/`；PostgreSQL 优先使用独立测试库 `PG_TEST_URL`，否则需要 Docker/testcontainers；真实 LLM 用例需要可用 backend。详见 [integration/AGENTS.md](tests/integration/AGENTS.md)。
- 合并前通过 lint、format、mypy、pytest、import-linter、architecture/doc-sync checks 与本地 mutation gate。`make mutmut` 默认针对 `unique_adjuster`，不在 push CI 执行；`make mutmut-report` 查看幸存 mutant，`make mutmut-clean` 清理缓存。Windows 使用 `mutmut<3` 与 `PYTHONUTF8=1`。
- benchmark 需显式指定 `tests/benchmarks/bench_fill.py`；运行与比较方法见 [benchmarks/AGENTS.md](tests/benchmarks/AGENTS.md)。

## 文档同步

下列源文件发生接口或规则变更时，在同一提交中同步对应文档：

| 源文件 | 对应文档与内容 |
|---|---|
| `src/sqlseed/generators/_dispatch.py` | docs/guide.md 的 Generators 表：完整 generator 名称与自动生成的数量；README 只保留入口与示例 |
| `src/sqlseed/core/mapper.py` | docs/guide.md、docs/architecture.md、docs/architecture.zh-CN.md、CLAUDE.md：exact/pattern match rules |
| `src/sqlseed/core/expression.py` | docs/guide.md：表达式与 SAFE_FUNCTIONS 参考 |
| `src/sqlseed/plugins/hookspecs.py` | docs/guide.md、docs/architecture.md、docs/architecture.zh-CN.md、CLAUDE.md 与相关 AGENTS.md：hooks |
| `src/sqlseed/config/models.py` | docs/architecture.md、docs/architecture.zh-CN.md：模型字段与类型 |
| `plugins/sqlseed-cli/src/sqlseed_cli/main.py` | docs/guide.md 与 CLI 插件 README：完整 CLI reference；根 README 保留入门示例 |
| `plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py` | docs/guide.md 与 AI 插件中英文 README：完整 AI CLI reference；根 README 保留用途概述 |
| `src/sqlseed/__init__.py` | docs/api.md：完整 public API；README.md、README.zh-CN.md：入口表与示例 |

不要手改 `AUTO-GENERATED` 标记内的值；运行 `python scripts/sync_docs.py`，再运行 `python scripts/sync_docs.py --check` 与 `pytest tests/test_doc_sync.py`。需要构建文档时运行 `make docs-build`（MkDocs strict）。

## 发布维护

- 修改依赖后，在根目录、`plugins/sqlseed-ai/`、`plugins/mcp-server-sqlseed/` 各自运行 `uv lock`，维护已有三个 lock files；CLI/Web 当前没有独立 lock file。
- 版本发布同时更新 [CHANGELOG.md](CHANGELOG.md) 和 [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)。
- 推送提交后再创建/推送 `v<version>` tag，并通过 `gh release create` 发布；详细命令与 sigstore attestation 失败的已知处理方式见 [CLAUDE.md](CLAUDE.md) 的 Release Checklist，以及 `.github/workflows/publish.yml`。
- 五包上传成功后，`publish.yml` 的 `verify-public` job 自动在 Linux/Python 3.12 从正式 PyPI 验收。按 [发布指南](docs/releasing.md) 检查该 job 和 `public-pypi-acceptance` artifact，保留文件来源与哈希、真实入口和 SQLite 结果；可用 `scripts/verify_pypi_release.sh <version>` 本地复验。本地构建成功不代表线上发行已验收。
