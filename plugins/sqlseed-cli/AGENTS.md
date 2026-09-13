# sqlseed-cli 包边界

**源码核验日期：** 2026-09-14

本包提供 `sqlseed` console script；依赖 core、Click 与 Rich。实现规则见
[src/sqlseed_cli/AGENTS.md](src/sqlseed_cli/AGENTS.md)，包配置见 [pyproject.toml](pyproject.toml)。

## 依赖与发布

- 保持 CLI 可单独安装；AI 命令通过 `sqlseed.cli_commands` entry point 接入，生产源码不要直接依赖 `sqlseed_ai`。
- 当前 CLI 要求 Core `>=0.2.4.dev0,<0.3`；Core 0.2.3 的 public API 没有 CLI 调用所需的 `url` 参数。
- console script 指向 `sqlseed_cli:main`；不要把 CLI 入口放回 core。
- 本包使用 hatch-vcs，从仓库根获取版本；没有独立 `uv.lock`。
- 修改核心命令或参数时，同步 [docs/guide.md](../../docs/guide.md#cli-reference) 和本包 README 的 CLI 参考；仓库根的中英文 README 只保留入门示例。

## 测试与验证

先按[根指南](../../AGENTS.md#安装与运行)在同一次解析中安装本地 Core 与插件，再从仓库根执行：

```bash
pytest plugins/sqlseed-cli/tests/
ruff check plugins/sqlseed-cli/
ruff format --check plugins/sqlseed-cli/
mypy plugins/sqlseed-cli/src/sqlseed_cli/
```

- CLI 单元测试使用 `click.testing.CliRunner`；发行入口验收仍需在独立环境运行真实 console script，见根 scripts 指南。
- `tests/test_cli.py` 覆盖命令、URL、snapshot/replay；`test_cli_yaml_priority.py` 验证 CLI 与 YAML 优先级；`test_cli_utils.py` 验证名称清理。
- `tests/test_config_execution_safety.py` 验证配置与显式目标冲突时两库均不改变、部分提交的实际行数，以及 provider / locale / batch_size 的 CLI 与 API 优先级一致。
- `tests/test_snapshot_transform.py` 用真实行值验证 transform 的快照保存与重放，不只检查退出码或“Snapshot saved”文案。
- `tests/test_cli_ai_commands.py` 当前直接导入 `sqlseed_ai.cli.ai_commands`；完整测试依赖本地 AI 插件，部分生成案例还使用可选 Mimesis，根安装命令覆盖这些依赖。不要据此让 CLI 生产包直接依赖 AI 或 Mimesis。
- 共享 DB fixtures 来自仓库根 `conftest.py`；本包 `tests/conftest.py` 不重新注册 `pytest_plugins`。
- 配置优先级测试要实际加载 YAML、写入临时 SQLite 并检查结果；不要只断言 mock 收到同样的参数。
