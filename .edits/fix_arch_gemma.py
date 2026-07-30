"""Fix remaining docs: architecture.md EN, gemma4-integration EN/ZH."""
from __future__ import annotations
import sys
sys.path.insert(0, "/workspace")
from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# ---- docs/architecture.md MCP section (English) ----
edit(f"{ROOT}/docs/architecture.md",
     """## 10. MCP Server Architecture

```mermaid
flowchart LR
    subgraph Client["AI Assistant (Claude/Cursor/...)"]
        Request["MCP Request"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Resource["📖 Resource<br/>sqlseed://schema/{db}/{table}"]
        Tool1["🔍 sqlseed_inspect_schema<br/>Returns: columns + FK + indexes + samples + hash"]
        Tool2["🤖 sqlseed_generate_yaml<br/>AI analysis → self-correction → YAML"]
        Tool3["⚡ sqlseed_execute_fill<br/>Execute data generation"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 native function calling analysis"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>Gemma 4 agent-driven data fill"]
        Tool6["💎 sqlseed_list_gemma_models<br/>List available Gemma 4 models"]
    end

    subgraph SQLSeed["sqlseed Core"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Resource
    Request --> Tool1
    Request --> Tool2
    Request --> Tool3
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Resource --> SchemaCtx
    Tool1 --> SchemaCtx
    Tool2 --> SA --> ACR
    Tool3 --> Orchestrator
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```""",
     """## 10. MCP Server Architecture

Current dual-server architecture:

```mermaid
flowchart LR
    subgraph Client["AI Assistant (Claude/Cursor/...)"]
        Request["MCP Request"]
    end

    subgraph MCPServer["mcp-server-sqlseed (FastMCP)"]
        Tool1["🤖 sqlseed_generate_yaml<br/>Rule-driven → YAML"]
        Tool2["⚡ sqlseed_execute_fill<br/>Execute data generation"]
    end

    subgraph AIMCPServer["sqlseed-ai[mcp] (FastMCP)"]
        Tool3["🤖 sqlseed_ai_generate_yaml<br/>LLM-driven YAML generation"]
        Tool4["💎 sqlseed_gemma4_analyze<br/>Gemma 4 analysis"]
        Tool5["💎 sqlseed_gemma4_agent_fill<br/>End-to-end agent"]
        Tool6["💎 sqlseed_list_gemma_models<br/>Model list"]
    end

    subgraph SQLSeed["sqlseed Core"]
        Orchestrator["DataOrchestrator"]
        SchemaCtx["get_schema_context()"]
    end

    subgraph AIPlugin["sqlseed-ai"]
        SA["SchemaAnalyzer"]
        ACR["AiConfigRefiner"]
    end

    Request --> Tool1
    Request --> Tool2
    Request --> Tool3
    Request --> Tool4
    Request --> Tool5
    Request --> Tool6

    Tool1 --> SchemaCtx
    Tool2 --> Orchestrator
    Tool3 --> SA --> ACR
    Tool4 --> SA
    Tool5 --> Orchestrator
    Tool6 --> SA

    SchemaCtx --> Orchestrator
```""")

# ---- docs/gemma4-integration.md quickstart --backend ----
edit(f"{ROOT}/docs/gemma4-integration.md",
     "python scripts/quickstart.py --backend lm_studio --model google/gemma-4-e4b",
     "SQLSEED_AI_BACKEND=lm_studio python scripts/quickstart.py --model google/gemma-4-e4b")

edit(f"{ROOT}/docs/gemma4-integration.zh-CN.md",
     "python scripts/quickstart.py --backend lm_studio --model google/gemma-4-e4b",
     "SQLSEED_AI_BACKEND=lm_studio python scripts/quickstart.py --model google/gemma-4-e4b")

print("Done.")
