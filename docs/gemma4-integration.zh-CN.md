# Gemma 4 集成指南

GemmaSQLSeed 深度集成了 Gemma 4 模型家族，利用**原生函数调用（Native Function Calling）**实现智能 Schema 分析和数据生成。

## 支持的模型

| 模型 | 变体 | 推荐后端 | 使用场景 |
|------|------|---------|---------|
| `gemma-4-e2b-it` | E2B (2B Effective, Edge) | Ollama / LM Studio | 超轻量端侧部署 |
| `gemma-4-e4b-it` | E4B (4B Effective, Edge) | LM Studio | 本地 Schema 分析 |
| `gemma-4-12b-it` | 12B Unified | LM Studio / Ollama | 速度与质量均衡 |
| `gemma-4-26b-a4b-it` | 26B A4B MoE | Google AI Studio | 复杂分析 + 自纠正 |
| `gemma-4-31b-it` | 31B Dense | Google AI Studio | 最强推理能力 |

## 后端配置

### Google AI Studio（云端）

```bash
export GOOGLE_API_KEY=your-key
# 模型默认使用 gemma-4-26b-a4b-it
```

### LM Studio（本地 GUI）

```bash
export SQLSEED_AI_BACKEND=lm_studio
export SQLSEED_AI_MODEL=google/gemma-4-e4b
# 确保 LM Studio 已运行并加载了 Gemma 4 模型
```

### Ollama（本地 CLI）

```bash
export SQLSEED_AI_BACKEND=ollama
export SQLSEED_AI_MODEL=gemma4:e4b
# 确保 Ollama 已运行：ollama pull gemma4:e4b
```

## 原生函数调用（Native Function Calling）

GemmaSQLSeed 通过 `GEMMA_TOOLS` 定义了一个函数接口（唯一的工具：`analyze_schema`）：

### analyze_schema

分析数据库表结构，推荐数据生成配置。

```python
GEMMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_schema",
            "description": "Analyze a database table schema and recommend data generation configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {"type": "string"},
                    "columns": {"type": "array", "items": {...}},
                    "foreign_keys": {"type": "array", "items": {...}},
                    "indexes": {"type": "array", "items": {...}},
                },
                "required": ["table_name", "columns"],
            },
        },
    }
]
```

### 调用流程

实际策略由 `AIConfig.resolve_tool_calling_protocol()` 按后端解析：

```
1. 仅当解析协议为 "gemma4"（仅 Google AI Studio）或 "openai"
   （Google AI Studio / OpenAI 兼容）时，才尝试原生函数调用
   （tools=GEMMA_TOOLS, tool_choice="auto"）
2. Gemma 4 选择 analyze_schema 函数，返回结构化参数
3. 从 tool_call.function.arguments 中提取 JSON
4. 降级：云端后端（Google AI Studio / OpenAI 兼容）使用 JSON mode
   （response_format: json_object）；本地后端（LM Studio、Ollama）
   直接使用纯文本模式。
```

## Agent 记忆（自纠正机制）

`AiConfigRefiner` 实现了自纠正循环：

```
Gemma 4 生成初始配置
    -> 验证（类型检查、约束检查、依赖完整性）
    -> 如果发现错误：
        -> 将错误信息反馈给 Gemma 4
        -> Gemma 4 修正配置
        -> 重新验证（最多 3 轮）
    -> 最终配置 -> 数据填充
```

## MCP 服务器工具

提供 3 个 Gemma 4 专用 MCP 工具：

| 工具 | 说明 |
|------|------|
| `sqlseed_gemma4_analyze` | 使用 Gemma 4 原生函数调用分析 Schema |
| `sqlseed_gemma4_agent_fill` | 端到端 Agent 工作流（分析 -> 配置 -> 填充） |
| `sqlseed_list_gemma_models` | 列出可用的 Gemma 4 模型变体和后端状态 |

## 快速开始

```bash
# 一键启动 Gemma 4 演示
python scripts/quickstart.py --backend lm_studio --model google/gemma-4-e4b

# CLI 使用
sqlseed ai-suggest app.db -t users -o config.yaml

# Python API
from sqlseed_ai import SchemaAnalyzer
from sqlseed_ai.config import AIConfig
from sqlseed.core.orchestrator import DataOrchestrator

config = AIConfig.from_env()  # 读取 SQLSEED_AI_BACKEND, SQLSEED_AI_MODEL
analyzer = SchemaAnalyzer(config=config)

with DataOrchestrator("app.db") as orch:
    schema_ctx = orch.get_schema_context("users")
result = analyzer.analyze_table_from_ctx(**schema_ctx)
```

## 性能参考

| 后端 | 模型 | Schema 分析耗时 | 备注 |
|------|------|---------------|------|
| LM Studio | E4B (4B Effective, Edge) | ~5 分钟 | 本地推理，完整 system prompt |
| LM Studio | E4B (4B Effective, Edge)（精简） | ~20 秒 | 精简 prompt，更少示例 |
| Google AI Studio | 26B A4B MoE | ~10-30 秒 | 云端推理，推荐使用 |
| Ollama | 4B | ~3-5 分钟 | 本地 CLI，与 LM Studio 类似 |
