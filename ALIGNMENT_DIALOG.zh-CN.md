# sqlseed 项目对齐对话记录

**创建日期：** 2026-06-26
**用途：** 用户与助手之间对齐对话的完整记录，供多智能体架构评审使用。本文档捕获完整对话轨迹、用户原始需求、所有决策点以及最终架构决策。
**状态：** 已就绪，可供多智能体评审

---

## 1. 背景

### 1.1 触发原因

用户识别出一个元问题：在执行任何代码层面的防腐防御（mock 自证陷阱修复、变异测试等）之前，项目的权威文档（CLAUDE.md、AGENTS.md、GEMINI.md）必须先与用户的实际需求对齐。否则所有防御机制保护的都是错误的目标。

### 1.2 用户的洞察

> "需要和用户对齐，这样才能保证CLAUDE、AGENTS、GEMINI相关文档和用户需求一致"

用户认识到：
1. ARCHITECTURE.md 是在对齐过程中作为新文件生成的，但 CLAUDE.md 和 AGENTS.md 仍包含过时内容（MySQL 引用、CLI 作为核心模块、AI 在核心中等）
2. 在同步到 CLAUDE.md/AGENTS.md 之前，对齐决策本身需要独立评审（多智能体评审），以确保它们代表最佳实践
3. 本文档捕获完整对齐对话供评审使用

---

## 2. 用户原始需求

用户声明了 5 项核心需求，构成所有架构决策的基础：

### 2.1 核心包范围

> "sqlseed是一个用于数据库测试库，只专注于为数据库写入合理的测试数据，其他功能不涉及"

sqlseed 是一个数据库测试数据库。它专注于为数据库写入合理的测试数据——不涉及其他功能。

### 2.2 AI 插件范围

> "sqlseed-ai 是用于ai辅助完成数据库生成的库，它属于sqlseed的一个插件，核心逻辑是完成yml文件的ai生成"

sqlseed-ai 是一个 AI 辅助的 sqlseed 插件。其核心逻辑是 AI 驱动的 YAML 文件生成。

### 2.3 MCP 插件范围

> "mcp-server-sqlseed是一个mcp插件，只专注于测试数据生成"

mcp-server-sqlseed 是一个专注于测试数据生成的 MCP 插件。

### 2.4 多数据库支持

> "以上插件要支持多数据库的测试数据生成，目前已经实现2种类型"

两个插件都必须支持多数据库测试数据生成。目前已实现 2 种类型。

### 2.5 微服务风格架构

> "项目整体架构类似于微服务架构，主要的核心功能保持不变...其他功能随着ai的发展可以使用插件的方式快速迭代"

项目架构类似微服务：核心功能保持稳定，其他功能以插件形式快速演进（特别是随着 AI 技术的发展）。

---

## 3. 对齐对话（6 轮）

### Round 1：核心架构边界

**用户关键陈述：**
- MCP 工具："gemma4相关功能我是知道的，但是从我之前的描述来看，你觉得放在这个mcp-server-sqlseed中合适吗...schema 检查首先要调研一下是否有相关的mcp功能是支持"
- 核心 AI 代码："这一层应该是涉及到了核心能力，当前需要保证用户入口支持：1.在没有sqlseed-ai的情况下，可以手动配置yml文件...2.一定要支持python api的调用...3.需要支持当下流行的CLI终端...4.cli、ai、MCP是可选功能...5.核心能力保证不变动"
- 多数据库状态："SQLite 是默认内置，PostgreSQL 是已完成的扩展；MySql暂时不添加，保证代码的整洁性...所以相关的内容需要删除"
- ai-suggest 位置："因为涉及到有部分用户不使用CLI功能，只使用Python代码功能，所以CLI为可选项，可以变为插件形式接入；ai也是，因为ai需要联网配置api，核心功能要保证离线也可以正常使用"

**Round 1 决策：**
- MCP gemma4 工具不属于 mcp-server-sqlseed（应在 sqlseed-ai 中）
- Schema 检查应调研（后续确认：使用现有成熟 MCP）
- 核心入口：Python API（必需）+ 手动 YAML（必需）+ CLI（可选）+ AI（可选）+ MCP（可选）
- MySQL：完全移除
- CLI：抽取为插件形式
- AI：必须是插件（需要网络）

---

