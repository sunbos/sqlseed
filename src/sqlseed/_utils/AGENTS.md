# 底层共享工具

本目录是 leaf layer；禁止导入 `core/generators/database/plugins/config`。只接收多个模块需要的公共能力，单模块 helper 留在原模块。

## SQL 安全边界

- [sql_safe.py](sql_safe.py) 提供 sanitize → quote → parameterized INSERT；改动必须检查 SQL injection 边界并做安全 review。
- `quote_identifier()` 将内部双引号转义为两个双引号；拒绝空白名称、NUL、`;`、换行、回车与单引号。允许连字符，不能误伤已安全引用的表名。
- `sql_safe.validate_table_name(name)` 会 warning 非常规名称并返回 quoted identifier；它不验证表是否存在。
- [paths.py](paths.py) 的 `validate_table_name(name, allowed_tables)` 检查 allowlist membership；不要因同名而混用这两个函数。
- `build_insert_sql()` 用 `?` placeholder 绑定值；不要把数据值拼进 SQL。
- `validate_db_target()` 接受数据库 URL 或存在的 `.db/.sqlite/.sqlite3` 文件，URL 由 SQLAlchemy 后续校验；不施加项目目录限制。

## 其他工具

- [logger.py](logger.py)：统一使用 `get_logger(__name__)` / `configure_logging()`，不要另起标准库 logging 配置；默认日志输出 stderr，避免污染数据输出。导入时必须保留宿主已有的 structlog 配置；只有尚未配置时才安装默认处理器，显式调用 `configure_logging()` 仍可覆盖。
- [metrics.py](metrics.py)：`MetricsCollector` 聚合 count/total/min/max/avg；保留单次遍历与按名称过滤。
- [progress.py](progress.py)：通过 `create_progress()` 选 backend，disabled → Null，Jupyter → tqdm，terminal → Rich；保留编码不支持时的 ASCII fallback。
- tqdm 是 notebook 可选依赖；不能因未安装 notebook 支持破坏其他环境。
- `get_cache_dir()` 优先 `SQLSEED_CACHE_DIR`，否则遵循 macOS/Linux/Windows 路径约定；只返回路径，调用方负责创建目录。

## 验证

从仓库根执行 `pytest tests/test_utils/ tests/test_database/test_sql_safe.py`。SQL quoting 修改补跑 `pytest tests/test_database/test_helpers.py`；`lint-imports` 检查 leaf layer 不反向依赖上层。
