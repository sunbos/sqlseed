<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-06-21 -->

# benchmarks

## Purpose

Performance benchmarks. Uses pytest-benchmark for data generation performance measurement.

## Key Files

| File | Description |
|------|-------------|
| `bench_fill.py` | Benchmark tests for the `fill` function |

## For AI Agents

### Working In This Directory

- Benchmark results are environment-sensitive; do not set strict thresholds in CI
- New benchmarks should use the `@pytest.mark.benchmark` marker

### Testing Requirements

```bash
pytest tests/benchmarks/ --benchmark-only
pytest tests/benchmarks/ --benchmark-only --benchmark-compare
```

### Common Patterns

- Use the `benchmark` fixture from `pytest-benchmark` to wrap the function under test
- Test scenarios: 1K rows, 10K rows, provider comparison

## Dependencies

### Internal

- `src/sqlseed/`

### External

- `pytest-benchmark>=4.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
