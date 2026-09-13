# sqlseed_ai 运行时

继承 [插件边界](../../AGENTS.md)。此处维护 AI 调用、插件 hooks 和 v4 修复引擎；自动修复的大型 CHECK 推断模块另读 [auto_heal/AGENTS.md](auto_heal/AGENTS.md)。

## 六层职责

Layer 表示架构层；healer 的 Level 表示 LLM 修复粒度，二者不能混用。

| Layer | 目录 / 入口 | 负责的行为 |
|---|---|---|
| 1 | [contracts/](contracts/) | `ContractViolation`、`ContractResolver`、builtin / learned violations |
| 2 | [validator/](validator/) | `FastValidator`：单列 contract / cardinality、跨列 FK / DAG、composite FK、DBAPI 异常解析、SQLite shadow FK 定位 |
| 3 | [repair/](repair/) | `REPAIR_STRATEGIES` 纯函数、`RepairExecutor` 按 `fix_hint` 派发、`RepairPipeline` 增量复验 |
| 4 | [healer/](healer/) | `HealOrchestrator`、分级 LLM 调用、振荡检测、降级、broken-edge 对齐、diff learning |
| 5 | [auto_heal/](auto_heal/) | `AutoHealOrchestrator`：snapshot → subgraph → validate / repair / heal → 对齐 → schema 复核 → YAML |
| 6 | [analyzer/](analyzer/) | `SchemaAnalyzer` 单表分析，供非 auto-heal 的 `ai-suggest` 使用 |

## Contracts 与确定性修复

- Contract matrix 是只列已知坏组合的 closed set；未匹配默认 COMPATIBLE。优先匹配更具体的条目，相同 specificity 时 learned 优先于 builtin；learned registry 保留 `schema_hash` 过滤，不把缺少条目当作失败。
- 新修复行为优先在 [repair/strategies.py](repair/strategies.py) 添加纯 `RepairFn` 并注册到 `REPAIR_STRATEGIES`；保持 Registry / Validator / Executor 的通用派发边界。
- `normalize_params` 是生成器参数白名单的统一来源；[refiner.py](refiner.py) 已委托它，勿复制旧 Rule #14。日期参数白名单需保留各 provider 实际支持的参数形式。
- `coerce_float_to_int` 处理 INTEGER 列的 `random_float`；derived mode、日期生成器和 CHECK 关联修复沿用现有策略。旧规则迁移参考 [v4_coverage_matrix.md](../../../../docs/superpowers/plans/v4_coverage_matrix.md)，不要重建 legacy validator。
- **Repair accounting**：`before == after` 表示策略拒绝修复，必须进入 `unfixable`，不能增加 `applied_fixes` / `fix_count`；这直接影响 `RepairPipeline` 的部分修复复验条件。
- 更新列字典前复制策略返回值，防止返回同一对象后 `clear()` 把配置清空；保留原始 `before` 审计信息。
- **Phone hard truth**：`_semantic_upgrade` 和 `_upgrade_phone_to_pattern` 遇到 `LENGTH(col)=N` 时使用 `pattern` / `[0-9]{N}`；不要退回可变长度 `phone` 或把该情形当作成功 no-op。

## Healer 路由与降级

- Level 1 = subgraph；Level 2 = column + dependencies；Level 3 = compact / ultra-compact + JSON repair；Level 4 = deterministic degrade。
- Level 1 失败路由：`CONTEXT_OVERFLOW` / `EMPTY_RESPONSE` → Level 2；`JSON_FORMAT` → Level 3；`SEMANTIC` / `UNKNOWN` → Level 4；`NETWORK` → 抛出错误。
- [healer/candidate_validation.py](healer/candidate_validation.py) 在 merge / success 边界使用 Core 配置模型和内置 dispatch 签名校验候选结构、参数名和类型；无效候选按 semantic failure 降级，不污染已接受配置。它不执行 generator / native 方法，不替代 FastValidator 的 closed-set contract，也不宣称验证所有生成值或 SQL CHECK。
- [healer/context_detector.py](healer/context_detector.py) 在估计 tokens 超过 context window 的 60% 时跳过 Level 1；修改阈值或路由须覆盖相应上下文和失败分类测试。
- 保留 [healer/subgraph.py](healer/subgraph.py) 的 Tarjan SCC 与 megacluster breaking、[healer/oscillation.py](healer/oscillation.py) 的振荡终止，以及 [healer/post_repair.py](healer/post_repair.py) 的 broken FK edge 对齐。
- 降级前由 `HealOrchestrator._restore_failed_columns()` 从原始确定性配置恢复失败列；`ProgressiveDegrader` 保留 CHECK 推断的 `generator` / `params` / `derive_from` / `expression`，只剥离 LLM native 字段并记录原因。
- 失败列的 `table:column` 标识必须只恢复对应表；同时保留旧裸列名输入的兼容，不让同名列跨表串改。
- 级联降级覆盖 derived dependents 与 composite FK group；使用 visited 防循环。`derive_from` 为字符串时做完整名称比较，列表时做成员比较，不能用字符串子串判断依赖。
- Source / derived mode 的互斥清理由 repair 和 auto-heal 最终清理保证；不要误把它改成降级时无条件删除确定性规则。

