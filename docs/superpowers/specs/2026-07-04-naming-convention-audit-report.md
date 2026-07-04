# 命名规范审查报告

**日期**: 2026-07-04
**审查方式**: 4 层扫描（ruff + codespell + grep + 人工 Read + 文档反向验证）
**设计文档**: [docs/superpowers/specs/2026-07-04-naming-convention-audit-design.md](2026-07-04-naming-convention-audit-design.md)
**状态**: 等待用户逐项确认

## 汇总统计

| 维度 | P0 | P1 | P2 | P3 | 小计 |
|------|----|----|----|----|------|
| S 拼写 | 1 | 0 | 0 | 1 | 2 |
| P PEP 8 | 0 | 0 | 0 | 0 | 0 |
| C 一致性 | 0 | 1 | 2 | 8 | 11 |
| F 文件组织 | 0 | 0 | 0 | 0 | 0 |
| PC 项目惯例 | 0 | 0 | 0 | 0 | 0 |
| D 文档对齐 | 7 | 1 | 1 | 4 | 13 |
| **合计** | **8** | **2** | **3** | **13** | **26** |

## 报告阅读说明

用户对每条发现标记：
- `✓` 同意修复
- `✗` 不同意（保留现状）
- `?` 需讨论

确认后，将按原子 commit 原则（一个重命名目标一个 commit）实施修复，遵循设计文档 §6.3.2。

---

## 1. 拼写与语法（S 类）

### 001 | S1 | P0 | plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py:125

**问题**: 变量名 `bakend` 拼写错误（应为 `backend`）。
**当前代码**:
```python
to_model=next_model.to_backend_id(backend) if bakend else next_model.value,
```
**建议**: 将 `bakend` 改为 `backend`。
**理由**: 拼写错误（S1）。ruff F821（未定义名称）和 codespell 同时命中。同函数第 127 行已正确拼写为 `backend`。该错误被 structlog 在 WARNING 级别下的 no-op 行为掩盖，一旦在 INFO 级别触发会抛出 `NameError`，导致 Gemma 4 模型回退逻辑失效。
**影响范围**: 1 处调用点（之前会话可能已修复，需验证当前状态）。
**状态**: `?`（需验证当前状态）

### 002 | S3 | P3 | plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py:973

**问题**: docstring 中使用 `unparseable`（codespell 建议改为 `unparsable`）。
**当前代码**: docstring 包含 "unparseable"
**建议**: 可选修改：改为 `unparsable`，或保留（两种写法在技术语境中都被广泛使用）。
**理由**: S3（注释/docstring 拼写）。`unparseable` 在技术英语中可接受；`unparsable` 是更严格正确的形式。
**影响范围**: 1 处 docstring。
**状态**: `?`

---

## 2. PEP 8 命名约定（P 类）

✓ 无发现。`ruff check src/ plugins/ --select=N` 报告 "All checks passed!" — 所有类名（PascalCase）、函数/方法/变量名（snake_case）、常量（UPPER_CASE）、类型别名（PascalCase）、私有成员 `_` 前缀均符合 PEP 8。

---

## 3. 一致性与可读性（C 类）

### 003 | C1 | P1 | src/sqlseed/core/column_dag.py:21 vs src/sqlseed/core/enrichment.py:209

**问题**: 同一概念"列是否唯一"在不同文件中命名不一致。
**当前代码**:
- `column_dag.py:21`: `unique: bool = False`（在 `ColumnConstraints` 数据类中）
- `enrichment.py:209`: `is_unique: bool = False`（函数参数）
- `constraints.py:35,75,102`: `unique: bool = False`（函数参数）

**建议**: 统一为 `is_unique: bool`（与代码库中 `is_derived`、`is_computed`、`is_strict`、`is_without_rowid` 的 `is_*` 形容词风格一致）。
**理由**: C1（跨文件一致性）。同一概念应使用同一名称。
**影响范围**: 跨 3 个文件约 5 处调用点。
**状态**: `?`

### 004 | C4 | P2 | src/sqlseed/core/constraints.py:19

