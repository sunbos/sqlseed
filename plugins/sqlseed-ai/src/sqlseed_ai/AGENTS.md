<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-04-29 | Updated: 2026-04-29 -->

# sqlseed_ai

## Purpose

AI 数据生成插件的实现。通过 OpenAI 兼容 API 分析数据库模式并生成数据配置建议。

## Key Files

| File | Description |
|------|-------------|
| `analyzer.py` | `SchemaAnalyzer` 模式分析器，调用 LLM 分析表结构并推荐生成器配置 |
| `refiner.py` | `AiConfigRefiner` 配置优化器，基于 AI 建议优化现有配置，支持自纠正 |
| `provider.py` | AI 数据提供者，实现 `GeneratorDispatchMixin`，为简单列提供默认值 |
| `config.py` | `AIConfig` AI 配置（API key, model, base_url 等），支持环境变量 |
| `_client.py` | OpenAI 客户端工厂，支持自定义 base_url |
| `_model_selector.py` | `select_next_free_model()` 免费模型自动选择与降级 |
| `_json_utils.py` | JSON 响应容错解析，`_sanitize_names()` 名称清洗 |
| `errors.py` | 错误类型定义，`ErrorSummary`/`summarize_error()` 错误汇总 |
| `examples.py` | Few-shot 示例，用于 AI 提示词 |
| `__init__.py` | `AISqlseedPlugin` 插件类，实现 `hookimpl`，导出 `plugin` 实例 |

## AIConfig 环境变量

| 环境变量 | 字段 | 回退 |
|----------|------|------|
| `SQLSEED_AI_API_KEY` | `api_key` | `OPENAI_API_KEY` |
| `SQLSEED_AI_BASE_URL` | `base_url` | `OPENAI_BASE_URL` |
| `SQLSEED_AI_MODEL` | `model` | 无 |
| `SQLSEED_AI_TIMEOUT` | `timeout` | 默认 60.0 |

## LLM 调用与回退机制

1. `call_llm()` 尝试使用 `response_format={"type": "json_object"}`（JSON mode）
2. 若 API 不支持 JSON mode（错误含 "json"/"response_format"/"400"），回退到普通模式
3. 遇到 `APITimeoutError`/`APIConnectionError` 时，调用 `select_next_free_model()` 切换到下一个免费模型
4. 最多尝试 `_MAX_FALLBACK_ATTEMPTS = 3` 次模型降级
5. 所有模型均失败则抛出最后一个异常

## 自纠正流程（AiConfigRefiner）

1. `generate_and_refine()` 调用 LLM 生成 YAML 配置
2. 验证生成的配置是否能通过 `GeneratorConfig` 模型校验
3. 若校验失败，将错误信息反馈给 LLM 请求修正
4. 最多重试 `max_retries=3` 次
5. 包含重复错误检测：若连续两次错误相同则提前终止
6. 使用 `_compute_schema_hash()` 缓存结果（SHA256 前 12 字符），避免重复分析同一 schema

## 错误分类系统（7 个处理器）

`errors.py` 的 `summarize_error()` 按优先级尝试以下处理器：

| # | 处理器 | 捕获的错误类型 |
|---|--------|---------------|
| 1 | `_try_pydantic_error` | Pydantic ValidationError |
| 2 | `_try_json_error` | JSONDecodeError |
| 3 | `_try_attribute_generator_error` | AttributeError（生成器方法不存在） |
| 4 | `_try_unknown_generator_error` | UnknownGeneratorError |
| 5 | `_try_expression_error` | 表达式求值错误 |
| 6 | `_try_file_error` | 文件 I/O 错误 |
| 7 | `_default_error` | 兜底处理器 |

## For AI Agents

### Working In This Directory

- `AISqlseedPlugin` 实现 `hookimpl`：`sqlseed_ai_analyze_table`（分析整张表）和 `sqlseed_pre_generate_templates`（为非简单列生成模板值）
- 简单列（name, email, phone 等）通过 `_SIMPLE_COL_RE` 正则跳过 AI 调用，不要为简单列浪费 LLM token
- `_model_selector.py` 维护免费模型列表，自动选择可用模型，支持降级，模型列表可能需要定期更新
- JSON 解析必须使用 `_json_utils.py` 的容错逻辑，不要直接 `json.loads`，LLM 返回的 JSON 格式可能不规范
- 所有 AI 调用需处理 `APIConnectionError`/`APITimeoutError`/`APIError`
- `refiner.py` 的自纠正流程：生成 → 验证 → 修正，最多重试若干次
- `config.py` 的 `AIConfig` 支持环境变量（`SQLSEED_AI_API_KEY`, `SQLSEED_AI_MODEL`, `SQLSEED_AI_BASE_URL`）

### Testing Requirements

```bash
pytest tests/test_ai_plugin.py tests/test_refiner.py
```

### Common Patterns

- 插件注册：`[project.entry-points."sqlseed"]` 中的 `ai = "sqlseed_ai:plugin"`
- AI 调用流程：`_client.py` 创建客户端 → `analyzer.py` 构建提示词 → 调用 LLM → `_json_utils.py` 容错解析
- 错误处理：`errors.py` 的 `summarize_error()` 将异常转为用户友好的摘要

## Dependencies

### Internal

- `sqlseed`（core, generators, plugins hookspecs）

### External

- `openai>=1.0` — LLM API 客户端

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
