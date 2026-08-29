<!-- Parent: ../AGENTS.md -->
<!-- Last updated: 2026-08-30 -->

# benchmarks

## Purpose

Performance benchmarks. Uses pytest-benchmark for data generation performance measurement. 1 file, 3 benchmarks.

## Key Files

| File | Benchmarks | Description |
|------|-----------:|-------------|
| `bench_fill.py` | 3 | `fill` 1K/10K rows + `preview` 5 rows |

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
- Test scenarios: 1K/10K row fill + 5-row preview (all `provider="base"`)

## Dependencies

### Internal

- `src/sqlseed/`

### External

- `pytest-benchmark>=4.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
