# sqlseed 核心包

**核验日期：** 2026-09-14

本目录提供离线 Python API、生成引擎及插件基础设施，承接[根级规则](../../AGENTS.md)。CLI、AI、MCP、Web 的实现放在仓库 `plugins/` 下；修改包边界前读 [ARCHITECTURE.md](../../ARCHITECTURE.md)。

## 按工作范围继续阅读

| 工作 | 局部指导 |
| --- | --- |
| schema、mapping、流式生成、约束、关系 | [core/AGENTS.md](core/AGENTS.md) |
| DataOrchestrator 的 mixin、连接、fill、preview | [core/orchestrator/AGENTS.md](core/orchestrator/AGENTS.md) |
| provider、generator dispatch、locale | [generators/AGENTS.md](generators/AGENTS.md) |
| adapter、dialect、批量写入 | [database/AGENTS.md](database/AGENTS.md) |
| YAML/JSON、Pydantic、snapshot | [config/AGENTS.md](config/AGENTS.md) |
| pluggy hookspec 与插件发现 | [plugins/AGENTS.md](plugins/AGENTS.md) |
| SQL safety、logger、metrics、cache、progress | [_utils/AGENTS.md](_utils/AGENTS.md) |

## Public API

[__init__.py](__init__.py) 是用户入口；保留参数兼容性并通过现有 orchestrator 委托实现。

- `fill(db_path, *, url, table, count, ...)`：向单表写入数据。
- `connect(db_path, *, url, ...)`：返回支持 context manager 的 `DataOrchestrator`。
- `preview(db_path, *, url, table, count, ...)`：生成预览，不写入数据库。
- `fill_from_config(config_path)`：加载配置并按关联顺序批量生成。
- `load_config(path)`：读取 `GeneratorConfig`。
- 前三者的 `db_path` 与 `url` 互斥；后两者接收配置路径，没有数据库连接参数。
- `fill()` 管理单次连接生命周期；`connect()` 返回由调用方关闭的 orchestrator。`fill_from_config()` 先预检所有请求表并拒绝重复 catalog 身份，再按 FK 顺序逐表生成；不要把预检描述成多表事务。

## 包边界

- 核心不直接导入外部插件或引入 LLM runtime；通过现有 hookspec 扩展。`core/enrichment.py` 是本地计算，保留在核心。
- 依赖方向与 Protocol 合约承接根级规则，细节分别见 generators、database、_utils 的局部指导；不要为复用少量逻辑跨越层级。
- Core 的 import 和 Python API 必须在未安装 CLI/AI/MCP/Web 时可用；保留 optional dependency 的降级路径，Faker 与 SQLAlchemy 仍是必需依赖。

## 验证与文档

命令从仓库根执行；按局部指导选择受影响测试。

- Public API 改动运行 `pytest tests/test_public_api.py tests/test_architecture.py`；多表执行或连接生命周期变更补跑 `pytest tests/test_core/test_fill_safety_boundaries.py tests/test_core/test_connection_lifecycle.py`。
- 修改 [__init__.py](__init__.py) 时同步 [docs/api.md](../../docs/api.md) 的完整参考，以及 [README.md](../../README.md) 与 [README.zh-CN.md](../../README.zh-CN.md) 的入口表和示例。
- 其他源码与文档的联动遵循[根指南](../../AGENTS.md#文档同步)的同步矩阵，并核对 [CLAUDE.md](../../CLAUDE.md) 中相关规则；不要手改 AUTO-GENERATED markers，运行 `python scripts/sync_docs.py` 与 `pytest tests/test_doc_sync.py`。