**问题**: 布尔字段 `registered` 缺少 `is_` 前缀。
**当前代码**:
```python
@dataclass
class RegisterResult:
    registered: bool = True
```
**建议**: 重命名为 `is_registered: bool = True`。
**理由**: C4（布尔命名）。项目对状态属性使用 `is_*` 风格（`is_derived`、`is_computed`、`is_strict`）。
**影响范围**: `stream.py` 及其他调用者约 5 处字段访问。
**状态**: `?`

### 005 | C4 | P2 | src/sqlseed/core/constraints.py:20

**问题**: 布尔字段 `need_backtrack` 缺少 `is_/should_` 前缀，且主谓不一致。
**当前代码**:
```python
need_backtrack: bool = False
```
**建议**: 重命名为 `should_backtrack: bool = False`（或 `needs_backtrack`）。
**理由**: C4（布尔命名）。`need` vs `needs` 主谓不一致；项目风格偏好 `should_*`/`is_*` 前缀。
**影响范围**: `stream.py` 约 3 处字段访问。
**状态**: `?`

### 006 | C3 | P3 | plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:339

**问题**: 方法名 `_refinement_loop` 是名词短语，缺少动词前缀。
**当前代码**: `def _refinement_loop(self, ...)`
**建议**: 重命名为 `_run_refinement_loop`。
**理由**: C3（函数名应以动词开头）。类中其他方法均使用动词前缀：`_handle_*`、`_check_*`、`_apply_*`。
**影响范围**: 1 处调用点（内部方法）。
**状态**: `?`

### 007 | C3 | P3 | plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py:35

**问题**: 函数名 `_spec_to_column_entry` 使用 `_X_to_Y` 模式，无显式动词。
**当前代码**: `def _spec_to_column_entry(...)`
**建议**: 重命名为 `_convert_spec_to_column_entry` 或 `_build_column_entry_from_spec`。
**理由**: C3（函数名应以动词开头，如 convert/build）。
**影响范围**: 1 处调用点（内部函数）。
**状态**: `?`

### 008 | C5 | P3 | src/sqlseed/core/orchestrator/_connection.py:137,145

**问题**: setter 参数使用单字母名 `v`。
**当前代码**:
```python
@plugin_mediator.setter
def plugin_mediator(self, v: PluginMediator | None) -> None: ...
@enrichment.setter
def enrichment(self, v: EnrichmentEngine | None) -> None: ...
```
**建议**: 将 `v` 改为 `value`（setter 参数的 Python 惯例）或领域相关名称（`mediator`、`enrichment`）。
**理由**: C5（参数名应直观）。单字母 `v` 不具描述性；`value` 是 Python setter 的惯例。
**影响范围**: 2 处 setter 定义。
**状态**: `?`

### 009 | C4 | P3 | src/sqlseed/__init__.py:51-55（及其他 12 处）

**问题**: 布尔 API 参数使用动词短语风格（`clear_before`、`optimize_pragma`、`enrich`、`skip_ai`），无 `is_/should_` 前缀。
**当前代码**:
```python
def fill(..., clear_before: bool = False, optimize_pragma: bool = True, enrich: bool = True, skip_ai: bool = True):
```
**建议**: 两种选项：
- (a) 保持现状（动词短语风格是 Python 控制行为参数的合理惯例，与 Click flag 名一致）
- (b) 重命名为 `should_clear_before`、`should_optimize_pragma`、`should_enrich`、`should_skip_ai`

**理由**: C4。项目存在两套布尔风格并存：`is_*`（状态属性）和动词短语（行为参数）。这是**一致的项目约定**，非违反。
**影响范围**: 跨 `__init__.py`、`config/models.py`、`orchestrator/_connection.py`、`_generation.py`、`_specs.py`、`mapper.py`、CLI `main.py` 共 14 处。
**状态**: `?`（建议 `✗` 保留 — 约定一致且动词短语对行为开关更地道）

### 010 | C4 | P3 | src/sqlseed/core/stream.py:281

**问题**: 局部布尔变量 `col_success` 缺少 `is_` 前缀。
**当前代码**: `col_success = ...`（局部变量）
**建议**: 重命名为 `is_col_success` 或 `col_succeeded`。
**理由**: C4。注意：附近的 `is_unique`（第 171 行）正确使用了前缀。
**影响范围**: 1 处局部变量。
**状态**: `?`

### 011 | C4 | P3 | plugins/sqlseed-ai/src/sqlseed_ai/__init__.py:123

