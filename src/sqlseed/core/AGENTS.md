# AGENTS.md — src/sqlseed/core

## 作用域

- 本目录拥有数据生成主流程：编排、列映射、DAG、表达式、约束、Transform、Enrichment、SharedPool、Schema 包装与插件中介。

## 文件清单

| 文件 | 职责 |
|------|------|
| `orchestrator.py` | `DataOrchestrator`（主编排器）、`CoreCtx`/`ExtCtx` dataclass |
| `mapper.py` | `ColumnMapper`（9 级策略链）、`GeneratorSpec` dataclass |
| `column_dag.py` | `ColumnDAG`（拓扑排序）、`ColumnNode`/`ColumnConstraints` dataclass |
| `constraints.py` | `ConstraintSolver`（唯一性约束 + 回溯）、`RegisterResult` dataclass |
| `expression.py` | `ExpressionEngine`（安全表达式求值）、`ExpressionTimeoutError` |
| `transform.py` | `load_transform()`（动态加载 Python 脚本）、`RowTransformFn` 类型别名 |
| `enrichment.py` | `EnrichmentEngine`（数据分布推断 + 枚举检测） |
| `unique_adjuster.py` | `UniqueAdjuster`（唯一列参数调整） |
| `relation.py` | `RelationResolver`（FK 解析 + 拓扑排序）、`SharedPool`（跨表值池） |
| `schema.py` | `SchemaInferrer`（Schema 推断 + 列分布画像） |
| `result.py` | `GenerationResult` dataclass |
| `plugin_mediator.py` | `PluginMediator`（AI 建议 + 模板池 + 批量 transform） |

## 关键不变量

- `DataOrchestrator.fill_table()` 的顺序是有语义的：连接与插件注册、PRAGMA 优化、可选清表、规格解析、AI 建议、模板池、构建 `DataStream`、生成前后 hook、批量插入前后 hook、SharedPool 注册，以及 `finally` 中恢复 PRAGMA。
- `DataOrchestrator.__init__` 接受 `associations: list[Any] | None = None` 参数，构造时传递给 `RelationResolver.set_associations()`。`from_config()` 会自动从 `GeneratorConfig.associations` 传入。
- 当 `enrich=True` 且 `clear_before=True` 时，编排器会在清空表之前先解析 specs（以捕获现有数据分布），然后清空表，再使用已解析的 specs 生成数据。
- `preview_table()` 复用规格解析，但不写数据库，也不会走 AI 建议或模板池路径。改这里时不要无意把 preview 变成 fill 的副本。
- `fill_table()` 出错时返回带 `errors` 的 `GenerationResult`，而不是把绝大多数异常向上抛出。
- `PluginMediator` 走尽力而为策略：AI 建议和模板池异常会被吞掉并记 debug；批量 transform 会链式应用最后一个非 `None` 结果；SharedPool 注册后会触发 `sqlseed_shared_pool_loaded` hook。
- `DataStream` 同时维护自己的 RNG，并在有 seed 时单独给 Provider 设 seed。它只对 `choice` / `foreign_key` 做本地特判，其他未知生成器会继续抛 `UnknownGeneratorError`。
- Transform 脚本是显式逃生通道，会执行用户 Python 代码；相关加载和上下文约定要保持清晰，不要把它伪装成受限沙箱。
- `RelationResolver`/`SharedPool` 的职责是保持 FK 与跨表值池行为稳定，尤其是填充后的值注册。
- `ConstraintSolver._is_seen()` 仅检查值是否存在，**不会隐式注册**。`check_and_register()` 先调用 `_is_seen()` 再显式调 `_register()`。
- `ConstraintSolver.check_and_register()` 对 `value=None` 直接返回 `True`（跳过注册），与 `try_register()` 行为一致。
- `ConstraintSolver` 支持 `probabilistic=True` 模式，使用 SHA256 hash-based 去重降低内存占用（适用于 >100K 行），以及 `check_and_register_composite()` 复合唯一约束。
- `ExpressionEngine.evaluate()` 对每次调用创建独立的 `simpleeval.SimpleEval()` 实例，避免竞态条件。超时机制使用独立线程（默认 5 秒），通过 `ExpressionTimeoutError`（继承自 `TimeoutError`）报告。**注意**：线程超时后无法被强制终止，超时线程仍在后台运行。
- `ExpressionEngine.SAFE_FUNCTIONS` 白名单包括 21 个函数：`len`、`int`、`str`、`float`、`hex`、`oct`、`bin`、`abs`、`min`、`max`、`upper`、`lower`、`strip`、`lstrip`、`rstrip`、`zfill`、`replace`、`substr`、`lpad`、`rpad`、`concat`。
- `EnrichmentEngine.ENUM_NAME_PATTERNS` 包含 19 条枚举列名模式（`^by[A-Za-z]`、`*_type`、`*_status`、`is_*`、`has_*`、`can_*`、`*_level`、`*_category`、`*_class`、`*_flag`、`*_kind`、`*_grade`、`*_rank`、`*_tier`、`*_mode`、`*_stage`、`*_phase`、`*_state`、`*_group`）。
- `PluginMediator.AI_APPLICABLE_GENERATORS` 为 `frozenset({"string", "integer", "date", "datetime", "choice"})`，只有这些类型的列会触发 AI 分析。
- `register_shared_pool()` 在 `fill_table()` 完成后调用，遍历所有非 `skip` 的列以及自增主键列（`skip` + PK），从数据库查询值（`limit=10000`）并合并到 `SharedPool`。自增主键的值也会被注册，以便其他表的 FK 引用可以找到这些值。
- `SharedPool.merge()` 使用 `set()` 进行去重追加，对不可哈希值（如 `dict`/`list`）通过 `try/except TypeError` 回退到线性扫描。
- `resolve_implicit_associations()` 检查 SharedPool 中是否存在同名列值，实现无 FK 约束的隐式跨表关联。仅对 `foreign_key_or_integer` 类型的 spec 进行隐式关联。
- `apply_associations()` 处理 `ColumnAssociation` 配置中的显式跨表关联。使用 `assoc.source_column or assoc.column_name` 确定源表列名，先查 SharedPool 再查数据库获取值，将目标列升级为 `foreign_key` 生成器。

## 修改建议

- 改列映射、唯一性、Enrichment、DAG 排序或表达式求值时，同时看 `tests/test_core/` 和 `tests/test_orchestrator.py`、`tests/test_mapper.py`、`tests/test_relation.py`、`tests/test_schema.py`。
- 改 hook 时机、payload 或插件中介逻辑时，连同 `src/sqlseed/plugins/hookspecs.py` 与插件测试一起审。
- 保持 `core` 对可选插件实现包无直接运行时依赖；集成应通过 hook 规范和 entry point 完成。
- 如果要修改"静默回退"或"捕获异常继续返回结果"的策略，必须同步更新测试和用户文档。

## 验证

- 核心单测：`pytest tests/test_core`
- 集成相关：`pytest tests/test_orchestrator.py tests/test_mapper.py tests/test_relation.py tests/test_schema.py`
- 影响公共行为时再跑：`pytest tests/test_public_api.py tests/test_cli.py`
