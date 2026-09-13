# 命名规范审查 Stage 2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按原子 commit 原则修复 Stage 1 报告中用户确认的 25 条命名规范发现（009 保留现状）。

**Architecture:** 每个重命名目标（定义 + 所有调用点 + 测试 + 文档）打包为单个 commit，确保每个 commit 独立 CI 绿色。使用 AST 感知工具（IDE Rename Symbol / rope），禁止纯文本正则全局替换。跨包重命名必须在同一 commit 中同步更新所有插件调用点。

**Tech Stack:** ruff, mypy, pytest, codespell, import-linter, AST 重构工具

**设计文档**: [docs/superpowers/specs/2026-07-04-naming-convention-audit-design.md](../specs/2026-07-04-naming-convention-audit-design.md)
**Stage 1 报告**: [docs/superpowers/specs/2026-07-04-naming-convention-audit-report.md](../specs/2026-07-04-naming-convention-audit-report.md)

---

## 通用约束（每个任务都必须遵守）

1. **AST 工具优先**: 使用 IDE Rename Symbol / rope / pyrefly 进行重命名，禁止 `sed` / `grep -r` 全局替换
2. **原子 commit**: 一个重命名目标 = 一个 commit（定义 + 调用点 + 测试 + 文档）
3. **跨包同步**: 核心包 `src/sqlseed/` 的公共 API 重命名必须在同一 commit 中同步更新所有插件调用点
4. **CI 验证**: 每个 commit 后必须运行：
   ```bash
   ruff check src/ tests/ plugins/
   ruff format --check src/ tests/ plugins/
   mypy
   pytest tests/test_architecture.py tests/test_doc_sync.py
   ```
5. **保留 `from __future__ import annotations`**: 所有修改文件首行必须保持
6. **代码注释/docstring 用英文**: 遵循项目惯例（PEP 8/257）

---

## 任务依赖关系

```
Task 1 (bakend) ──┐
Task 2 (is_unique) ─┤
Task 3 (is_registered) ─┤
Task 4 (should_backtrack) ─┤
Task 5 (_run_refinement_loop) ─┤
Task 6 (_convert_spec_to_column_entry) ─┤
Task 7 (setter v → value) ─┤
Task 8 (col_succeeded) ─┤
Task 9 (_is_ai_enabled) ─┤
Task 10 (匈牙利命名) ─┤
Task 11 (unparsable) ─┤
Task 12 (server docstring 计数) ─┤
Task 13 (README 架构更新) ─┤
Task 14 (README hook 计数) ─┤
Task 15 (CLAUDE.md staged pipeline) ─┤
                        │
                        ▼
                 Task 16 (最终 CI 全量验证)
```

Task 1-15 之间无强依赖（不同文件/不同标识符），但建议按顺序执行以便 review。Task 16 必须最后执行。

---

## Task 1: 修复 `bakend` 拼写错误（发现 001）

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py:125`

- [ ] **Step 1: 使用 AST 工具重命名 `bakend` → `backend`**

修改 `_model_selector.py:125`：
```python
# 修改前
to_model=next_model.to_backend_id(backend) if bakend else next_model.value,
# 修改后
to_model=next_model.to_backend_id(backend) if backend else next_model.value,
```

注意：这是局部变量，仅在 logger.info 调用中使用。同函数第 127 行已正确使用 `backend`。

- [ ] **Step 2: 验证 ruff + codespell**

Run: `ruff check plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
Expected: All checks passed

Run: `codespell plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
Expected: 无输出（无拼写错误）

- [ ] **Step 3: 验证 mypy + pytest**

Run: `mypy plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py`
Expected: Success

Run: `pytest plugins/sqlseed-ai/tests/ -k "model_selector or fallback" -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/_model_selector.py
git commit -m "fix(naming): correct 'bakend' typo to 'backend' in _model_selector.py

