# 语言统一设计文档：全英文转换

**生成日期**：2026-06-21
**范围**：`src/sqlseed/` 全部文件
**目标**：遵循 Python PEP 8/257 规范，将所有中文 docstring/注释/AGENTS.md 转为英文
**优先级**：此文档要求覆盖前序文档（generators/plugins）中的中文 docstring 要求

---

## 一、背景

在之前的优化过程中，我将许多英文 docstring 转为中文，但 log/error/CLI 消息仍是英文。这造成：
1. 中文 docstring 与英文错误消息割裂
2. 违反 Python 生态约定（PEP 8/257）
3. 国际贡献者难以维护

**注意**：前序设计文档（generators、plugins）中要求 docstring 转中文的方案已被本文档取代。最终执行以本文档为准——全英文。

## 二、转换范围

| 转换项 | 说明 |
|--------|------|
| 中文 docstring → 英文 | 模块/类/方法级 docstring |
| 中文注释 → 英文 | `#` 行注释 |
| 中文 AGENTS.md → 英文 | 8 个文件 |
| **不转换** | log/error/CLI 消息（已是英文） |
| **不转换** | `docs/superpowers/specs/` 设计文档（历史记录，保持中文） |

## 三、执行方案：逐目录转换

按以下顺序逐目录转换，每个目录完成后验证：

| 顺序 | 目录 | 文件数 | 验证命令 |
|------|------|--------|----------|
| 1 | `_utils/` | 7 + AGENTS.md | `ruff check src/sqlseed/_utils/` + `mypy` + `pytest tests/` |
| 2 | `cli/` | 4 + AGENTS.md | 同上 |
| 3 | `config/` | 5 + AGENTS.md | 同上 |
| 4 | `core/` | 14 + AGENTS.md | 同上 |
| 5 | `database/` | 11 + AGENTS.md | 同上 |
| 6 | `generators/` | 11 + AGENTS.md | 同上 |
| 7 | `plugins/` | 4 + AGENTS.md | 同上 |
| 8 | 根级文件 | `__init__.py` + `_version.py` + `AGENTS.md` | 全量验证 |

## 四、3 智能体分工

由于语言转换不涉及逻辑变更，采用逐目录串行执行（非 3 智能体并行），每个目录完成后立即验证：
- **执行者**：按目录顺序逐个转换
- **验证**：每个目录完成后运行 ruff + mypy + pytest

## 五、转换原则

1. **保持原意**：中文 docstring 的语义内容完整保留，仅语言切换
2. **简洁专业**：使用标准 Python docstring 英语风格
3. **不修改逻辑**：仅转换文本，不修改任何业务逻辑
4. **AGENTS.md 格式**：保持 `**Generated:** 2026-06-21` 日期头，内容转英文

## 六、验证标准

每个目录转换后：
- `ruff check` 通过
- `mypy` 通过
- `pytest` 通过（相关测试）

全部完成后：
- 全量 `ruff check src/sqlseed/` 通过
- 全量 `mypy src/sqlseed/` 通过
- 全量 `pytest tests/` 通过

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 英文翻译不准确导致语义偏差 | 低 | docstring 误导 | 保持原意，使用标准 Python docstring 风格 |
| 转换过程中意外修改逻辑代码 | 极低 | 运行时错误 | 仅修改 docstring/注释/AGENTS.md，不触碰逻辑代码 |
| ruff E501 行长度超限 | 中 | lint 失败 | 拆分长 docstring 行，使用 summary-line + body 风格 |
| 前序文档中文要求与本文档冲突 | 已解决 | 已通过本文档覆盖 | 以本文档为准，全英文 |

---

## 八、YAGNI 清单（不做）

- ❌ 不转换 log/error/CLI 消息（已是英文）
- ❌ 不转换 `docs/superpowers/specs/` 设计文档（历史记录）
- ❌ 不在转换过程中重构代码逻辑
- ❌ 不添加新的 docstring（仅转换已有的中文 docstring）