**问题**: 布尔属性 `_ai_enabled` 缺少 `is_` 前缀。
**当前代码**: `_ai_enabled: bool`
**建议**: 重命名为 `_is_ai_enabled: bool`。
**理由**: C4。状态属性应使用 `is_*` 风格。
**影响范围**: 约 3 处内部访问。
**状态**: `?`

### 012 | C7 | P3 | src/sqlseed/core/transform.py:37,42,44 及其他位置

**问题**: 语义类型前缀变量（轻度匈牙利命名）。
**当前代码**:
- `transform.py:37,42,44`: `fn_any`（类型收窄中间变量）
- `mapper.py:386,387`: `str_group`（字符串生成器集合）
- `staged_analyzer.py:1616`: `str_group`
- `staged_analyzer.py:1902,1903`: `int_family`
- `analyzer/_caller.py:235,237`: `param_err`

**建议**: 重命名为语义化名称：
- `fn_any` → `transform_fn_any` 或 `raw_transform_fn`
- `str_group` → `string_generators`
- `int_family` → `integer_types`
- `param_err` → `parameter_error`

**理由**: C7（避免匈牙利命名）。这些是语义类型前缀，非纯匈牙利，但可读性可优化。
**影响范围**: 跨 4 个文件 7 处局部变量。
**状态**: `?`

---

## 4. 文件/模块组织（F 类）

✓ 无发现。所有模块遵循单一职责原则（F3），私有模块使用 `_` 前缀（F2），模块名反映职责（F1）。

---

## 5. 项目惯例（PC 类）

✓ 无发现。所有文件首行有 `from __future__ import annotations`（PC3），logger 使用 `logger = get_logger(__name__)`（PC4），测试文件遵循 `test_<module>.py` 约定（PC1/PC2）。

---

## 6. 文档对齐（D 类）

### 013 | D1/D8 | P0 | README.md:1001

**问题**: 架构图将 `orchestrator.py` 描述为单文件；实际是 `orchestrator/` 包。
**当前代码**（README.md L1001）:
```
orchestrator.py  # DataOrchestrator main engine
```
**建议**: 更新为：
```
orchestrator/    # DataOrchestrator 包（4 个 mixin + 1 个共享数据模块）
  __init__.py
  _common.py
  _connection.py
  _specs.py
  _generation.py
  _query.py
```
**理由**: D1（路径存在性），D8（架构描述）。CLAUDE.md L80 正确描述为包。
**影响范围**: 1 处架构图块。
**状态**: `?`

### 014 | D1/D8 | P0 | README.md:1029-1030

**问题**: 架构图显示 `src/sqlseed/cli/` 目录；实际位置是 `plugins/sqlseed-cli/`。
**当前代码**（README.md L1029-1030）:
```
cli/
  main.py  # Click commands: fill, preview, inspect, init, replay, ai-suggest
```
**建议**: 从 `src/sqlseed/` 部分移除 `cli/`；确保 `plugins/sqlseed-cli/` 单独文档化。
**理由**: D1/D8。CLI 在 Phase B 迁移到插件（CLAUDE.md L107）。
**影响范围**: 1 处架构图块。
**状态**: `?`

### 015 | D8 | P0 | README.md:140-153,1074

**问题**: README 声称支持 MySQL（`sqlseed[mysql]`）；MySQL 已被移除。
**当前代码**: README 提到 `sqlseed[mysql]` 可选依赖和功能列表中的 MySQL。
**建议**: 移除所有 MySQL 引用。MySQL 已移除（推迟到 PostgreSQL 完全验证后，见 CLAUDE.md L7）。
**理由**: D8。`pyproject.toml` 无 `mysql` extra；CLAUDE.md L7 明确说明移除。
**影响范围**: README 约 2 个章节。
**状态**: `?`

### 016 | D3 | P0 | README.md:1071

**问题**: README 将 `sqlseed[faker]` 列为可选依赖；faker 是必需的核心依赖。
**当前代码**: `pip install sqlseed[faker]`
**建议**: 移除 `[faker]` extra；将 faker 文档化为必需：`pip install sqlseed`（faker 已包含）。
**理由**: D3。`pyproject.toml` L38 将 `faker>=30.0` 列入核心 `dependencies`；CLAUDE.md L275 确认 "faker is a required core dependency"。
**影响范围**: 1 处安装说明。
**状态**: `?`