Fixes Stage 1 finding 001 (S1, P0). The misspelled variable 'bakend'
would raise NameError at INFO log level, breaking Gemma 4 model
fallback logic. ruff F821 and codespell both flagged this."
```

---

## Task 2: 统一 `unique` → `is_unique`（发现 003）

**Files:**
- Modify: `src/sqlseed/core/column_dag.py:21,93,109`
- Modify: `src/sqlseed/core/constraints.py:75,82,89,102,115,122`
- Modify: `src/sqlseed/core/features.py:104,242`
- Modify: `src/sqlseed/core/stream.py:171,345`
- Modify: `tests/test_core/test_constraints.py`（如有相关测试）
- Modify: `tests/test_core/test_column_dag.py`（如有相关测试）
- Modify: `tests/test_core/test_stream.py`（如有相关测试）

**注意**: 以下位置**不改**（SQLAlchemy `IndexInfo.unique` 反射属性 / 对外 JSON API key）：
- `src/sqlseed/core/schema.py:77` — `idx.unique` 是 `IndexInfo.unique`（SQLAlchemy 反射）
- `src/sqlseed/core/features.py:235` — `idx.unique` 是 `IndexInfo.unique`
- `src/sqlseed/core/orchestrator/_query.py:83` — `"unique": idx.unique` 是对外 JSON API key，保持兼容

- [ ] **Step 1: 使用 AST 工具重命名 `ColumnConstraints.unique` → `is_unique`**

在 `column_dag.py:21`：
```python
# 修改前
@dataclass
class ColumnConstraints:
    unique: bool = False
# 修改后
@dataclass
class ColumnConstraints:
    is_unique: bool = False
```

同步更新 `column_dag.py:93,109` 的字段访问。

- [ ] **Step 2: 重命名 `constraints.py` 中的函数参数 `unique` → `is_unique`**

`constraints.py:75,82,89,102,115,122` — 所有 `unique: bool = False` 参数及 docstring 中的引用。

- [ ] **Step 3: 重命名 `features.py:104` 的 `IndexFeatures.unique` → `is_unique`**

```python
# 修改前
@dataclass
class IndexFeatures:
    unique: bool
# 修改后
@dataclass
class IndexFeatures:
    is_unique: bool
```

同步更新 `features.py:242`：`is_unique=idx.unique`（注意：`idx.unique` 保留，是 SQLAlchemy 属性）。

- [ ] **Step 4: 更新 `stream.py` 调用点**

`stream.py:171`：
```python
# 修改前
is_unique = node.constraints.unique if node.constraints else False
# 修改后
is_unique = node.constraints.is_unique if node.constraints else False
```

`stream.py:345`：
```python
# 修改前
if not n.is_skip and n.constraints and n.constraints.unique
# 修改后
if not n.is_skip and n.constraints and n.constraints.is_unique
```

- [ ] **Step 5: 更新测试文件**

搜索测试文件中对 `unique=` / `.unique` 的访问，统一改为 `is_unique`。

- [ ] **Step 6: 验证 CI 全套**

Run: `ruff check src/ tests/`
Run: `ruff format --check src/ tests/`
Run: `mypy`
Run: `pytest tests/test_core/ -v`

- [ ] **Step 7: Commit**

```bash
git add src/sqlseed/core/column_dag.py src/sqlseed/core/constraints.py \
        src/sqlseed/core/features.py src/sqlseed/core/stream.py \
        tests/test_core/
git commit -m "refactor(naming): rename 'unique' to 'is_unique' for boolean consistency

Fixes Stage 1 finding 003 (C1, P1). Unifies the boolean naming style
across ColumnConstraints, IndexFeatures, and ConstraintSolver methods
to match the project's 'is_*' convention for state attributes.

