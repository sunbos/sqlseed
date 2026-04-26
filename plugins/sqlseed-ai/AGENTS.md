# AGENTS.md — plugins/sqlseed-ai

## 作用域

- 本目录是可选分发包 `sqlseed-ai`，源码在 `plugins/sqlseed-ai/src/sqlseed_ai/`。
- 包入口通过 `[project.entry-points."sqlseed"]` 注册为 `ai = "sqlseed_ai:plugin"`（即 `AISqlseedPlugin()` 实例）。
- 依赖：`sqlseed>=0.1.0`、`openai>=1.0`。

## 文件清单

| 文件 | 职责 |
|------|------|
| `__init__.py` | `AISqlseedPlugin` 类（4 个 Hook 实现）、`plugin` 模块级实例、`_SIMPLE_COL_RE` 正则 |
| `_client.py` | `get_openai_client(config)` — OpenAI 客户端工厂，封装 `OpenAI(api_key=..., base_url=..., timeout=...)` 创建逻辑 |
| `_json_utils.py` | `parse_json_response(content)` — JSON 响应解析（处理 Markdown 代码围栏清理和 JSON 解析容错） |
| `_model_selector.py` | `select_best_free_model()` — 动态选择 OpenRouter 最受欢迎的免费模型、`select_next_free_model()` — 按优先级列表选择下一个模型（用于回退）、`PREFERRED_FREE_MODELS` 优先级列表、1 小时缓存 |
| `analyzer.py` | `SchemaAnalyzer` — 核心 LLM 分析器（构建 prompt、调用 LLM、解析结果）、`call_llm()` 超时回退（最多 3 个模型）、`_call_llm_once()` 单次调用、`SYSTEM_PROMPT`、`TEMPLATE_SYSTEM_PROMPT` |
| `config.py` | `AIConfig(BaseModel)` — AI 配置模型（api_key、model、base_url、temperature、max_tokens、timeout）、`resolve_model()` 自动选择模型 |
| `errors.py` | `ErrorSummary` dataclass、`summarize_error()` — 错误摘要与分类系统（7 个处理器：pydantic/json/attribute_generator/unknown_generator/expression/file/default） |
| `examples.py` | `FEW_SHOT_EXAMPLES` — 4 个 few-shot 示例（users、bank_cards、orders、employees） |
| `provider.py` | `AIProvider(GeneratorDispatchMixin)` — 兼容性空壳，使用 `__getattr__` 动态分发 + `_RETURN_DEFAULTS` 字典提供默认值 |
| `refiner.py` | `AiConfigRefiner` — AI 配置自纠正引擎（生成→验证→修正循环）、`AISuggestionFailedError` |

## 本目录规则

- 保持它是可选插件。主包 `sqlseed` 不能因为这里或 `openai` 未安装而整体失效。
- OpenAI 兼容客户端配置统一走 `_client.py` 和 `AIConfig`；不要在多个模块里复制 API key、base URL、model 环境变量解析。
- `AISqlseedPlugin`、`SchemaAnalyzer`、模板生成和自纠正流程默认是软失败路径。AI 不可用时应返回 `None`、空结果或可读错误，而不是拖垮整条生成链。
- hook 方法名和参数必须与 `src/sqlseed/plugins/hookspecs.py` 保持一致。
- `refiner.py` 的缓存、schema hash 和重试回路属于包契约的一部分；改动时要同步更新测试。
- `provider.py` 当前是兼容性空壳；不要把真实 LLM 生成主逻辑塞到这里。真实 AI 逻辑通过 hook 而非 Provider 接口执行。
- `SchemaAnalyzer.call_llm()` 默认使用 JSON mode（`response_format={"type": "json_object"}`），当模型不支持时会自动回退到 text mode。回退触发条件：捕获 `APIError/ValueError/RuntimeError`，检查错误消息中是否包含 `"json"`、`"response_format"` 或 `"400"` 关键词。
- `suggest.py`（`ColumnSuggester`）和 `nl_config.py`（`NLConfigGenerator`）已移除。其功能由 `SchemaAnalyzer` + `AiConfigRefiner` 完全替代。如有外部用户导入这些类，需在 CHANGELOG 中注明兼容性中断。

## Hook 实现

| Hook | firstresult | 行为 |
|------|-------------|------|
| `sqlseed_ai_analyze_table` | 是 | 委托 `SchemaAnalyzer.analyze_table_from_ctx(**kwargs)` |
| `sqlseed_pre_generate_templates` | 是 | 仅对**非简单列**调用 `analyzer.generate_template_values()`，上限 50 个值；捕获异常返回 `None` |
| `sqlseed_register_providers` | 否 | 空操作 |
| `sqlseed_register_column_mappers` | 否 | 空操作 |

**简单列过滤**：`_SIMPLE_COL_RE` 匹配常见列名/类型关键词（name、email、phone、address、url、uuid、date、boolean、int、float、text、string、id、code、title、status、type、category 等），匹配到的列跳过 LLM 调用以节省 API 开销。

## AIConfig 环境变量