### 017 | D3 | P0 | README.md:768

**问题**: 安装命令 `pip install mcp-server-sqlseed[ai]` 无效；不存在 `[ai]` extra。
**当前代码**: `pip install mcp-server-sqlseed[ai]`
**建议**: 改为 `pip install sqlseed-ai[mcp]`（AI MCP 工具在 sqlseed-ai 中，而非 mcp-server-sqlseed）。
**理由**: D3。`mcp-server-sqlseed/pyproject.toml` 无 `[ai]` extra；CLAUDE.md L270 文档化为 `sqlseed-ai[mcp]`。
**影响范围**: 1 处安装命令。
**状态**: `?`

### 018 | D2/D8 | P0 | README.md:790-796

**问题**: MCP Capabilities 表列出 6 个工具（含已移除的 `sqlseed_inspect_schema`）和 1 个 Resource；实际 mcp-server-sqlseed 有 2 个工具，0 个 Resource。
**当前代码**: 表格列出 `sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill`、AI 工具及 `sqlseed://schema/{db_path}/{table_name}` Resource。
**建议**: 重写表格：
- mcp-server-sqlseed: 2 个工具（`sqlseed_generate_yaml`、`sqlseed_execute_fill`），0 个 Resource
- sqlseed-ai[mcp]: 4 个工具（`sqlseed_ai_generate_yaml`、`sqlseed_gemma4_analyze`、`sqlseed_gemma4_agent_fill`、`sqlseed_list_gemma_models`），0 个 Resource

**理由**: D2/D8。`sqlseed_inspect_schema` 已在 Phase D 移除；CLAUDE.md L271 确认 "No Resources"。
**影响范围**: 1 处能力表格。
**状态**: `?`

### 019 | D2 | P0 | README.md:1043

**问题**: 架构图将 `sqlseed_inspect_schema` 列为 mcp-server-sqlseed 工具；该工具已移除。
**当前代码**:
```
mcp-server-sqlseed
  server.py  # Tools: sqlseed_inspect_schema, sqlseed_generate_yaml, sqlseed_execute_fill
```
**建议**: 移除 `sqlseed_inspect_schema`：
```
mcp-server-sqlseed
  server.py  # Tools: sqlseed_generate_yaml, sqlseed_execute_fill
```
**理由**: D2。工具在 Phase D 移除。
**影响范围**: 1 行架构图。
**状态**: `?`

### 020 | D4 | P1 | README.md:100

**问题**: README 声称 "11 Lifecycle Hooks"；实际为 12 个。
**当前代码**: "🧩 11 Lifecycle Hooks"
**建议**: 改为 "🧩 12 Lifecycle Hooks"。
**理由**: D4。`hookspecs.py` 定义 12 个 hook；CLAUDE.md L135 和 README.md L976（自相矛盾）均写 12。
**影响范围**: 1 处徽章/文本。
**状态**: `?`

### 021 | D4 | P2 | plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py:49

**问题**: docstring 写 "74 exact rules + 27 regex patterns"；实际为 75 + 29。
**当前代码**:
```python
"""...Uses sqlseed's core ``ColumnMapper`` (74 exact rules + 27 regex patterns)..."""
```
**建议**: 改为 "75 exact rules + 29 regex patterns"。
**理由**: D4。`mapper.py` 有 75 条 EXACT_MATCH_RULES 和 29 条 PATTERN_MATCH_RULES；CLAUDE.md count markers 确认。
**影响范围**: 1 处 docstring。
**状态**: `?`

### 022 | D2 | P3 | CLAUDE.md:270

**问题**: CLAUDE.md 列出 sqlseed-ai 包文件但遗漏 `staged_analyzer.py`、`schema_analyzer.py`、`stage_relevance.py`、`dependency_resolver.py`、`_stage_prompts.py`。
**当前代码**: "Plugins (separate packages)" 章节的文件列表遗漏这些文件。
**建议**: 将遗漏的文件添加到列表，附简短描述。
**理由**: D2。这些文件在代码中存在但未文档化。
**影响范围**: 1 处文档章节。
**状态**: `?`

### 023 | D7 | P3 | CLAUDE.md（多处章节）

