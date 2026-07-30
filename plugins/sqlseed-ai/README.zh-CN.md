# sqlseed-ai

[English](README.md) | **[中文](README.zh-CN.md)**

[sqlseed](https://github.com/sunbos/sqlseed) 的 AI 驱动数据生成插件。

LLM 驱动的 Schema 分析、自纠正配置生成和模板池辅助。支持多种后端：Google AI Studio（Gemma 4 原生函数调用）、LM Studio、Ollama，以及任何 OpenAI 兼容 API（OpenRouter、OpenAI、DeepSeek 等）。

## 安装

```bash
pip install sqlseed-ai
```

## 快速开始

sqlseed-ai 插件提供 **3 个 CLI 命令**：

| 命令 | 用途 | 适用场景 |
| :--- | :--- | :--- |
| `ai-suggest` | 单表 LLM 分析 + 自纠正 | 单表分析，支持 `--verify` 校验 |
| `ai-analyze` | 全库/部分表分析，走 v4 AutoHealOrchestrator（默认路径） | 多表 YAML 生成，含契约驱动自愈 |
| `auto-heal` | 通过 LLM + 规则管道修复损坏的 YAML 配置 | 修复 `sqlseed fill` 失败的 YAML 文件 |

```bash
# 设置 API Key（或使用 GOOGLE_API_KEY 用于 Google AI Studio）
export SQLSEED_AI_API_KEY="your-api-key"

# ─────────────────────────────────────────────
# ai-suggest: 单表 LLM 分析
# ─────────────────────────────────────────────

# AI 分析并生成配置
sqlseed ai-suggest app.db --table users --output users.yaml

# 带自纠正（默认 3 轮）
sqlseed ai-suggest app.db --table users --output users.yaml --verify

# 指定模型（默认使用 Gemma 4 26B via Google AI Studio）
sqlseed ai-suggest app.db --table users -o users.yaml --model gemma-4-26b-a4b-it

# 使用本地 LM Studio（通过环境变量选择后端）
export SQLSEED_AI_BACKEND=lm_studio
sqlseed ai-suggest app.db --table users -o users.yaml --model google/gemma-4-e4b

# 跳过缓存
sqlseed ai-suggest app.db --table users -o users.yaml --no-cache

# ─────────────────────────────────────────────
# ai-analyze: 全库分析（v4 架构默认路径）
# ─────────────────────────────────────────────

# 分析整个数据库并生成 YAML（v4 AutoHealOrchestrator）
sqlseed ai-analyze --db app.db -o config.yaml

# 通过 --url 连接多数据库
sqlseed ai-analyze --url "postgresql+psycopg://user:pass@host/db" -o config.yaml

# 记录完整 LLM 交互用于调试
sqlseed ai-analyze --db app.db -o config.yaml --log-llm

# ─────────────────────────────────────────────
# auto-heal: 修复损坏的 YAML 配置
# ─────────────────────────────────────────────

# ai-analyze 之后若 `sqlseed fill` 失败，可修复 YAML
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml

# 使用不同的 LLM 模型进行修复
sqlseed auto-heal --db app.db --config broken.yaml -o healed.yaml --model gemma-4-26b-a4b-it
```

## 功能

### Schema 分析器

`SchemaAnalyzer` 从数据库提取丰富上下文（列、索引、样本数据、外键、数据分布），构建结构化 Prompt 供 LLM 分析。返回列级生成配置（JSON 格式）。

### 自纠正 Refiner

`AiConfigRefiner` 验证 LLM 输出是否符合实际 Schema：
1. LLM 生成列配置
2. Refiner 检查未知生成器、类型不匹配、表达式错误
3. 若发现错误，向 LLM 发送修正请求
4. 最多重试 3 轮，然后抛出 `AISuggestionFailedError`

### 自动模型选择

使用 `google_ai_studio` 后端（默认）时，`GemmaModel` 枚举提供预配置的 Gemma 4 变体。模型根据后端自动选择：

1. **Google AI Studio**：默认使用 `gemma-4-26b-a4b-it`（推荐的质量与速度平衡）。
2. **LM Studio / Ollama**：用户需通过 `--model` 或 `SQLSEED_AI_MODEL` 指定已加载的模型。
3. **OpenAI-compatible**（OpenRouter、DeepSeek 等）：用户需同时指定 `--model` 和 `--base-url`。

**OpenRouter 免费模型**设置：
```bash
export SQLSEED_AI_BACKEND=openai_compat
export SQLSEED_AI_BASE_URL=https://openrouter.ai/api/v1
export SQLSEED_AI_MODEL=<免费模型名>
```

通过 `--model` 或 `SQLSEED_AI_MODEL` 跳过自动选择。

使用 `google_ai_studio` 后端时，`GemmaModel` 枚举提供预配置的 Gemma 4 变体：

| 枚举值 | 模型 ID | 说明 |
|:-------|:--------|:-----|
| `GemmaModel.GEMMA_4_E2B` | `gemma-4-e2b-it` | 2B Effective, Edge — 超轻量边缘部署 |
| `GemmaModel.GEMMA_4_E4B` | `gemma-4-e4b-it` | 4B Effective, Edge — 轻量本地推理 |
| `GemmaModel.GEMMA_4_12B` | `gemma-4-12b-it` | 12B Unified, Laptop — 速度与质量均衡 |
| `GemmaModel.GEMMA_4_26B_A4B` | `gemma-4-26b-a4b-it` | 26B A4B MoE — 高质量，推荐使用 |
| `GemmaModel.GEMMA_4_31B` | `gemma-4-31b-it` | 31B Dense — 最佳质量，最大模型 |

`AIBackend` 枚举用于选择 API 后端：

| 枚举值 | 后端 | 默认 Base URL |
|:-------|:-----|:--------------|
| `AIBackend.GOOGLE_AI_STUDIO` | Google AI Studio | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `AIBackend.LM_STUDIO` | LM Studio | `http://127.0.0.1:1234/v1` |
| `AIBackend.OLLAMA` | Ollama | `http://localhost:11434/v1` |
| `AIBackend.OPENAI_COMPAT` | OpenAI 兼容端点 | （需设置 `SQLSEED_AI_BASE_URL`） |

### 模板池

当 sqlseed 以 `skip_ai=False` 填充表时，插件通过 `sqlseed_pre_generate_templates` Hook 为无法映射到确定性生成器的列预生成候选值。

### 文件缓存

AI 配置缓存在平台标准缓存目录（macOS: `~/Library/Caches/sqlseed/ai_configs/`，Linux: `~/.cache/sqlseed/ai_configs/`，Windows: `%LOCALAPPDATA%/sqlseed/ai_configs/`），带 schema hash 校验。Schema 变更自动失效。使用 `--no-cache` 跳过。可通过 `SQLSEED_CACHE_DIR` 环境变量覆盖。

## 配置

### 环境变量

| 变量 | 回退 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `SQLSEED_AI_API_KEY` | `GOOGLE_API_KEY` → `OPENAI_API_KEY` | — | API Key（必填） |
| `SQLSEED_AI_BASE_URL` | `OPENAI_BASE_URL` | （按后端自动设置） | API 端点 |
| `SQLSEED_AI_MODEL` | — | `gemma-4-26b-a4b-it` | 模型名称 |
| `SQLSEED_AI_TIMEOUT` | — | （按后端自动：云端 60s，本地 120s） | API 超时（秒） |
| `SQLSEED_AI_BACKEND` | — | `google_ai_studio` | AI 后端：`google_ai_studio`、`lm_studio`、`ollama`、`openai_compat` |
| `GOOGLE_API_KEY` | — | — | Google AI Studio API Key（后端为 `google_ai_studio` 时作为 `SQLSEED_AI_API_KEY` 的回退） |

### CLI 参数

```
--model, -m       模型名称（覆盖自动选择）
--api-key         API Key（覆盖环境变量）
--base-url        API Base URL（覆盖环境变量）
--max-retries     自纠正轮数（默认: 3，0=禁用）
--verify/--no-verify  切换自纠正（默认: verify）
--no-cache        跳过文件缓存
--timeout         API 超时秒数（按后端自动：云端 60s，本地 120s）
```

## 插件 Hooks

本插件通过 `[project.entry-points."sqlseed"]` 注册，实现：

| Hook | 用途 |
|:-----|:-----|
| `sqlseed_ai_analyze_table` | LLM 驱动的表分析，返回列配置 |
| `sqlseed_apply_ai_suggestions` | 编排器调用的高层 AI 中介入口（判断是否需要 AI，并将结果合并到列配置） |
| `sqlseed_transform_row` | 防御性回退：为配置错误的 DATE 列将 ISO 日期字符串转换为 `datetime.date` |
| `sqlseed_pre_generate_templates` | 为复杂列预生成候选值 |

> **注**：本插件**未实现** `sqlseed_register_providers` 和 `sqlseed_register_column_mappers` —— 注册通过 `pyproject.toml` entry point 处理。

## 依赖

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `openai >= 1.0`
- OpenAI 兼容 API Key 或 Google AI Studio API Key

## Gemma 4 集成

使用 `google_ai_studio` 后端时，sqlseed-ai 利用 **Gemma 4 原生函数调用（Native Function Calling）** 进行结构化 Schema 分析：

### GEMMA_TOOLS

插件定义了 `GEMMA_TOOLS` 函数声明（现定义在 `_tools.py` 中，原在 `analyzer.py`），指示 Gemma 4 以结构化 Schema 分析响应。模型被要求调用 `analyze_schema` 函数并传入类型化参数（表名、列、外键、索引等），而非输出自由文本，从而确保输出符合预期的 Schema。

> **注**：所有 LLM prompt 模板（full、compact、ultra-compact 及模板生成 prompt）均集中位于 `_prompts.py`。

### 原生函数调用机制

1. **工具定义**：`GEMMA_TOOLS` 声明 `analyze_schema` 函数，使用严格的 JSON Schema 描述每个参数（table_name、columns、foreign_keys、indexes 等）。
2. **请求发送**：将 Schema 上下文和分析 Prompt 发送给 Gemma 4 模型，附带 `tools=[GEMMA_TOOLS]` 和 `tool_config` 设置为强制函数调用。
3. **响应解析**：模型返回 `FunctionCall` 对象而非纯文本。插件直接提取结构化参数，无需正则匹配或脆弱的文本解析。
4. **验证**：提取的参数通过相同的 `AiConfigRefiner` 管道进行自纠正验证。

此方法显著提高了输出可靠性，因为模型被约束为生成格式良好、符合 Schema 的响应，避免了基于文本的 LLM 输出解析的不确定性。

## 许可证

AGPL-3.0-or-later
