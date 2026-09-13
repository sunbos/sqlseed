# test_utils

本目录验证日志、metrics、缓存路径与进度展示；实现规则见 [_utils/AGENTS.md](../../src/sqlseed/_utils/AGENTS.md)。

## 入口与隔离

- `test_metrics.py`：直接构造 `MetricsCollector`，验证记录、过滤、聚合与空集合边界。
- `test_logger.py`：验证 structlog 的自动初始化、日志级别、stderr 和环境配置；保留 `_restore_logging` 的清理。
- logger 使用 `cache_logger_on_first_use=True`，已有 logger 不随新配置更新；需要观察配置切换时使用唯一 logger 名称，避免跨测试状态污染。
- `test_paths.py`：覆盖 macOS/Linux/Windows 与 `SQLSEED_CACHE_DIR`；环境变量用 monkeypatch，创建目录用 `tmp_path`，不写用户真实缓存。
- `test_progress.py`：覆盖 Null/Rich/tqdm 后端与环境检测；无 UI/无可选依赖的 fallback 仍要能工作。
- 修改 environment/platform 检测时验证实际返回结果和状态恢复，不只验证某个 mock 调用。

## 验证

从仓库根执行：

```bash
pytest tests/test_utils/
lint-imports
```

`_utils` 是叶子层；测试可以导入其他模块辅助验证，但不能因此在生产 `_utils` 引入上层依赖。
