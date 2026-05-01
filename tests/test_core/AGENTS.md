<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# test_core

## Purpose

核心引擎组件的单元测试。覆盖 DAG、约束求解、枚举增强、表达式求值、唯一性调整和插件中介。

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | 核心模块局部 fixture（enrich_ctx, mediator_ctx 等） |
| `test_column_dag.py` | ColumnDAG 拓扑排序和依赖解析测试 |
| `test_constraints.py` | ConstraintSolver 唯一性约束和回溯测试 |
| `test_enrichment.py` | EnrichmentEngine 枚举列增强测试 |
| `test_expression.py` | ExpressionEngine 表达式求值测试 |
| `test_plugin_mediator.py` | PluginMediator 插件交互测试 |
| `test_transform.py` | 用户自定义变换脚本加载测试 |
| `test_unique_adjuster.py` | UniqueAdjuster 唯一性调整测试 |

## For AI Agents

### Working In This Directory

- DAG 测试需覆盖循环依赖检测
- 约束求解测试需覆盖大数据集场景（概率集合模式）
- 表达式引擎测试需覆盖安全沙箱边界

### Testing Requirements

```bash
pytest tests/test_core/
```

### Common Patterns

- 使用 `conftest.py` 中的局部 fixture 创建测试用核心组件实例

## Dependencies

### Internal

- `src/sqlseed/core/`

### External

- `pytest>=8.0`

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
