# sqlseed_cli 实现

**源码核验日期：** 2026-09-14

上层规则见 [包指南](../../AGENTS.md)。本目录负责参数解析、终端展示和 core API 调用；生成与校验算法留在库层。

## 入口与职责

| 文件 | 修改入口 |
| --- | --- |
| [main.py](main.py) | `cli` group；`fill`、`preview`、`inspect`、`init`、`replay`；`FillOptions` 与分组 dataclasses |
| [__init__.py](__init__.py) | 导出 `cli`/`main`；导入时发现并注册插件命令 |
| [_utils.py](_utils.py) | `sanitize_table_config()` 原地去掉表名、列名前导 `.`/`:` |

`main.py` 中的 `_execute_config_fill()` 负责配置覆盖值，`_execute_fill()` 负责分支与直接填充，`_load_replay_config()` 负责快照解析错误。修改优先级或错误处理时沿这些入口定位，避免把已提取的职责重新堆进命令函数。

## 命令约定

- 新 core 命令挂到 `main.py` 的 `cli` group。第三方命令使用 `sqlseed.cli_commands`，entry point callable 签名为 `register(cli_group)`。
- 插件注册失败应记录 WARNING 并继续提供基础 CLI；不要扩大捕获范围吞掉 `KeyboardInterrupt`/`SystemExit`。
- 用户输出用 `click.echo`/Rich；内部日志用项目 logger。`cli()` 从 `SQLSEED_LOG_LEVEL` 读取日志级别，默认 WARNING。
- `fill`/`preview`/`inspect` 的 positional `db_path` 与 `--url` 互斥；调用 public API 时未使用的一方传 `None`。
- `init` 的 `--db` 默认保持 `None`，只有 `--db` 和 `--url` 均未提供时才补 `test.db`，否则会错误拒绝 `init --url`。
- `fill` 无 `--config` 时要求正数 `--count`；`--config` 下未指定 count/seed 时保留 `None`，由 core 使用 YAML 值。
- `fill --config` 的连接目标只能来自配置文件；与 positional `db_path` 或 `--url` 混用时在写库前返回 usage error，避免静默忽略显式目标。
- `_execute_config_fill()` 通过 Click parameter source 区分选项来源：不传 decorator 默认 provider/locale/batch-size，让 core 保留 YAML 值；显式参数（即使等于默认值）仍覆盖。无配置路径保持原默认值。改优先级时同时验证真实 CLI 与 core API 两条入口。
- 直接 `fill`、配置批量 `fill` 与 `replay` 的 `result.errors` 会展示并以非零 exit code 表示部分失败；配置批量路径保留每张表实际提交的 count，不把某张表失败误报为全部回滚。
- 将数据库异常转为用户错误时复用 `_redact_credentials()`；避免在终端错误里泄漏 URL 凭据。
- `replay` 使用 `SnapshotManager.load()`、`GeneratorConfig`、`DataOrchestrator.from_config()`；保留 snapshot 中的列配置、seed、batch_size、clear_before 与 transform。直接 `fill --transform --snapshot` 必须保存 transform 路径，重放时仍需该脚本可用。
- `replay` 对含 `..` 且解析到 cache 目录之外的路径拒绝访问；不要误改为禁止所有外部绝对路径。

## 局部验证

从仓库根运行 `pytest plugins/sqlseed-cli/tests/`，依赖要求见上层包指南。按修改范围重点检查：

- 参数优先级、目标冲突和部分提交：[test_cli_yaml_priority.py](../../tests/test_cli_yaml_priority.py)、[test_config_execution_safety.py](../../tests/test_config_execution_safety.py)。
- 快照与 transform 重放：[test_cli.py](../../tests/test_cli.py)、[test_snapshot_transform.py](../../tests/test_snapshot_transform.py)。
- 入口发现和 AI 命令接入：[test_cli_ai_commands.py](../../tests/test_cli_ai_commands.py)。