| 字段 | 环境变量（优先） | 回退环境变量 | 默认值 |
|------|------------------|-------------|--------|
| `api_key` | `SQLSEED_AI_API_KEY` | `OPENAI_API_KEY` | `None` |
| `base_url` | `SQLSEED_AI_BASE_URL` | `OPENAI_BASE_URL` | `"https://openrouter.ai/api/v1"` |
| `model` | `SQLSEED_AI_MODEL` | — | `None`（自动选择最受欢迎的免费模型） |
| `timeout` | `SQLSEED_AI_TIMEOUT` | — | `60.0`（秒） |
| `temperature` | — | — | `0.3` |
| `max_tokens` | — | — | `4096` |

## 动态模型选择

当 `model` 为 `None` 时，`AIConfig.resolve_model()` 会调用 `_model_selector.select_best_free_model()` 自动选择模型：

1. 检查缓存（1 小时有效期）
2. 调用 `GET https://openrouter.ai/api/v1/models`（公开端点，无需 API key）
3. 筛选条件：免费（`pricing.prompt == "0"` 且 `pricing.completion == "0"`）、文本输入输出、支持 `response_format`
4. 按 `PREFERRED_FREE_MODELS` 优先级列表匹配第一个可用模型
5. 如果 API 调用失败或无匹配，回退到优先级列表第一个模型

`PREFERRED_FREE_MODELS` 优先级列表（基于 OpenRouter 网页端免费模型排名，需定期手动更新）：

| 优先级 | 模型 ID |
|--------|---------|
| 1 | `nvidia/nemotron-3-super-120b-a12b:free` |
| 2 | `tencent/hy3-preview:free` |
| 3 | `inclusionai/ling-2.6-1t:free` |
| 4 | `inclusionai/ling-2.6-flash:free` |
| 5 | `z-ai/glm-4.5-air:free` |
| 6 | `minimax/minimax-m2.5:free` |
| 7 | `openai/gpt-oss-120b:free` |
| 8 | `nvidia/nemotron-3-nano-30b-a3b:free` |
| 9 | `google/gemma-4-31b-it:free` |
| 10 | `nvidia/nemotron-nano-9b-v2:free` |
| 11 | `openai/gpt-oss-20b:free` |
| 12 | `google/gemma-4-26b-a4b-it:free` |

用户显式指定 `--model` 或 `SQLSEED_AI_MODEL` 时跳过自动选择。

## LLM 调用超时与模型回退

`call_llm()` 实现了超时回退机制：

1. OpenAI 客户端设置 `timeout`（默认 60 秒，可通过 `SQLSEED_AI_TIMEOUT` 配置）
2. 当 LLM 调用因 `APITimeoutError` 或 `APIConnectionError` 失败时，自动按优先级列表回退到下一个模型
3. 最多尝试 3 个模型
4. 其他错误（如 400、401）不触发回退
5. 回退时通过 `logger.warning` 输出信息

## AiConfigRefiner 自纠正流程

```
1. 创建 DataOrchestrator 上下文
2. 计算 schema_hash（SHA256 前 12 字符）
3. 检查缓存（除非 no_cache=True）
4. 获取 schema 上下文，构建初始消息
5. 循环 max_retries+1 次：
   a. 调用 LLM 生成配置
   b. 验证配置（Pydantic → 列名存在性 → 空配置检查 → preview 试运行）
   c. 若验证通过 → 缓存并返回
   d. 若验证失败 → 将错误配置作为 assistant 消息、修正 prompt 作为 user 消息追加到历史
6. 超过重试次数则抛出 AISuggestionFailedError
```

缓存文件路径：`{cache_dir}/{table_name}.json`，缓存条目含 `_meta.schema_hash` 和 `_meta.created_at`。`_compute_schema_hash` 使用 SHA256 前 12 字符（MCP 服务器版本使用前 16 字符，两者是不同模块中的不同函数）。

## 错误分类系统

`summarize_error()` 按优先级依次尝试 7 个处理器：

| 处理器 | 匹配条件 | `error_type` | `retryable` |
|--------|----------|-------------|-------------|
| `_try_pydantic_error` | `ValidationError` | `"pydantic_validation"` | `True` |
| `_try_json_error` | `JSONDecodeError` | `"json_syntax"` | `True` |
| `_try_attribute_generator_error` | `AttributeError` 且消息含 `"generate_"` | `"unknown_generator"` | `True` |
| `_try_unknown_generator_error` | `UnknownGeneratorError` | `"unknown_generator"` | `True` |
| `_try_expression_error` | 类名含 `"ExpressionTimeout"` 或模块含 `"simpleeval"` | `"expression_error"` | `True` |
| `_try_file_error` | `FileNotFoundError` 或 `PermissionError` | `"fatal"` | `False` |
| `_default_error` | 兜底 | `"runtime_error"` | `True` |

## 评审热点

- prompt、few-shot 示例、JSON 解析和错误摘要会直接影响 `tests/test_ai_plugin.py` 与 `tests/test_refiner.py`。
- `sqlseed ai-suggest` 的 CLI 集成在主包 `src/sqlseed/cli/main.py`，参数或环境变量改动通常需要同时改两边。
- `AIConfig.from_env()` 目前同时支持 `SQLSEED_AI_*` 和 `OPENAI_*` 环境变量，兼容性改动要慎重。

## 验证

- 安装插件：`pip install -e "./plugins/sqlseed-ai"`
- 相关测试：`pytest tests/test_ai_plugin.py tests/test_refiner.py tests/test_cli.py`
