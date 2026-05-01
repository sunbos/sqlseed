# sqlseed-ai

[English](README.md) | **[中文](README.zh-CN.md)**

[sqlseed](https://github.com/sunbos/sqlseed) 的 AI 驱动数据生成插件。

LLM 驱动的 Schema 分析、自纠正配置生成和模板池辅助。使用 OpenAI 兼容 API（默认：OpenRouter 免费模型）。

## 安装

```bash
pip install sqlseed-ai
```

## 快速开始

```bash
# 设置 API Key（OpenRouter、OpenAI、DeepSeek 等）
export SQLSEED_AI_API_KEY="your-api-key"

# AI 分析并生成配置
sqlseed ai-suggest app.db --table users --output users.yaml

# 带自纠正（默认 3 轮）
sqlseed ai-suggest app.db --table users --output users.yaml --verify

# 指定模型
sqlseed ai-suggest app.db --table users -o users.yaml --model deepseek/deepseek-chat

# 跳过缓存
sqlseed ai-suggest app.db --table users -o users.yaml --no-cache
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

查询 OpenRouter API 找到最佳可用免费模型，按优先级列表回退：

```
nvidia/nemotron-3-super-120b-a12b:free → tencent/hy3-preview:free → ...
```

结果缓存 1 小时。通过 `--model` 或 `SQLSEED_AI_MODEL` 跳过自动选择。

### 模板池

当 sqlseed 以 `skip_ai=False` 填充表时，插件通过 `sqlseed_pre_generate_templates` Hook 为无法映射到确定性生成器的列预生成候选值。

### 文件缓存

AI 配置缓存在 `.sqlseed_cache/ai_configs/`，带 schema hash 校验。Schema 变更自动失效。使用 `--no-cache` 跳过。

## 配置

### 环境变量

| 变量 | 回退 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `SQLSEED_AI_API_KEY` | `OPENAI_API_KEY` | — | API Key（必填） |
| `SQLSEED_AI_BASE_URL` | `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | API 端点 |
| `SQLSEED_AI_MODEL` | — | 自动选择 | 模型名称 |
| `SQLSEED_AI_TIMEOUT` | — | `60` | API 超时（秒） |

### CLI 参数

```
--model, -m       模型名称（覆盖自动选择）
--api-key         API Key（覆盖环境变量）
--base-url        API Base URL（覆盖环境变量）
--max-retries     自纠正轮数（默认: 3，0=禁用）
--verify/--no-verify  切换自纠正（默认: verify）
--no-cache        跳过文件缓存
--timeout         API 超时秒数（默认: 120）
```

## 插件 Hooks

本插件通过 `[project.entry-points."sqlseed"]` 注册，实现：

| Hook | 用途 |
|:-----|:-----|
| `sqlseed_ai_analyze_table` | LLM 驱动的表分析，返回列配置 |
| `sqlseed_pre_generate_templates` | 为复杂列预生成候选值 |
| `sqlseed_register_providers` | 占位（无操作，entry-point 注册） |
| `sqlseed_register_column_mappers` | 占位（无操作，entry-point 注册） |

## 依赖

- Python >= 3.10
- `sqlseed >= 0.1.0`
- `openai >= 1.0`
- OpenAI 兼容 API Key

## 许可证

AGPL-3.0-or-later
