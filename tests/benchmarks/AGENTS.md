<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# benchmarks

## Purpose

性能基准测试。使用 pytest-benchmark 进行数据生成性能测量。

## Key Files

| File | Description |
|------|-------------|
| `bench_fill.py` | fill 函数的基准测试 |

## For AI Agents

### Working In This Directory

- 基准测试结果受环境影响，不要在 CI 中设置严格阈值
- 新增基准测试应使用 `@pytest.mark.benchmark` 标记

### Testing Requirements

```bash
pytest tests/benchmarks/ --benchmark-only
pytest tests/benchmarks/ --benchmark-only --benchmark-compare
```

### Common Patterns

- 使用 `pytest-benchmark` 的 `benchmark` fixture 包装被测函数
- 测试场景：1K 行、10K 行、不同 provider 对比

## Dependencies

### Internal

- `src/sqlseed/`

### External

- `pytest-benchmark>=4.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
