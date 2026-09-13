# 底层共享工具

**核验日期：** 2026-09-14

本目录是 leaf layer，承接[核心包规则](../AGENTS.md)；禁止导入 `core/generators/database/plugins/config`。只接收多个模块需要的公共能力，单模块 helper 留在原模块。

## SQL 安全边界

- [sql_safe.py](sql_safe.py) 提供 sanitize → quote → parameterized INSERT；改动必须检查 SQL injection 边界并做安全 review。
- `quote_identifier()` 将内部双引号转义为两个双引号；拒绝空白名称、NUL、`;`、换行、回车与单引号。允许连字符，不能误伤已安全引用的表名。
- `sql_safe.validate_table_name(name)` 会 warning 非常规名称并返回 quoted identifier；它不验证表是否存在。
- [paths.py](paths.py) 的 `validate_table_name(name, allowed_tables)` 检查 allowlist membership；不要因同名而混用这两个函数。
- `build_insert_sql()` 用 `?` placeholder 绑定值；不要把数据值拼进 SQL。
- [paths.py](paths.py) 的 `validate_db_target()` 接受数据库 URL 或存在的 `.db/.sqlite/.sqlite3` 路径，URL 由 SQLAlchemy 后续校验；它检查后缀与存在性，不打开验证 SQLite 内容，也不施加项目目录限制。

## 其他工具

- [logger.py](logger.py)：统一使用 `get_logger(__name__)` / `configure_logging()`，不要另起标准库 logging 配置；默认日志输出 stderr，避免污染数据输出。导入时必须保留宿主已有的 structlog 配置；只有尚未配置时才安装默认处理器，显式调用 `configure_logging()` 仍可覆盖。
- logger 首次使用后会缓存绑定配置；宿主应在 import 或首次使用前配置日志，不能假设后续 `configure_logging()` 会更新已缓存 logger。
- [metrics.py](metrics.py)：`MetricsCollector` 聚合 count/total/min/max/avg；保留单次遍历与按名称过滤。
- [progress.py](progress.py)：通过 `create_progress()` 选 backend，disabled → Null，Jupyter 且有 tqdm → notebook backend，其他环境且有 Rich → Rich；缺少对应可选库均降级为 Null，保留编码不支持时的 ASCII fallback。
- tqdm 是 notebook 可选依赖，Rich 由 CLI 依赖提供；不能让缺失进度显示库破坏 core 的 import 或生成路径。
- `get_cache_dir()` 优先 `SQLSEED_CACHE_DIR`，否则遵循 macOS/Linux/Windows 路径约定；只返回路径，调用方负责创建目录。
- [daemon_task.py](daemon_task.py) 用 Future 管理单个 daemon worker 的结果与异常；超时只停止等待，不终止工作。需要在 worker 内执行的完成回调通过构造参数 `on_done` 在线程启动前注册，避免快速任务完成后回调落到调用线程。进程控制异常也必须传回等待方，不能变成 `None` 成功结果。
- [type_checks.py](type_checks.py) 的 `has_exact_type()` 表达严格内建类型合同；计数与 JSON 类型边界不能因改用普通 `isinstance(value, int)` 而接受布尔值。

## 验证与文档

从仓库根执行 `pytest tests/test_utils/ tests/test_database/test_sql_safe.py`。SQL quoting 修改补跑 `pytest tests/test_database/test_helpers.py`；logger/progress/daemon 行为分别在 `tests/test_utils/test_logger.py`、`test_progress.py`、`test_daemon_task.py` 验证。`lint-imports` 检查 leaf layer 不反向依赖上层；依赖边界依据 [ARCHITECTURE.md](../../../ARCHITECTURE.md)，测试约定见 [tests/test_utils/AGENTS.md](../../../tests/test_utils/AGENTS.md)。
