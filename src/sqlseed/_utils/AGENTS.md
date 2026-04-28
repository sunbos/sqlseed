<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# _utils

## Purpose

跨模块共享的底层工具函数。包括日志、指标、进度条和 SQL 安全。

## Key Files

| File | Description |
|------|-------------|
| `logger.py` | structlog 配置，`configure_logging()` 和 `get_logger()` 函数 |
| `metrics.py` | `MetricsCollector` 性能指标收集与汇总统计 |
| `progress.py` | `create_progress()` rich 进度条工厂 |
| `sql_safe.py` | SQL 注入防护：`validate_table_name()`, `quote_identifier()`, `build_insert_sql()` |
| `schema_helpers.py` | 数据库模式检测共享逻辑（如 `detect_autoincrement`） |

## For AI Agents

### Working In This Directory

- `sql_safe.py` 是安全关键模块，修改需极度谨慎，任何变更必须通过安全审查
- 日志统一使用 structlog，所有模块通过 `get_logger(__name__)` 获取，不要使用标准库 `logging`
- 新增工具函数应考虑是否真的被多个模块共享，单模块使用的函数应放在对应模块内
- `MetricsCollector` 使用 dataclass 存储指标条目，支持按名称过滤和汇总统计

### Testing Requirements

```bash
pytest tests/test_utils/
```

### Common Patterns

- `get_logger(__name__)` 获取模块级 logger
- `sql_safe` 模块提供三层防护：验证（validate）、引用（quote）、构建（build）

## Dependencies

### Internal

- 无（底层模块，不依赖其他内部模块）

### External

- `structlog>=24.0` — 结构化日志
- `rich>=13.0` — 进度条

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