Note: IndexInfo.unique (SQLAlchemy reflection) and the 'unique' JSON
API key in _query.py:83 are intentionally preserved for backward
compatibility."
```

---

## Task 3: 重命名 `registered` → `is_registered`（发现 004）

**Files:**
- Modify: `src/sqlseed/core/constraints.py:19`
- Modify: `src/sqlseed/core/stream.py:199`
- Modify: `tests/test_core/test_constraints.py`（如有）

- [ ] **Step 1: 重命名 `RegisterResult.registered` → `is_registered`**

`constraints.py:19`：
```python
# 修改前
@dataclass
class RegisterResult:
    registered: bool = True
# 修改后
@dataclass
class RegisterResult:
    is_registered: bool = True
```

- [ ] **Step 2: 更新 `stream.py:199`**

```python
# 修改前
if result.registered:
# 修改后
if result.is_registered:
```

- [ ] **Step 3: 更新测试文件**

搜索 `result.registered` / `registered=` 改为 `is_registered`。

- [ ] **Step 4: 验证 + Commit**

Run: `ruff check src/ tests/ && mypy && pytest tests/test_core/test_constraints.py -v`

```bash
git add src/sqlseed/core/constraints.py src/sqlseed/core/stream.py tests/test_core/
git commit -m "refactor(naming): rename 'registered' to 'is_registered' in RegisterResult

Fixes Stage 1 finding 004 (C4, P2). Aligns with project's 'is_*'
boolean naming convention for state attributes."
```

---

## Task 4: 重命名 `need_backtrack` → `should_backtrack`（发现 005）

**Files:**
- Modify: `src/sqlseed/core/constraints.py:20,120,131`
- Modify: `src/sqlseed/core/stream.py:204`
- Modify: `tests/test_core/test_constraints.py:27`

- [ ] **Step 1: 重命名 `RegisterResult.need_backtrack` → `should_backtrack`**

`constraints.py:20`：
```python
# 修改前
need_backtrack: bool = False
# 修改后
should_backtrack: bool = False
```

- [ ] **Step 2: 更新 docstring 和构造调用**

`constraints.py:120`（docstring）：`need_backtrack=True` → `should_backtrack=True`
`constraints.py:131`：`need_backtrack=True` → `should_backtrack=True`

- [ ] **Step 3: 更新 `stream.py:204`**

```python
# 修改前
if result.need_backtrack and source_columns:
# 修改后
if result.should_backtrack and source_columns:
```

- [ ] **Step 4: 更新测试 `test_constraints.py:27`**

```python
# 修改前
assert result.need_backtrack is True
# 修改后
assert result.should_backtrack is True
```

- [ ] **Step 5: 验证 + Commit**

Run: `ruff check src/ tests/ && mypy && pytest tests/test_core/ -v`

```bash
git add src/sqlseed/core/constraints.py src/sqlseed/core/stream.py tests/test_core/test_constraints.py
git commit -m "refactor(naming): rename 'need_backtrack' to 'should_backtrack'