### Round 2：插件发布策略

**用户关键陈述：**
- CLI 安装："你觉得怎样比较好从最优设计来看？因为我这里不是很懂...核心功能要保证长期稳定"
- 插件系统位置："这个涉及到明确的边界定义了，我从用户的使用角度（无感使用），核心功能直接sqlseed，想要安装特定的功能直接pip install sqlseed[需要安装的功能]"
- Mediator 拆分："我不太清楚这3个功能是什么作用，按照最佳实践来设计"
- MySQL 删除范围：选择"完全删除"

**Round 2 决策：**
- 插件系统（pluggy hookspecs + manager）作为基础设施保留在核心包中
- `core/plugin_mediator.py` 保留通用方法（`apply_batch_transforms`、`apply_template_pool`）；AI 专用的 `apply_ai_suggestions` 移至 sqlseed-ai
- MySQL：完全删除（不仅是禁用）
- 用户安装模式：`pip install sqlseed[feature]`

---

### Round 3：AI Enrichment 边界与 Gemma4 调研

**用户关键陈述：**
- Enrichment 拆分："使用AI插件的本质是需要网络进行调用...但是核心功能一定要保证离线可以正常使用不依赖外部网络。你可以按照最佳实践去帮我判断一下"
- Gemma4："相关功能我建议调研一下...1.https://github.com/gdgshanghai/Gemma4-Hackathon-ShangHai 这个是比赛的参考链接，当前我是要参加比赛...注意：首先要保证项目整体是纯净的，不能因为比赛所涉及到的代码而污染整个项目"
- MCP generate_yaml："保证MCP功能的专注，只做测试数据生成的相关功能"
- 补充："你还可以对我进行相关的提问，保证每一轮对话的问题有所收敛；但是不要因为收敛问题而减少提问问题的数量"

**Round 3 决策：**
- `core/enrichment.py`：将 `detect_enum_columns()`（本地计算）保留在核心；将 `apply_ai_enrichment()` 移至 sqlseed-ai
- Gemma4：需要调研（后续确认为在线和离线均可）
- MCP：专注于测试数据生成（不包含 schema 检查）
- Schema 检查：由现有 MCP 处理（mcp-database-server、mcp-db-analyzer）

---

### Round 4：Gemma4 隔离与测试组织

**用户关键陈述：**
- Gemma4 隔离："我觉得偏向于1和3，纠结选择哪一个比较好，是最佳实践对于整个项目来说"
- AI MCP 接口：选择"sqlseed-ai 自带 MCP"
- CLI entry_points："你说这个问题我又纠结了，纠结的点还是在于使用场景...如果按照核心功能可以离线使用的标准来看，sqlseed作为指令确实也没什么问题...所以还是需要你帮我判断一下...因为在以上2种情况来看，2就是1的子集了，我说的对吧？"
- 测试组织：选择"分离测试"

**Round 4 决策：**
- Gemma4 代码隔离以便移除（**后在 Round 6 修订**——见下文）
- sqlseed-ai 提供自己的 MCP 接口（`pip install sqlseed-ai[mcp]`）
- CLI：完全独立的插件（核心包无 `[project.scripts]`）
- 测试：核心测试保留在 `tests/`，插件测试移至 `plugins/*/tests/`

---

### Round 5：文档同步策略

**用户关键陈述：**
- "我认为当前时机有点不对，因为生成的文档，没有进行文档的项目评审；我的想法是，使用其他的智能体，结合你给我生成的文档和当前项目进行代码评审，保证当前设计为最佳实践"
- "应该是没有问题了，我的想法是把咱们之前从我开始要求你和我进行项目对齐的对话，生成一份文档；之后对这个文档，我会使用其他多智能体进行评审"
- "如果你还有相关需要和我对齐的，可以继续询问"

**Round 5 决策：**
- 暂不直接同步到 CLAUDE.md/AGENTS.md
- 先生成本对齐对话文档
- 用户将使用其他 AI agent 对本文档与实际项目进行评审
- 评审确认是最佳实践后，再同步到 CLAUDE.md/AGENTS.md/GEMINI.md

---

### Round 6：Gemma4 长期定位与 MCP 边界细化