## Analyzer、配置与调用链

- [runtime.py](runtime.py) 提供 `build_ai_config()` / `build_llm_client()` / `build_heal_orchestrator()`，供 CLI 与 Web 等入口共用；不得导入 Click、输出交互消息或抛 `SystemExit`。缺配置抛 `ValueError`，缺依赖保留 `ImportError`，错误呈现由入口负责。
- Runtime 工厂创建的 HTTP client 由创建它的入口关闭，CLI/Web 用 `closing()` 覆盖构造和执行失败；healer 只借用传入的 client / snapshot / validator，不取得资源所有权。此处保留既有 auto-heal 的 `timeout or None` 语义，analyzer 继续使用 `_client.py` 的自动解析策略，不在边界提取时统一不同路径的 timeout。
- `SchemaAnalyzer` 是 mixin 组合的 package：`_caller.py` 管请求与模型 fallback，`_streaming.py` 管流式分派，`_tool_calling.py` 管协议，`_context.py` 管上下文，`_json_parser.py` 管解析和分析入口。修改放入对应职责文件。
- OpenAI client 与异常类型统一通过 [_client.py](_client.py)；不要在 `analyzer/` 直接导入 `openai` 或重复构造 timeout。环境默认配置走 `AIConfig.from_env()`。
- `AIConfig.resolve_*()` 返回解析值，不能改写公开配置字段；调用方必须使用返回值。`timeout=0` 和 `max_tokens=0` 表示自动解析，不能作为真实请求的零预算。
- `gemma4` 协议仅 Google AI Studio 支持；`openai` 支持 Google AI Studio / OpenAI-compatible；LM Studio / Ollama 或不支持的请求协议回退 `none`。两个工具协议共用 [_tools.py](_tools.py) 的 `GEMMA_TOOLS`。
- 工具调用失败回退 JSON / text；非结构化 LLM 文本交给 [_json_utils.py](_json_utils.py) 的 `parse_json_response()`，保留 channel / fence / raw-decode 兼容处理。
- [_prompts.py](_prompts.py) 的 full → compact → ultra-compact 提供上下文降级，选择优先级是 ultra-compact > compact > full；本地 E2B / E4B 使用 ultra-compact 并关闭 streaming。模板值使用独立 `TEMPLATE_SYSTEM_PROMPT`。
- `APITimeoutError` / `APIConnectionError` 的模型 fallback 由 `_model_selector.py` 和 `_caller.py` 管理；本地 fallback 必须先验证模型可用，保留有界重试和最终错误。
- [refiner.py](refiner.py) 的单表建议使用 `TableConfig` 校验、live schema 列名检查和小批 preview，再由 [errors.py](errors.py) 汇总失败供下一次提示；不要用完整 `GeneratorConfig` 替换单表校验。
- Refiner 缓存文件名使用完整表名的 SHA-256，不能把 SQL 标识符直接用作文件路径。只兼容读取缓存目录内的旧 basename 文件，拒绝越界路径和指向目录外的链接；`no_cache=True` 同时禁止读写缓存。
- Refiner 缓存的 schema 校验值仍是排序列名的截断 SHA-256，不是完整 schema fingerprint，不能与 Layer 5 乐观锁使用的 `SchemaSnapshot.schema_hash` 混用。新格式缓存往返需保留合法的完整表名。
- `SchemaSnapshot.schema_hash` 包含列类型、可空性、默认值、computed / identity / autoincrement 元数据以及既有约束与外键；不包含记录值、采集时间等非 schema 信息。新增语义字段时保持排序 JSON 的稳定计算。

## Hooks 与集成

- [__init__.py](__init__.py) 导出 `plugin = AISqlseedPlugin()`；hooks 使用 `sqlseed.plugins.hookspecs.hookimpl`，不注册 provider / mapper。
- `sqlseed_apply_ai_suggestions` 委托 [ai_mediator.py](ai_mediator.py)，AI mediation 不能搬回 Core；保留 hook 的失败降级行为，预期分析 / 模板错误按现有捕获边界返回 `None`。
- `_SIMPLE_COL_RE` 跳过可由普通生成器处理的模板列；模板生成请求最多 `min(count, 50)` 个值。
- `sqlseed_transform_row` 的 ISO 字符串 → `datetime.date` 转换是 DATE 列防御路径，保留无法转换时的容错。
- 验证按 [../../tests/AGENTS.md](../../tests/AGENTS.md) 选择测试；新增 Python 文件保留 English docstring，并使用真实可用类型，不用 `Any` / `type: ignore` 掩盖可建模的类型。
