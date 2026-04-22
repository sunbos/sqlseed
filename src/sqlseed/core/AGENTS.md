# AGENTS.md — src/sqlseed/core

## 作用域

- 本目录拥有数据生成主流程：编排、列映射、DAG、表达式、约束、Transform、Enrichment、SharedPool、Schema 包装与插件中介。

## 关键不变量

- `DataOrchestrator.fill_table()` 的顺序是有语义的：连接与插件注册、PRAGMA 优化、可选清表、规格解析、AI 建议、模板池、构建 `DataStream`、生成前后 hook、批量插入前后 hook、SharedPool 注册，以及 `finally` 中恢复 PRAGMA。
- `preview_table()` 复用规格解析，但不写数据库，也不会走 AI 建议或模板池路径。改这里时不要无意把 preview 变成 fill 的副本。
- `fill_table()` 出错时返回带 `errors` 的 `GenerationResult`，而不是把绝大多数异常向上抛出。
- `PluginMediator` 走尽力而为策略：AI 建议和模板池异常会被吞掉并记 debug；批量 transform 会链式应用最后一个非 `None` 结果；SharedPool 注册后会触发 `sqlseed_shared_pool_loaded` hook。
- `DataStream` 同时维护自己的 RNG，并在有 seed 时单独给 Provider 设 seed。它只对 `choice` / `foreign_key` 做本地特判，其他未知生成器会继续抛 `UnknownGeneratorError`。
- Transform 脚本是显式逃生通道，会执行用户 Python 代码；相关加载和上下文约定要保持清晰，不要把它伪装成受限沙箱。
- `RelationResolver`/`SharedPool` 的职责是保持 FK 与跨表值池行为稳定，尤其是填充后的值注册。

## 修改建议

- 改列映射、唯一性、Enrichment、DAG 排序或表达式求值时，同时看 `tests/test_core/` 和 `tests/test_orchestrator.py`、`tests/test_mapper.py`、`tests/test_relation.py`、`tests/test_schema.py`。
- 改 hook 时机、payload 或插件中介逻辑时，连同 `src/sqlseed/plugins/hookspecs.py` 与插件测试一起审。
- 保持 `core` 对可选插件实现包无直接运行时依赖；集成应通过 hook 规范和 entry point 完成。
- 如果要修改“静默回退”或“捕获异常继续返回结果”的策略，必须同步更新测试和用户文档。

## 验证

- 核心单测：`pytest tests/test_core`
- 集成相关：`pytest tests/test_orchestrator.py tests/test_mapper.py tests/test_relation.py tests/test_schema.py`
- 影响公共行为时再跑：`pytest tests/test_public_api.py tests/test_cli.py`