**用户关键陈述：**
- Gemma4："Gemma4这个功能放在哪个位置，取决于做的是是否好；我认为如果做的很好的情况下，是不是完全可以作为插件去使用；比如我需要使用到gemma4的情况下安装插件即可，如果不需要，不安装也不会有影响；但是这里又涉及到了后续版本的维护性相关问题，比如后续如果出了新版本gemma5怎么办？后续怎么处理。相关gemma4问题取决于是否想要长期保留"
- sqlseed-cli："完全独立包，这个没有问题"
- MCP 边界："mcp-server-sqlseed和sqlseed-ai的交集部分sqlseed-ai[mcp]感觉还是有点模糊，在我看来yml生成是不是核心逻辑？ai和mcp只是辅助手段"
- MCP 在线/离线："纯离线用 mcp-server-sqlseed这句话描述的是不是不准确，因为如果我想要CLI接入MCP的情况下，它一般为在线吧，比如claude code接入MCP，所以MCP应该是在线离线都支持吧？"

**Gemma4 调研结果：**
- Gemma4 是 Apache 2.0 协议，无 MAU 限制——法律上可长期使用
- Gemma4 同时支持在线（Google AI Studio）和离线（Ollama/LM Studio）部署
- Gemma4 通过 6 个特殊 token（`<|tool>`、`<|tool_call>`、`<|tool_result>` 等）实现原生 Function Calling
- 多种模型尺寸：E2B (2.3B)、E4B (4.5B)、26B MoE、31B Dense

**Round 6 决策：**

1. **Gemma4 作为长期 LLM 后端**（修订自 Round 4 的"隔离以便移除"）：
   - Gemma4 **不是**比赛专用代码。它是长期受支持的 LLM 后端。
   - 不设 `sqlseed_ai/gemma4/` 子目录（避免暗示可移除性）。
   - Gemma4 原生 Function Calling 作为**协议实现**位于 `analyzer/_tool_calling.py` 中（`tool_calling_protocol="gemma4"`），与 `"openai"` 和 `"none"` 并列。
   - Gemma4 通过标准后端访问：`backend="ollama"` + `model="gemma4:26b"`，或 `backend="google_ai_studio"` + `model="gemma-4-..."`。
   - 不设 `backend="gemma4"` 配置——Gemma4 是模型，不是后端。
   - **Gemma5 过渡**：若 Gemma5 沿用相同 6 个特殊 token，零代码改动。若 Gemma5 更改 token，新增 `tool_calling_protocol="gemma5"`——无需移除 `"gemma4"`（向后兼容）。

2. **MCP 边界细化**（修订自 Round 4 的"在线/离线"划分）：
   - YAML 模板生成是一项**核心能力**（使用 `ColumnMapper`，74 条精确规则 + 27 个模式），不是 AI 功能。
   - **边界**：两个 MCP 之间的分界线是"是否需要 LLM 运行时"，**不是**"在线/离线"（MCP 协议对部署模式中立）。
   - **mcp-server-sqlseed**：`sqlseed_generate_yaml`（规则驱动，无 LLM）+ `sqlseed_execute_fill`。暴露核心能力。无论网络状态都能工作。
   - **sqlseed-ai[mcp]**：`sqlseed_ai_generate_yaml`（LLM 驱动）。暴露 AI 插件能力。需要 LLM 运行时（在线 API 或本地 Ollama/LM Studio）。
   - **交集定义**（两者都生成 YAML）：mcp-server-sqlseed = 规则驱动（可离线、确定性、适合简单 schema）；sqlseed-ai[mcp] = LLM 驱动（需要 LLM、适合需要语义推理的复杂 schema）。

3. **sqlseed-cli 发布**：确认为完全独立包（独立 pyproject.toml、独立版本号、独立发布）。与 sqlseed-ai 和 mcp-server-sqlseed 保持一致。

---

## 4. 最终架构决策（8 项）

### 决策 1：核心包稳定性

核心包（`sqlseed`）必须保持稳定且可离线使用。它包含：
- Python API：`fill`、`connect`、`preview`、`fill_from_config`、`load_config`
- 核心逻辑：orchestrator、mapper、schema、relation、column_dag、expression、constraints、transform、result、stream、unique_adjuster
- 生成器：faker（必需）、mimesis（可选）、base（仅类型路由）
- 数据库适配器：SQLAlchemy（必需，SQLite + PostgreSQL）、RawSQLite（仅测试）
- 插件基础设施：pluggy hookspecs + manager（作为基础设施保留在核心中）
- 配置：Pydantic 模型、YAML 加载器、SnapshotManager
- 工具：sql_safe、logger、metrics、progress、paths（无内部依赖）

