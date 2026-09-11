# test_core

本目录验证 core 的 DAG、约束、CHECK adaptation、表达式、enrichment、唯一性调整、stream 与 plugin mediation。共享测试规则继承 [../AGENTS.md](../AGENTS.md)。

## 关键入口

- `conftest.py` 提供 `make_stream()`、`enrich_ctx` 与 `mediator_ctx`；helper 保持真实组件与数据库生命周期。
- `test_stream.py` / `test_constraints.py` 覆盖批量生成、约束回溯与大数据量的 probabilistic set 模式。
- `test_check_parser.py` / `test_check_adapt.py` 覆盖确定性 CHECK 提取，以及参数 overlap 裁剪、disjoint 拒绝。
- `test_column_dag.py` 覆盖拓扑排序与循环检测；`test_expression.py` 覆盖 sandbox 和 timeout。
- `test_enrichment.py` / `test_features.py` 验证已有数据的 enum 检测与结构特征；不要只验证 mock 的返回值。
- `test_unique_adjuster.py` 与 `test_unique_exclude_integration.py` 分别验证参数计算和 exclude_values 的真实写入结果。
- `test_schema_fallback.py` / `test_orchestrator_schema_fallback.py` 验证 fallback 与编排集成。
- `test_plugin_mediator.py` / `test_transform.py` 覆盖 hooks 结果选择与用户 transform 加载。

## 唯一性回归的关键模式

- 参考 `test_unique_adjuster.py::TestAdjustChoiceFallback`：使用真实 `ColumnMapper` 与 `ColumnInfo`，选非 exact-rule 名称（例如 `category` / `rank`）并带非 None default，触发 `_type_faithful_fallback` 和下游调整数学。
- 断言最终 `GeneratorSpec.params` 的范围/长度等具体值；`MagicMock(return_value=...)` 加 `assert_called_once_with(...)` 不证明计算正确。
- 修改边界处理时覆盖 nullable UNIQUE skip、PRIMARY KEY/default skip、唯一值空间不足及超限情况；保留已有 regression case 的实际触发条件。
- `test_sqlite_schema_oracles.py` 先用原生 SQL 建立允许/拒绝的事实，再验证实际生成落库；只在普通表中替换 INT/BIGINT/INTEGER 不能覆盖 WITHOUT ROWID/DESC，两个 adapter 返回同一 metadata 模型也不能证明 SQLite 语义正确。

## 验证

从仓库根执行：

```bash
pytest tests/test_core/
pytest tests/test_orchestrator.py tests/test_relation.py
make mutmut
```

`make mutmut` 的默认目标是 `unique_adjuster`；用 `make mutmut-report` 查找幸存 mutant。历史高存活率说明断言可能过弱，不是提高容忍阈值的理由。