Fixes Stage 1 finding 005 (C4, P2). Adds 'should_' prefix for
boolean action flag and fixes subject-verb agreement ('need' vs
'needs'). Aligns with project's 'should_*'/'is_*' convention."
```

---

## Task 5: 重命名 `_refinement_loop` → `_run_refinement_loop`（发现 006）

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:339,434,464`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md:50`

- [ ] **Step 1: 使用 AST 工具重命名方法**

`refiner.py:339`（定义）：`def _refinement_loop(` → `def _run_refinement_loop(`
`refiner.py:434,464`（调用）：`self._refinement_loop(` → `self._run_refinement_loop(`

- [ ] **Step 2: 更新 AGENTS.md:50**

```markdown
<!-- 修改前 -->
| Tune retry / refinement loop | `refiner.py` | `_refinement_loop()`, `_try_prompt_levels()` |
<!-- 修改后 -->
| Tune retry / refinement loop | `refiner.py` | `_run_refinement_loop()`, `_try_prompt_levels()` |
```

- [ ] **Step 3: 验证 + Commit**

Run: `ruff check plugins/sqlseed-ai/ && mypy plugins/sqlseed-ai/ && pytest plugins/sqlseed-ai/tests/ -v`

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/refiner.py plugins/sqlseed-ai/src/sqlseed_ai/AGENTS.md
git commit -m "refactor(naming): rename '_refinement_loop' to '_run_refinement_loop'

Fixes Stage 1 finding 006 (C3, P3). Adds verb prefix to match the
naming style of sibling methods (_handle_*, _check_*, _apply_*)."
```

---

## Task 6: 重命名 `_spec_to_column_entry` → `_convert_spec_to_column_entry`（发现 007）

**Files:**
- Modify: `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py:35,62`

- [ ] **Step 1: 使用 AST 工具重命名函数**

`server.py:35`（定义）：`def _spec_to_column_entry(` → `def _convert_spec_to_column_entry(`
`server.py:62`（调用）：`_spec_to_column_entry(name, spec)` → `_convert_spec_to_column_entry(name, spec)`

- [ ] **Step 2: 验证 + Commit**

Run: `ruff check plugins/mcp-server-sqlseed/ && mypy plugins/mcp-server-sqlseed/ && pytest plugins/mcp-server-sqlseed/tests/ -v`

```bash
git add plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py
git commit -m "refactor(naming): rename '_spec_to_column_entry' to '_convert_spec_to_column_entry'

Fixes Stage 1 finding 007 (C3, P3). Adds explicit verb 'convert' to
match Python function naming convention (verb-first)."
```

---

## Task 7: 重命名 setter 参数 `v` → `value`（发现 008）

**Files:**
- Modify: `src/sqlseed/core/orchestrator/_connection.py:137,145`

- [ ] **Step 1: 重命名 setter 参数**

`_connection.py:137`：
```python
# 修改前
@plugin_mediator.setter
def plugin_mediator(self, v: PluginMediator | None) -> None: ...
# 修改后
@plugin_mediator.setter
def plugin_mediator(self, value: PluginMediator | None) -> None: ...
```

`_connection.py:145`：
```python
# 修改前
@enrichment.setter
def enrichment(self, v: EnrichmentEngine | None) -> None: ...
# 修改后
@enrichment.setter
def enrichment(self, value: EnrichmentEngine | None) -> None: ...
```

如果 setter 内部使用了 `v`，需同步改为 `value`。

- [ ] **Step 2: 验证 + Commit**

Run: `ruff check src/sqlseed/core/orchestrator/ && mypy && pytest tests/test_core/ -v`

```bash
git add src/sqlseed/core/orchestrator/_connection.py
git commit -m "refactor(naming): rename setter parameter 'v' to 'value'

Fixes Stage 1 finding 008 (C5, P3). 'value' is the Python convention
for setter parameters; 'v' is non-descriptive."
```

---

## Task 8: 重命名 `col_success` → `col_succeeded`（发现 010）

**Files:**
- Modify: `src/sqlseed/core/stream.py:281,286`

- [ ] **Step 1: 使用 AST 工具重命名局部变量**

`stream.py:281`：
```python
# 修改前
col_success, new_backtrack_to = self._attempt_node_generation(node, row, generated_values)
# 修改后
col_succeeded, new_backtrack_to = self._attempt_node_generation(node, row, generated_values)
```

`stream.py:286`：
```python
# 修改前
if not col_success:
# 修改后
if not col_succeeded:
```

注意：`_attempt_node_generation` 的返回值是元组解包，第一个元素是 bool。需检查该方法是否在别处被调用（如果是，需同步更新解包变量名，但变量名是局部的，不影响函数签名）。

- [ ] **Step 2: 验证 + Commit**

Run: `ruff check src/sqlseed/core/stream.py && mypy && pytest tests/test_core/test_stream.py -v`

```bash
git add src/sqlseed/core/stream.py
git commit -m "refactor(naming): rename 'col_success' to 'col_succeeded'

Fixes Stage 1 finding 010 (C4, P3). Aligns with the 'is_*'/'succeeded'
boolean naming style; nearby is_unique (L171) already uses the prefix."
```

---

## Task 9: 重命名 `_ai_enabled` → `_is_ai_enabled`（发现 011）

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/__init__.py:123,129,136,238,311`
- Modify: `plugins/sqlseed-ai/tests/test_ai_plugin_init.py:125`

**注意**: `_check_ai_enabled()` 函数名（L68）**不改** — 它已经有动词 `check`，符合命名规范。

- [ ] **Step 1: 使用 AST 工具重命名字段**

`__init__.py:123`：
```python
# 修改前
self._ai_enabled: bool = _check_ai_enabled()
# 修改后
self._is_ai_enabled: bool = _check_ai_enabled()
```

`__init__.py:129`（docstring）：`_ai_enabled` → `_is_ai_enabled`
`__init__.py:136`：`self._ai_enabled = True` → `self._is_ai_enabled = True`
`__init__.py:238`：`if not self._ai_enabled:` → `if not self._is_ai_enabled:`
`__init__.py:311`：同上

- [ ] **Step 2: 更新测试**

`test_ai_plugin_init.py:125`：`plugin._ai_enabled = True` → `plugin._is_ai_enabled = True`

- [ ] **Step 3: 验证 + Commit**

Run: `ruff check plugins/sqlseed-ai/ && mypy plugins/sqlseed-ai/ && pytest plugins/sqlseed-ai/tests/ -v`

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/__init__.py plugins/sqlseed-ai/tests/test_ai_plugin_init.py
git commit -m "refactor(naming): rename '_ai_enabled' to '_is_ai_enabled'

Fixes Stage 1 finding 011 (C4, P3). Aligns state attribute with
project's 'is_*' boolean naming convention. The _check_ai_enabled()
function name is preserved (already verb-prefixed)."
```

---

## Task 10: 修复匈牙利命名（发现 012）

**Files:**
- Modify: `src/sqlseed/core/transform.py:37,42,44` — `fn_any` → `transform_fn_any`
- Modify: `src/sqlseed/core/mapper.py:386,387` — `str_group` → `string_generators`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py:1616,1902,1903` — `str_group` → `string_generators`, `int_family` → `integer_types`
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:235,237` — `param_err` → `parameter_error`

- [ ] **Step 1: 重命名 `transform.py` 的 `fn_any`**

`transform.py:37,42,44` — 使用 AST 工具重命名局部变量 `fn_any` → `transform_fn_any`。

- [ ] **Step 2: 重命名 `mapper.py` 的 `str_group`**

`mapper.py:386,387` — `str_group` → `string_generators`（局部变量）。

- [ ] **Step 3: 重命名 `staged_analyzer.py` 的 `str_group` 和 `int_family`**

`staged_analyzer.py:1616`（docstring）：`str_group` → `string_generators`
`staged_analyzer.py:1902,1903`：`int_family` → `integer_types`（局部变量）

- [ ] **Step 4: 重命名 `_caller.py` 的 `param_err`**

`_caller.py:235,237`：
```python
# 修改前
except APIError as param_err:
    classified = classify_api_error(param_err)
# 修改后
except APIError as parameter_error:
    classified = classify_api_error(parameter_error)
```

- [ ] **Step 5: 验证 + Commit**

Run: `ruff check src/sqlseed/core/ plugins/sqlseed-ai/ && mypy && pytest tests/test_core/ plugins/sqlseed-ai/tests/ -v`

```bash
git add src/sqlseed/core/transform.py src/sqlseed/core/mapper.py \
        plugins/sqlseed-ai/src/sqlseed_ai/staged_analyzer.py \
        plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py
git commit -m "refactor(naming): rename Hungarian-notation variables to semantic names

Fixes Stage 1 finding 012 (C7, P3). Renames:
- fn_any -> transform_fn_any (transform.py)
- str_group -> string_generators (mapper.py, staged_analyzer.py)
- int_family -> integer_types (staged_analyzer.py)
- param_err -> parameter_error (_caller.py)

Improves readability without changing behavior."
```

---

## Task 11: 修复 `unparseable` → `unparsable`（发现 002）

**Files:**
- Modify: `plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py:973`

- [ ] **Step 1: 修改 docstring**

`schema_analyzer.py:973`：
```python
# 修改前
E2B sometimes return empty content or unparseable text on the first
# 修改后
E2B sometimes return empty content or unparsable text on the first
```

- [ ] **Step 2: 验证 + Commit**

Run: `codespell plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py`
Expected: 无 `unparseable` 报告

```bash
git add plugins/sqlseed-ai/src/sqlseed_ai/schema_analyzer.py
git commit -m "docs(naming): fix 'unparseable' to 'unparsable' in schema_analyzer docstring

Fixes Stage 1 finding 002 (S3, P3). codespell flagged this as a
common misspelling; 'unparsable' is the strictly correct form."
```

---

## Task 12: 修复 server.py docstring 规则计数（发现 021）

**Files:**
- Modify: `plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py:49`

- [ ] **Step 1: 修改 docstring 计数**

`server.py:49`：
```python
# 修改前
"""...Uses sqlseed's core ``ColumnMapper`` (74 exact rules + 27 regex patterns)..."""
# 修改后
"""...Uses sqlseed's core ``ColumnMapper`` (75 exact rules + 29 regex patterns)..."""
```

- [ ] **Step 2: 验证计数与 mapper.py 一致**

Run: `pytest tests/test_doc_sync.py -v`
Expected: PASS（doc sync 测试会验证 count markers）

- [ ] **Step 3: Commit**

```bash
git add plugins/mcp-server-sqlseed/src/mcp_server_sqlseed/server.py
git commit -m "docs(naming): fix ColumnMapper rule count in server.py docstring

Fixes Stage 1 finding 021 (D4, P2). Updates '74 exact + 27 regex' to
'75 exact + 29 regex' to match the actual count in mapper.py and
CLAUDE.md AUTO-GENERATED count markers."
```

---

## Task 13: 更新 README.md 架构/依赖（发现 013-019, 024）

**Files:**
- Modify: `README.md:140-153,768,790-796,1001,1019,1029-1030,1043,1071,1074`

这是文档批量更新，作为一个原子 commit。

- [ ] **Step 1: 修复 013 — orchestrator 架构图**

`README.md:1001`：
```
<!-- 修改前 -->
orchestrator.py  # DataOrchestrator main engine
<!-- 修改后 -->
orchestrator/    # DataOrchestrator package (4 mixins + 1 shared data module)
  __init__.py
  _common.py
  _connection.py
  _specs.py
  _generation.py
  _query.py
```

- [ ] **Step 2: 修复 014 — 移除 src/sqlseed/cli/ 引用**

`README.md:1029-1030`：从 `src/sqlseed/` 部分移除 `cli/` 子目录，确保 `plugins/sqlseed-cli/` 单独文档化。

- [ ] **Step 3: 修复 015 — 移除 MySQL 引用**

`README.md:140-153,1074`：移除所有 `sqlseed[mysql]`、MySQL 功能列表条目。

- [ ] **Step 4: 修复 016 — faker 是必需依赖**

`README.md:1071`：移除 `sqlseed[faker]` extra，改为 `pip install sqlseed`（faker 已包含）。

- [ ] **Step 5: 修复 017 — mcp 安装命令**

`README.md:768`：`pip install mcp-server-sqlseed[ai]` → `pip install sqlseed-ai[mcp]`

- [ ] **Step 6: 修复 018 — MCP Capabilities 表**

`README.md:790-796`：重写表格：
- mcp-server-sqlseed: 2 tools (`sqlseed_generate_yaml`, `sqlseed_execute_fill`), 0 Resources
- sqlseed-ai[mcp]: 4 tools (`sqlseed_ai_generate_yaml`, `sqlseed_gemma4_analyze`, `sqlseed_gemma4_agent_fill`, `sqlseed_list_gemma_models`), 0 Resources

- [ ] **Step 7: 修复 019 — 移除 sqlseed_inspect_schema**

`README.md:1043`：
```
<!-- 修改前 -->
mcp-server-sqlseed
  server.py  # Tools: sqlseed_inspect_schema, sqlseed_generate_yaml, sqlseed_execute_fill
<!-- 修改后 -->
mcp-server-sqlseed
  server.py  # Tools: sqlseed_generate_yaml, sqlseed_execute_fill
```

- [ ] **Step 8: 修复 024 — sqlalchemy_adapter 注释**

`README.md:1019`：
```
<!-- 修改前 -->
sqlalchemy_adapter.py  # Default adapter (SQLite/PostgreSQL/MySQL)
<!-- 修改后 -->
sqlalchemy_adapter.py  # Default adapter (SQLite/PostgreSQL)
```

- [ ] **Step 9: 验证 doc sync + Commit**

Run: `pytest tests/test_doc_sync.py -v`
Run: `codespell README.md`

```bash
git add README.md
git commit -m "docs(naming): update README.md architecture and dependencies

Fixes Stage 1 findings 013-019, 024 (D1/D2/D3/D8, P0/P3):
- 013: orchestrator.py -> orchestrator/ package
- 014: remove src/sqlseed/cli/ (moved to plugins/sqlseed-cli/ in Phase B)
- 015: remove MySQL references (MySQL removed)
- 016: faker is required, not optional
- 017: mcp-server-sqlseed[ai] -> sqlseed-ai[mcp]
- 018: rewrite MCP Capabilities table (2+4 tools, 0 Resources)
- 019: remove sqlseed_inspect_schema (removed in Phase D)
- 024: remove MySQL from sqlalchemy_adapter comment

Aligns README.md with CLAUDE.md and pyproject.toml."
```

---

## Task 14: 修复 README.md hook 计数（发现 020）

**Files:**
- Modify: `README.md:100`

- [ ] **Step 1: 修改 hook 计数**

`README.md:100`：
```markdown
<!-- 修改前 -->
🧩 11 Lifecycle Hooks
<!-- 修改后 -->
🧩 12 Lifecycle Hooks
```

- [ ] **Step 2: 验证 doc sync + Commit**

Run: `pytest tests/test_doc_sync.py -v`

```bash
git add README.md
git commit -m "docs(naming): fix lifecycle hook count in README.md

Fixes Stage 1 finding 020 (D4, P1). Updates '11 Lifecycle Hooks' to
'12' to match hookspecs.py (12 hooks) and CLAUDE.md L135."
```

---

## Task 15: 补充 CLAUDE.md staged pipeline 文档（发现 022, 023, 025）

**Files:**
- Modify: `CLAUDE.md`（多处章节）

- [ ] **Step 1: 修复 022 — 补充 sqlseed-ai 文件列表**

在 CLAUDE.md "Plugins (separate packages)" 章节的 sqlseed-ai 文件列表中添加：
- `staged_analyzer.py` — Staged schema analysis pipeline (3-stage)
- `schema_analyzer.py` — Legacy schema analyzer
- `stage_relevance.py` — Stage relevance scoring
- `dependency_resolver.py` — Column dependency resolution
- `_stage_prompts.py` — Stage-specific prompt templates

- [ ] **Step 2: 修复 023 — 文档化 Rule #14 和 Rule #26**

在 CLAUDE.md 新增 "Staged Pipeline" 子章节：
```markdown
### Staged Pipeline (sqlseed-ai)

- `StagedSchemaAnalyzer` — Entry point, flag-gated (use_staged_analyzer)
- `Stage3Validator` — Rule-based validation (#14-#16)
- Rule #14 — Parameter whitelist stripping (removes invalid params like
  `domain` from `email` generator)
- Rule #26 — INTEGER column random_float -> random_int coercion
```

- [ ] **Step 3: 修复 025 — 在 Key Modules 中添加 staged pipeline 类**

在 CLAUDE.md "Key Modules" 章节为 `StagedSchemaAnalyzer` 和 `Stage3Validator` 新增条目。

- [ ] **Step 4: 验证 + Commit**

Run: `pytest tests/test_doc_sync.py -v`

```bash
git add CLAUDE.md
git commit -m "docs(naming): document staged pipeline in CLAUDE.md

Fixes Stage 1 findings 022, 023, 025 (D2/D7, P3):
- 022: add staged_analyzer.py, schema_analyzer.py, stage_relevance.py,
  dependency_resolver.py, _stage_prompts.py to file list
- 023: document StagedSchemaAnalyzer, Stage3Validator, Rule #14, Rule #26
- 025: add staged pipeline classes to Key Modules section"
```

---

## Task 16: 最终 CI 全量验证

**Files:** 无修改 — 仅验证

- [ ] **Step 1: 运行完整 CI 本地等价验证**

```bash
# Lint
ruff check src/ tests/ plugins/
ruff format --check src/ tests/ plugins/

# Type check
mypy

# Tests
pytest

# Architecture guard tests
pytest tests/test_architecture.py -v

# Doc sync tests
pytest tests/test_doc_sync.py -v

# Import linter
lint-imports

# Spelling
codespell src/ tests/ plugins/ docs/ README.md CLAUDE.md AGENTS.md
```

- [ ] **Step 2: 验证 CI 工作流文件**

确认 `.github/workflows/ci.yml` 中的所有步骤在本地等价验证中全部通过。

- [ ] **Step 3: 生成最终汇总报告**

创建 `docs/superpowers/specs/2026-07-04-naming-audit-stage2-summary.md`，记录：
- 修复的发现数（25 条）
- 提交的 commit 数（15 个）
- CI 验证结果
- 残留问题（如有）

- [ ] **Step 4: 最终 Commit**

```bash
git add docs/superpowers/specs/2026-07-04-naming-audit-stage2-summary.md
git commit -m "docs(naming-audit): add Stage 2 completion summary

Stage 2 of naming convention audit complete:
- 25 findings fixed (P0: 8, P1: 2, P2: 3, P3: 12)
- 15 atomic commits (one rename target per commit)
- 009 preserved (project convention: verb-phrase for action params)
- All CI checks green: ruff, mypy, pytest, test_architecture, test_doc_sync, lint-imports, codespell"
```

---

## 自我审查清单

- [x] **Spec coverage**: Stage 1 报告 26 条发现中 25 条有对应 Task（009 保留现状，已说明）
- [x] **Placeholder scan**: 无 TBD/TODO，每个 Step 都有具体代码或命令
- [x] **Type consistency**: 重命名后的标识符在所有 Task 中一致（如 `is_unique` 在 Task 2 中统一使用）
- [x] **AST 工具要求**: 每个 Task Step 1 都明确要求使用 AST 工具
- [x] **原子 commit**: 每个 Task 一个 commit，commit message 遵循 Conventional Commits
- [x] **跨包同步**: Task 2-4 涉及核心包，已列出所有插件调用点（实际上这些标识符未被插件引用，但已检查）
- [x] **CI 验证**: 每个 Task 都有验证步骤，Task 16 是最终全量验证

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-07-04-naming-audit-stage2-fix.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 每个 Task 派发独立 subagent，任务间 review，快速迭代

**2. Inline Execution** - 在当前会话中按 executing-plans 批量执行，带 checkpoint review

**Which approach?**