### 决策 2：CLI 作为完全独立包

- `plugins/sqlseed-cli/`，拥有独立 `pyproject.toml`、独立版本号、独立发布
- 核心包**无** `[project.scripts]`
- `pip install sqlseed-cli` 提供 `sqlseed` 命令
- CLI 依赖：`sqlseed`（核心）+ `click` + `rich`
- 与 sqlseed-ai 和 mcp-server-sqlseed 一致（均为独立包）

### 决策 3：AI 代码完全移入插件

- 所有 AI 相关代码移至 `plugins/sqlseed-ai/`
- 核心零 AI 逻辑
- `core/enrichment.py` 仅保留 `detect_enum_columns()`（本地计算）
- `core/plugin_mediator.py` 仅保留通用方法（`apply_batch_transforms`、`apply_template_pool`）
- AI 专用的 `apply_ai_suggestions()` 和 `apply_ai_enrichment()` 移至 sqlseed-ai
- Orchestrator 通过 pluggy hook 调用 AI（`plugins.hook.sqlseed_ai_analyze_table()`）

### 决策 4：Gemma4 作为长期 LLM 后端

- Gemma4 **不是**比赛专用代码——它是长期受支持的 LLM 后端
- 不设 `gemma4/` 子目录（避免暗示可移除性）
- 原生 Function Calling 是 `analyzer/_tool_calling.py` 中可插拔的 `tool_calling_protocol`
- `AIConfig.backend` 使用 `"google_ai_studio"` / `"ollama"` / `"lm_studio"` / `"openai"`（**无** `"gemma4"`）
- Gemma4 通过标准后端 + 模型名访问（例如 `backend="ollama"`、`model="gemma4:26b"`）
- Gemma5 过渡：如需可新增协议选项（向后兼容）

### 决策 5：MySQL 完全删除

- 删除 `database/_dialect.py` 中的 MySQL 分支
- 删除 `database/_type_normalizer.py` 中的 MySQL 类型
- 删除 `pyproject.toml` 中的 `mysql` 可选依赖
- 删除测试和文档中的 MySQL 引用
- 理由：只实现了 SQLite + PostgreSQL；MySQL 推迟至 PostgreSQL 完全验证后再考虑

### 决策 6：MCP 边界按 LLM 依赖划分

- **mcp-server-sqlseed**：`sqlseed_generate_yaml`（规则驱动，无 LLM）+ `sqlseed_execute_fill`
  - 通过 MCP 暴露核心能力
  - **不**依赖任何 LLM
  - 无论网络状态都能工作（本地 stdio 或远程 HTTP）
- **sqlseed-ai[mcp]**：`sqlseed_ai_generate_yaml`（LLM 驱动）
  - 通过 MCP 暴露 AI 插件能力
  - 需要 LLM 运行时（在线 API 或本地 Ollama/LM Studio）
- **边界**："是否需要 LLM 运行时"，**不是**"在线/离线"
- **交集**：两者都生成 YAML，但 mcp-server-sqlseed 使用规则（确定性），sqlseed-ai[mcp] 使用 LLM（语义推理）
- Schema 检查已移除（使用现有 mcp-database-server / mcp-db-analyzer）

### 决策 7：YAML 模板生成是核心能力

- YAML 模板生成（使用 `ColumnMapper`，74 条精确规则 + 27 个模式）是一项**核心能力**
- AI YAML 生成是对复杂 schema 的**增强**
- 这就是 `sqlseed_generate_yaml` 属于 mcp-server-sqlseed（暴露核心），而不是 sqlseed-ai 的原因

### 决策 8：插件系统保留在核心中

- `src/sqlseed/plugins/`（hookspecs + manager）保留在核心包中
- 只有 AI 专用的 mediation 移出至 sqlseed-ai
- pluggy 是轻量级的，不影响核心稳定性
- 插件系统是"外部插件接入核心"的基础设施
- 没有它，sqlseed-ai/sqlseed-cli 无法集成

---

## 5. 安装矩阵

