# benchmarks

本目录使用 pytest-benchmark 测量 fill/preview；当前入口是 `bench_fill.py`，文件名不匹配 pytest 默认的 `test_*.py` / `*_test.py` 收集规则。

## 修改要求

- 沿用 `benchmark` fixture 包装被测调用，并添加 `@pytest.mark.benchmark(group="fill")` 等分组。
- `bench_db` 在 `tmp_path` 创建 users 表；fill 测量使用 `clear_before=True`，避免多轮调用累积数据改变负载。
- 当前场景是 1K/10K rows fill 与 5 rows preview，使用 `provider="base"`。添加 provider 对比时显式标明 provider，避免把语义数据生成开销混入原基线。
- 保存基线时记录 commit、Python/依赖版本、硬件、provider 和运行参数，确保 compare 对应同一场景。结果受硬件、Python 版本与 provider 影响；比较时保持环境和场景一致，不在 CI 设置未经验证的硬阈值。
- benchmark 不能替代数据正确性回归；相关行为测试放在 `tests/` 对应模块。

## 执行与比较

从仓库根显式指定文件，并安装 core dev extras 中的 pytest-benchmark：

```bash
pytest tests/benchmarks/bench_fill.py --benchmark-only
pytest tests/benchmarks/bench_fill.py --benchmark-only --benchmark-autosave
pytest tests/benchmarks/bench_fill.py --benchmark-only --benchmark-compare
```

仅执行 `pytest tests/benchmarks/` 不会默认收集 `bench_fill.py`；先保存一次结果，再用 compare 比较同一环境的运行。
