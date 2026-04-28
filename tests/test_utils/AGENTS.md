<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_utils

## Purpose

工具模块测试。覆盖指标收集等工具函数。

## Key Files

| File | Description |
|------|-------------|
| `test_metrics.py` | MetricsCollector 指标收集测试 |

## For AI Agents

### Working In This Directory

- 验证指标的记录、过滤和汇总统计
- 测试空指标集的边界情况

### Testing Requirements

```bash
pytest tests/test_utils/
```

### Common Patterns

- 直接实例化 `MetricsCollector` 进行测试

## Dependencies

### Internal

- `src/sqlseed/_utils/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