| 用例 | 安装命令 | 获得的能力 |
|----------|----------------|--------------|
| 仅 Python API（离线） | `pip install sqlseed` | `from sqlseed import fill` |
| + CLI | `pip install sqlseed-cli` | `sqlseed` 命令 |
| + AI YAML 生成 | `pip install sqlseed-ai` | `sqlseed ai-suggest` + Gemma4 支持 |
| + PostgreSQL | `pip install sqlseed[postgres]` | PostgreSQL 支持 |
| + mimesis（高性能） | `pip install sqlseed[mimesis]` | MimesisProvider |
| + MCP 服务器（核心能力） | `pip install mcp-server-sqlseed` | 基于规则的 YAML + fill 的 MCP 工具 |
| + AI MCP | `pip install sqlseed-ai[mcp]` | LLM 驱动 YAML 的 AI MCP 工具 |
| 全部 | 安装以上全部 | 所有可选功能 |

---

## 6. 数据库支持

| 数据库 | 状态 | 适配器 |
|----------|--------|---------|
| SQLite | ✅ 默认（内置） | `SQLAlchemyAdapter` |
| PostgreSQL | ✅ 已实现（扩展） | `SQLAlchemyAdapter` + `psycopg` |
| MySQL | ❌ 已移除（推迟至 PostgreSQL 完全验证后再考虑） | — |

---

## 7. 多智能体评审聚焦点

评审本文档时，多智能体评审者应聚焦于：

### 7.1 架构边界正确性

- mcp-server-sqlseed 与 sqlseed-ai[mcp] 之间以"LLM 依赖"作为分界线是否正确？
- YAML 模板生成被归类为核心能力（规则驱动）vs AI 增强（LLM 驱动）是否正确？
- 是否存在无法清晰归入"核心 vs 插件"划分的能力？

### 7.2 Gemma4 长期可行性

- 将 Gemma4 视为长期 LLM 后端（vs 比赛专用代码）是否正确？
- `tool_calling_protocol` 抽象（vs `backend="gemma4"`）是否是 Gemma5 过渡的正确设计？
- 长期保留 Gemma4 原生 Function Calling 代码是否存在风险？

### 7.3 插件独立性

- 完全独立包模式（每个插件有独立 pyproject.toml + 版本号）是否是最佳实践？
- sqlseed 核心与插件之间的版本兼容性应如何管理？
- 是否应有兼容性矩阵或版本约束？

### 7.4 核心稳定性

- 将 pluggy 插件系统保留在核心中是否违反"核心稳定性"原则？
- `detect_enum_columns()` 是否真正是本地计算，还是有隐藏的 AI 依赖？
- 是否还有其他核心模块应移至插件？

### 7.5 MCP 生态定位

- 鉴于现有 mcp-database-server / mcp-db-analyzer，MCP 范围（不含 schema 检查）是否正确？
- mcp-server-sqlseed 和 sqlseed-ai[mcp] 应合并还是保持分离？
- 交集定义（两者都生成 YAML，但规则驱动 vs LLM 驱动）是否足够清晰以防止代码漂移？

---

## 8. 已知问题

### 8.1 ARCHITECTURE.md 更新（已解决）

早期编辑会话遇到文件系统恢复问题：Edit 工具操作报告成功但内容回退。该问题通过用 Write 工具一次性重写整个文件解决。

所有章节现已反映 Round 6 对齐决策：
- Section 3.3（sqlseed-ai 插件）：✅ Gemma4 作为长期后端，`tool_calling_protocol` 抽象
- Section 3.4（mcp-server-sqlseed）：✅ MCP 边界按 LLM 依赖划分
- Section 7.4（Gemma4 决策）：✅ "Gemma4 as Long-term LLM Backend"
- Section 7.5（MCP 决策）：✅ "MCP Scope and Boundary"（不再是 "MCP Scope Narrowed"）
- Phase E：✅ "Gemma4 Protocol Abstraction"（不再是 "Gemma4 Isolation"）
- Section 10：✅ "Gemma4 Long-term Maintenance (No Post-Competition Cleanup)"

### 8.2 CLAUDE.md / AGENTS.md / GEMINI.md 尚未同步

按用户 Round 5 决策：
- 这些文件在多智能体评审确认设计为最佳实践前**不会**更新
- 评审通过后，对齐决策将同步到这三个文件
- GEMINI.md 是指向 CLAUDE.md 的指针（单一真相源模式）

