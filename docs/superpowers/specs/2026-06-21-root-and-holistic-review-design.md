# 根级文件 + 整体审查设计文档

**生成日期**：2026-06-21
**目录范围**：`src/sqlseed/` 根级文件（4 个）+ 全量重新审查
**方法论**：9 步法

---

## 一、根级文件问题识别

### `__init__.py`（226 行）
- P1：无模块级 docstring
- P1：`fill_from_config` 函数（第 137-182 行）缺 docstring

### `_version.py`（9 行）
- P1：无模块级 docstring

### `AGENTS.md`（50 行）
- P2：无日期头
- P2：STRUCTURE 表格过时（generators 10→11 文件，plugins 2→4 文件，缺 `_version.py`/`py.typed`）
- P2：WHERE TO LOOK 中 base_provider 描述过时
- P2：CONVENTIONS 未提及多 DB 支持

### `py.typed`
- 无问题（PEP 561 空标记文件）

---

## 二、整体审查计划

### 2.1 全量验证
- `ruff check src/sqlseed/`
- `mypy src/sqlseed/`
- `python -m pytest tests/ -x --tb=short`

### 2.2 跨模块一致性检查
- docstring 语言一致性（全英文，遵循 PEP 8/257）
- AGENTS.md 格式一致性（`**Generated:** 2026-06-21`）
- 异常处理模式一致性（sqlalchemy.exc vs sqlite3）
- pylint 注释清理完整性

### 2.3 已优化目录完整性验证
- `_utils/`、`cli/`、`config/`、`core/`、`database/`、`generators/`、`plugins/`
- 确认所有修改未回退

---

## 三、3 智能体分工

### Agent A（根级 Python 文件 docstring）
- `__init__.py`：模块 docstring + `fill_from_config` docstring
- `_version.py`：模块 docstring

### Agent B（AGENTS.md 更新）
- `AGENTS.md`：日期头 + STRUCTURE 更新 + WHERE TO LOOK 修正 + CONVENTIONS 补充

### Agent C（全量重新审查 + 验证）
- 全量 ruff/mypy/pytest
- 跨模块一致性检查
- 已优化目录完整性验证
- 修复任何发现的问题

---

## 四、验证标准

| 命令 | 预期结果 |
|------|----------|
| `ruff check src/sqlseed/` | All checks passed |
| `mypy src/sqlseed/` | Success: no issues found |
| `python -m pytest tests/ -x --tb=short` | All tests passed |

---

## 五、YAGNI 清单（不做）

- ❌ 不重构 `__init__.py` 的公共 API 导出结构（当前 `__all__` 已完整）
- ❌ 不修改 `py.typed`（PEP 561 空标记文件，无需内容）
- ❌ 不为 `__init__.py` 中的私有函数 `_resolve_db_target` 添加更多文档（仅内部使用）

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 整体审查发现前序优化遗留问题 | 中 | 需要额外修复 | Agent C 负责修复并验证 |
| docstring 语言不一致（中英混合） | 低 | 已通过语言统一化设计文档解决 | 确认全英文 |
| AGENTS.md 格式不统一 | 低 | 已统一为 `**Generated:**` 格式 | Agent C 验证 |
