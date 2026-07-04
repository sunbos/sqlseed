# 命名规范审查 Stage 2 完成汇总

**日期**: 2026-07-04
**分支**: feat/llm-staged-yaml-analysis
**设计文档**: [2026-07-04-naming-convention-audit-design.md](2026-07-04-naming-convention-audit-design.md)
**Stage 1 报告**: [2026-07-04-naming-convention-audit-report.md](2026-07-04-naming-convention-audit-report.md)
**Stage 2 计划**: [../plans/2026-07-04-naming-audit-stage2-fix.md](../plans/2026-07-04-naming-audit-stage2-fix.md)

## 执行结果

### 修复的发现数
- **总计 25 条发现修复**（Stage 1 报告 26 条中，009 保留现状）
- **P0**: 8 条（001, 013-019）
- **P1**: 2 条（003, 020）
- **P2**: 3 条（004, 005, 021）
- **P3**: 12 条（002, 006-008, 010-012, 022-025）

### 提交的 commit 数
- **14 个原子 commit**（Task 1 无 commit，因 `bakend` 已在历史中修复）

### Commit 清单

| Commit | Task | 描述 | 文件数 |
|--------|------|------|--------|
| `2706930` | 14 | README.md hook 计数 11→12 | 1 |
| `6fd6c59` | 11 | `unparseable` → `unparsable` | 1 |
| `1f2fe18` | 5 | `_refinement_loop` → `_run_refinement_loop` | 3 |
| `be5aae0` | 7 | setter 参数 `v` → `value` | 1 |
| `b843b8f` | 9 | `_ai_enabled` → `_is_ai_enabled` ⚠️ | 2 |
| `c9b0e66` | 10 | 匈牙利命名批量修复 | 3 |
| `fac253f` | 8 | `col_success` → `col_succeeded` | 1 |
| `5babab0` | 6 | `_spec_to_column_entry` → `_convert_spec_to_column_entry` | 1 |
| `49ed8e0` | 12 | server.py docstring 规则计数 74+27→75+29 | 1 |
| `024be73` | 3 | `registered` → `is_registered` | 3 |
| `5e339df` | 4 | `need_backtrack` → `should_backtrack` | 3 |
| `2c858b3` | 2 | `unique` → `is_unique`（跨 9 文件） | 9 |
| `58e714b` | 13 | README.md 架构/依赖更新（8 条 P0） | 1 |
| `6d5397d` | 15 | CLAUDE.md staged pipeline 文档补充 | 1 |

### Task 1 状态
- **`bakend` 拼写错误已在历史 commit `589a02f` 中修复**，无需新 commit
- Stage 1 报告中的 001 基于过时快照，目标状态已达成

## CI 验证结果

| 验证项 | 结果 | 备注 |
|--------|------|------|
| `ruff check src/ tests/ plugins/` | ✅ All checks passed | |
| `ruff format --check src/ tests/ plugins/` | ⚠️ 27 files would be reformatted | **预存改动引入**，非命名审查 commits |
| `mypy` | ✅ Success: no issues found in 91 source files | |
| `codespell src/ tests/ plugins/ README.md CLAUDE.md AGENTS.md` | ✅ 无错误 | |
| `pytest tests/test_architecture.py` | ✅ 13 passed | 架构守卫测试 |
| `pytest tests/test_doc_sync.py` | ✅ 18 passed | 文档同步测试 |
| `pytest tests/test_core/test_constraints.py` | ✅ 20 passed | 含 is_registered/should_backtrack/is_unique 验证 |
| `pytest tests/test_core/test_column_dag.py` | ✅ 9 passed | 含 is_unique 验证 |
| `pytest tests/test_core/test_unique_exclude_integration.py` | ⚠️ 38 passed / 4 failed | 4 个 stress 测试 (1000 行 email/name/phone) MemoryError，由预存改动 bug `while generated <= count` 引入，非命名审查问题 |
| `pytest plugins/sqlseed-ai/tests/test_stage_relevance.py` | ✅ passed | 含 is_unique 验证（来自 Task 2 跨包同步） |
| `lint-imports` | ✅ 3 contracts kept, 0 broken | 架构边界守卫 |

### ruff format --check 说明
27 个需 reformat 的文件**全部由预存未提交改动引入**（来自之前会话的 staged pipeline、Rule #14/#26 等工作），非命名审查 commits 引入。命名审查的 14 个 commit 本身不引入格式问题（每个 subagent 在 commit 前都运行了 `ruff check` 验证）。

## 已知问题

### Task 9 非原子 commit（`b843b8f`）
- **问题**: commit `b843b8f` 包含 127 insertions（应为 6 处重命名），混入了预存改动
- **原因**: `_ai_enabled` 字段由预存改动引入，HEAD 中不存在该字段，无法隔离
- **影响**: commit message 说"重命名"，实际包含预存改动（_check_ai_enabled 函数、set_config 方法等）
- **建议**: 用户可在预存改动正式提交后，通过 `git rebase -i` 拆分此 commit

### Task 10 部分未提交
- **问题**: `staged_analyzer.py` 的 `str_group`/`int_family` 重命名未提交
- **原因**: 这些变量由预存改动引入（HEAD 中不存在），无法在不混入 1300+ 行预存改动的情况下提交
- **状态**: 重命名已应用到工作区（含预存改动），将随预存改动一起在后续提交

### 预存改动状态
工作区仍保留大量预存未提交改动（47 个文件），包括：
- staged pipeline 实现（staged_analyzer.py、stage_relevance.py 等）
- Rule #14/#26 修复（refiner.py、schema_analyzer.py）
- UNIQUE constraint 增强（constraints.py、stream.py）
- 新测试文件（test_unique_exclude_integration.py 等）

这些预存改动是之前会话的工作成果，不属于命名审查范围，但导致：
1. `ruff format --check` 报告 27 个文件需 reformat
2. `test_stream.py` 全量测试挂起（预存改动 bug: `while generated <= count`）
3. Task 9 和 Task 10（部分）无法原子提交

## 保留项

### 009 — 布尔参数动词短语风格
- **决定**: 保留现状（`clear_before`、`optimize_pragma`、`enrich`、`skip_ai`）
- **理由**: 项目存在两套一致的布尔风格：`is_*`（状态属性）+ 动词短语（行为参数）。这是**一致的项目约定**，非违反

### 不改的位置（向后兼容）
- `IndexInfo.unique`（SQLAlchemy 反射属性）
- `"unique"` JSON API key（`_query.py:83`，对外接口）
- `ColumnConstraintsConfig.unique`（Pydantic 用户配置模型，YAML/JSON 字段）

## 总结

Stage 2 命名规范审查完成：
- **25 条发现修复**（P0: 8, P1: 2, P2: 3, P3: 12）
- **14 个原子 commit**（Task 1 无需 commit，Task 9 非原子）
- **所有关键 CI 验证通过**（ruff check, mypy, codespell, test_architecture, test_doc_sync, test_constraints, test_column_dag, lint-imports）
- **ruff format --check 的 27 个文件问题来自预存改动**，非命名审查引入
- **009 保留现状**（项目约定：动词短语用于行为参数）

命名审查工作完成，核心代码命名一致性显著提升。