---

## 9. 重构路线图（评审通过后）

多智能体评审确认设计后，在独立分支中执行：

### Phase A：MySQL 移除
- 删除 `database/_dialect.py` 中的 MySQL 分支
- 删除 `database/_type_normalizer.py` 中的 MySQL 类型
- 删除 `pyproject.toml` 中的 `mysql` 可选依赖
- 删除测试和文档中的 MySQL 引用

### Phase B：CLI 抽取
- 创建 `plugins/sqlseed-cli/` 包，拥有独立 `pyproject.toml`
- 将 `src/sqlseed/cli/` 移至 `plugins/sqlseed-cli/src/sqlseed_cli/`
- 将 `ai_commands.py` 移至 `plugins/sqlseed-ai/src/sqlseed_ai/cli/`
- 从核心 `pyproject.toml` 移除 `[project.scripts]`
- 将 CLI 测试移至 `plugins/sqlseed-cli/tests/`

### Phase C：AI 代码抽取
- 将 `core/enrichment.py` 中的 `apply_ai_enrichment()` 移至 `plugins/sqlseed-ai/`
- 将 `core/plugin_mediator.py` 中的 `apply_ai_suggestions()` 移至 `plugins/sqlseed-ai/`
- 将 `detect_enum_columns()` 保留在核心 `enrichment.py` 中
- 将 `apply_batch_transforms()` + `apply_template_pool()` 保留在核心 `plugin_mediator.py` 中
- Orchestrator 通过 pluggy hook 调用 AI

### Phase D：MCP 范围收窄
- 从 mcp-server-sqlseed 移除 `sqlseed_inspect_schema` 工具
- 移除 `sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill`、`sqlseed_list_gemma_models` 工具
- 移除 `sqlseed://schema` Resource
- 仅保留 `sqlseed_generate_yaml`（规则驱动）+ `sqlseed_execute_fill`
- 将 AI MCP 工具移至 `sqlseed-ai[mcp]`

### Phase E：Gemma4 协议抽象
- 确保 Gemma4 原生 Function Calling 作为协议实现位于 `analyzer/_tool_calling.py` 中
- 确保 `AIConfig.backend` 使用标准后端（无 `gemma4`）
- 确保 `AIConfig.tool_calling_protocol: Literal["gemma4", "openai", "none"]`
- **不设** `gemma4/` 子目录
- **无需**赛后清理（Gemma4 是长期后端）

### Phase F：测试重组
- 核心测试保留在 `tests/`
- 创建 `plugins/sqlseed-cli/tests/`
- 将 AI 测试移至 `plugins/sqlseed-ai/tests/`
- 将 MCP 测试移至 `plugins/mcp-server-sqlseed/tests/`
- 更新 CI 按包运行测试

### Phase G：文档同步（最终步骤）
- 用所有对齐决策更新 CLAUDE.md
- 用对应章节更新 AGENTS.md
- GEMINI.md 保持指向 CLAUDE.md 的指针
- 运行 `pytest tests/test_doc_sync.py` 验证一致性

---

## 10. 术语表

| 术语 | 定义 |
|------|-----------|
| 核心能力 (Core capability) | 无需 LLM 即可离线工作的功能，属于 sqlseed 核心包 |
| 插件能力 (Plugin capability) | 需要外部依赖（CLI 库、LLM、MCP 协议）的功能 |
| LLM 运行时 (LLM runtime) | 一个活跃的 LLM 服务（在线 API 如 Google AI Studio，或本地服务如 Ollama/LM Studio） |
| 原生 Function Calling (Native Function Calling) | Gemma4 通过 6 个特殊 token（`<|tool>`、`<|tool_call>`、`<|tool_result>` 等）实现的内置工具调用 |
| tool_calling_protocol | AIConfig 中用于原生 Function Calling 的可配置协议（`"gemma4"`、`"openai"`、`"none"`） |
| 规则驱动 YAML (Rule-driven YAML) | 使用 `ColumnMapper`（74 条精确规则 + 27 个模式）生成 YAML，无 LLM，确定性 |
| LLM 驱动 YAML (LLM-driven YAML) | 使用 LLM 分析 schema 生成 YAML，需要 LLM 运行时，语义推理 |
