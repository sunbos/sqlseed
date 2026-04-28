<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# core

## Purpose

数据生成的核心编排引擎。负责模式推断、列映射、约束求解、枚举增强、派生表达式求值和批量数据流生成。

## Key Files

| File | Description |
|------|-------------|
| `orchestrator.py` | `DataOrchestrator` 主编排器，上下文管理器，协调所有核心组件完成 fill/preview 流程 |
| `column_dag.py` | `ColumnDAG` 列依赖有向无环图，拓扑排序确保派生列在其依赖列之后生成 |
| `constraints.py` | `ConstraintSolver` 唯一性约束求解器，支持回溯和概率集合模式 |
| `enrichment.py` | `EnrichmentEngine` 枚举列增强引擎，通过列名模式自动识别枚举列 |
| `expression.py` | `ExpressionEngine` 派生列表达式求值，基于 simpleeval 沙箱 |
| `mapper.py` | `ColumnMapper` 列名/类型到生成器的映射，含 `GeneratorSpec` 和多级策略链 |
| `schema.py` | `SchemaInferrer` 数据库模式推断，读取列信息和外键关系 |
| `relation.py` | `RelationResolver` 外键关系解析，`SharedPool` 共享值池确保 FK 一致性 |
| `result.py` | `GenerationResult` 生成结果数据类 |
| `transform.py` | 用户自定义行变换脚本加载与执行 |
| `unique_adjuster.py` | `UniqueAdjuster` 唯一性约束自动调整生成器参数 |
| `plugin_mediator.py` | `PluginMediator` 插件与核心组件的交互中介 |

## For AI Agents

### Working In This Directory

- `DataOrchestrator` 使用 `CoreCtx`/`ExtCtx` 两个 dataclass 管理内部状态，新增核心组件应注入到对应 ctx，不要在 orchestrator 中直接实例化
- `ColumnDAG` 通过拓扑排序保证派生列在其依赖的源列之后生成，不要绕过 DAG 直接计算派生列
- `ConstraintSolver` 对大数据集（>100K 行）使用概率集合模式（`_use_probabilistic=True`），用哈希换取内存
- `ExpressionEngine` 使用 simpleeval 沙箱执行用户表达式，有超时保护，新增安全函数需评估风险
- `EnrichmentEngine` 通过列名模式匹配（如 `is_*`, `*_type`, `*_status`）自动识别枚举列
- `preview_table()` 不走 AI 路径，不调用 `pre_generate_templates` hook
- `ConstraintSolver.check_and_register()` 对 `None` 值不隐式注册到唯一集合，只有非 None 值才注册
- `SharedPool` 确保外键列引用的值与父表实际插入的值一致，不要绕过它直接生成 FK 值
- 不要破坏 `DataOrchestrator` 的上下文管理器协议（`__enter__`/`__exit__`）

### Testing Requirements

```bash
pytest tests/test_core/
pytest tests/test_orchestrator.py tests/test_mapper.py tests/test_schema.py tests/test_relation.py
```

### Common Patterns

- 核心组件通过 `CoreCtx`（内部状态）和 `ExtCtx`（外部可访问状态）注入 orchestrator
- `ColumnMapper` 使用 7 级策略链：PK+autoincrement → user_config → 精确匹配(74条) → 有默认值 → 模式匹配(25条) → nullable → 类型回退(22条)
- `EnrichmentEngine.ENUM_NAME_PATTERNS` 定义了 19 条枚举列名模式
- `ExpressionEngine.SAFE_FUNCTIONS` 白名单定义了 21 个沙箱可用函数
- `PluginMediator.AI_APPLICABLE_GENERATORS = frozenset({"string"})` — 仅 string 类型列走 AI 生成

### 评审热点

- `ExpressionEngine` 的超时保护使用线程实现，但 Python 线程无法被强制终止，极端情况下可能残留
- `SharedPool.merge()` 对不可哈希值使用 `try/except TypeError` 回退到线性搜索，大数据量时可能影响性能
- `ConstraintSolver` 的概率模式阈值 >100K 仅在文档注释中提到，当前 orchestrator 未自动切换

## Dependencies

### Internal

- `generators`（DataProvider, DataStream）
- `database`（DatabaseAdapter, ColumnInfo）
- `config`（ColumnConfig）
- `_utils`（logger, sql_safe）
- `plugins`（PluginManager, PluginMediator）

### External

- `simpleeval` — 表达式沙箱求值
- `pydantic` — 数据类验证

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