**问题**: CLAUDE.md 未文档化 `Stage3Validator`、`StagedSchemaAnalyzer` 类及 Rule #14/#26 行为。
**当前代码**: 未提及这些 staged pipeline 组件。
**建议**: 新增 "Staged Pipeline" 子章节，文档化：
- `StagedSchemaAnalyzer`（入口点，flag 切换）
- `Stage3Validator`（规则 #14-#16）
- Rule #14（参数白名单剥离）
- Rule #26（INTEGER 列 random_float → random_int 强制转换）

**理由**: D7。规则在代码中存在（`staged_analyzer.py:938`、`staged_analyzer.py:1307`）但未在文档中。
**影响范围**: 多处文档章节。
**状态**: `?`

### 024 | D8 | P3 | README.md:1019

**问题**: `sqlalchemy_adapter.py` 的架构图注释提及 MySQL；MySQL 已移除。
**当前代码**:
```
sqlalchemy_adapter.py  # Default adapter (SQLite/PostgreSQL/MySQL)
```
**建议**: 移除 MySQL：
```
sqlalchemy_adapter.py  # Default adapter (SQLite/PostgreSQL)
```
**理由**: D8。MySQL 按 CLAUDE.md L7 移除。
**影响范围**: 1 行架构图。
**状态**: `?`

### 025 | D2 | P3 | CLAUDE.md（Key Modules 章节）

**问题**: CLAUDE.md "Key Modules" 章节未提及 `StagedSchemaAnalyzer` 和 `Stage3Validator`。
**当前代码**: 章节列出 `SchemaSemanticAnalyzer`（legacy）但无 staged pipeline 类。
**建议**: 为 staged pipeline 类新增条目。
**理由**: D2。新的 staged pipeline 类在 spec 中文档化但未在 CLAUDE.md key modules 中。
**影响范围**: 1 处文档章节。
**状态**: `?`

---

## 交叉引用汇总

### 按优先级

**P0（严重 — 8 项）**:
- 001: `bakend` 拼写错误（S1）— **需验证是否已修复**
- 013-019: README.md 架构/依赖错误（D1/D2/D3/D8）

**P1（高 — 2 项）**:
- 003: `unique` vs `is_unique` 跨文件不一致（C1）
- 020: README.md hook 计数错误（D4）

**P2（中 — 3 项）**:
- 004: `registered` 缺 `is_` 前缀（C4）
- 005: `need_backtrack` 缺前缀 + 主谓不一致（C4）
- 021: server.py docstring 规则计数错误（D4）

**P3（低 — 13 项）**:
- 002: `unparseable` docstring（S3）
- 006-012: C3/C4/C5/C7 风格优化
- 022-025: CLAUDE.md/README.md 文档补充（D2/D7/D8）

### 按文件

| 文件 | 发现 ID |
|------|---------|
| `plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py` | 001 |
| `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py` | 002 |
| `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py` | 006 |
| `plugins/sqlseed-ai/src/sqlseed_ai/__init__.py` | 011 |
| `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py` | 012 |
| `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py` | 012 |
| `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py` | 007, 021 |
| `src/sqlseed/__init__.py` | 009 |
| `src/sqlseed/core/column_dag.py` | 003 |
| `src/sqlseed/core/constraints.py` | 003, 004, 005 |
| `src/sqlseed/core/enrichment.py` | 003 |
| `src/sqlseed/core/stream.py` | 010 |
| `src/sqlseed/core/transform.py` | 012 |
| `src/sqlseed/core/mapper.py` | 012 |
| `src/sqlseed/core/orchestrator/_connection.py` | 008, 009 |
| `README.md` | 013, 014, 015, 016, 017, 018, 019, 020, 024 |
| `CLAUDE.md` | 022, 023, 025 |

---

## 下一步

1. **用户审阅本报告**，对每条标记 `✓` / `✗` / `?`。
2. 对 `?` 项进行深入讨论以达成共识。
3. 全部确认后，创建 **Stage 2 实施计划**，按原子 commit 原则（一个重命名目标一个 commit，遵循设计文档 §6.3.2）修复所有确认项。
4. 使用 AST 感知工具（设计文档 §6.3.1）和跨包同步（§6.3.3）执行 Stage 2。
5. 最终 CI 验证（设计文档 §7）。
