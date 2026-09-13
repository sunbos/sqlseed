# 方法论优化设计文档

**生成日期**：2026-06-23
**范围**：22 项方法论的优化升级，以 worktree 竞争+融合为核心
**目标**：解决 3 智能体模式的文件污染问题，升级 9 步流程、验证 gate、设计文档驱动、风险管理体系
**约束**：以 `feat/multi-db-support` 为合并目标分支（非 `main`）；向后兼容现有方法论

---

## 一、背景

### 1.1 当前方法论概述

当前项目积累了 22 项方法论，覆盖从设计到验证的全生命周期：

- **核心框架**（3 项）：9 步优化流程、3 智能体交叉执行、设计文档驱动开发
- **代码质量**（3 项）：PEP 8/257 规范、纯函数约定、类型安全渐进式改进
- **架构重构**（3 项）：模块拆分、死代码清理、3 层 Prompt 系统
- **测试**（3 项）：测试覆盖矩阵分析、平铺式测试文件组织、测试隔离原则
- **文档**（2 项）：文档与代码一致性审查、AGENTS.md 格式规范
- **验证**（2 项）：3 层验证 gate、回归测试
- **风险管理**（2 项）：影响分析前置、YAGNI 清单
- **Git 工作流**（2 项）：feat/* 分支策略、commit 粒度要求

### 1.2 问题识别

当前 3 智能体交叉执行模式存在核心缺陷：

- **Agent A 和 Agent B 在同一个工作目录中同时修改文件**
- 如果两个智能体修改了同一个文件（或文件有交叉依赖），会导致文件污染
- 分工模式依赖设计阶段预分配文件，灵活性低
- 无法充分利用"竞争带来更优解"的优势

### 1.3 优化方向

用户提出以 **worktree 竞争+融合** 为核心，重新设计 3 智能体模式：

- Agent A 和 Agent B 各自在独立 worktree 中完成**同一个任务**
- Agent C 在工作过程中持续检查中间结果
- 全部完成后，Agent C 比较两个实现，**融合两者优点**
- 最终结果合并到 `feat/multi-db-support` 分支

---

## 二、架构概述

### 2.1 Worktree 竞争+融合模式核心架构

```
c:\Users\14435\Desktop\sqlseed\              # 主工作目录（feat/multi-db-support）
c:\Users\14435\Desktop\sqlseed-worktree-a\  # Agent A worktree（feat/multi-db-support-agent-a）
c:\Users\14435\Desktop\sqlseed-worktree-b\  # Agent B worktree（feat/multi-db-support-agent-b）
```

### 2.2 工作流程

1. **创建阶段**：从 `feat/multi-db-support` 分支创建两个 worktree（agent-a、agent-b）
2. **竞争阶段**：Agent A 和 Agent B 各自在独立 worktree 中完成同一个任务
3. **持续检查阶段**：Agent C 在工作过程中定期检查两个 worktree 的中间结果（通过 git diff）
4. **融合阶段**：Agent C 比较两个实现，融合两者优点，生成最终版本
5. **合并阶段**：将融合结果合并到 `feat/multi-db-support` 分支
6. **清理阶段**：删除两个 worktree 和临时分支

### 2.3 关键原则

- Agent A 和 B **做同一件事**，不是分工
- Agent C **融合两者优点**，不是二选一
- 合并目标是 `feat/multi-db-support`，不是 `main`
- Agent C **持续检查**，不是事后才介入

---

## 三、3 智能体模式升级

### 3.1 从"分工合作"到"竞争+融合"

**旧模式（分工合作）**：
- Agent A 改文件集 X，Agent B 改文件集 Y，Agent C 验证
- 问题：同一工作目录，文件污染风险；分工依赖设计阶段预分配

**新模式（竞争+融合）**：

| 智能体 | 职责 | worktree | 分支 |
|--------|------|----------|------|
| **Agent A** | 独立完成完整任务 | `sqlseed-worktree-a` | `feat/multi-db-support-agent-a` |
| **Agent B** | 独立完成同一个任务 | `sqlseed-worktree-b` | `feat/multi-db-support-agent-b` |
| **Agent C** | 持续检查 + 融合 + 合并 | 主目录 | `feat/multi-db-support` |

### 3.2 具体操作流程

**Step 1 — 创建 worktree**：

```powershell
git worktree add ../sqlseed-worktree-a -b feat/multi-db-support-agent-a
git worktree add ../sqlseed-worktree-b -b feat/multi-db-support-agent-b
```

**Step 2 — Agent A/B 并行竞争**：
- Agent A 在 `sqlseed-worktree-a` 中独立完成任务
- Agent B 在 `sqlseed-worktree-b` 中独立完成同一个任务
- 两者互不干扰，文件完全隔离

**Step 3 — Agent C 持续检查**：
- Agent C 定期运行 `git diff feat/multi-db-support-agent-a` 和 `git diff feat/multi-db-support-agent-b` 查看中间结果
- 发现明显错误时，及时通知对应智能体修正
- 不干预实现方式，只检查正确性

**Step 4 — Agent C 融合**：
- Agent C 比较两个实现的差异（`git diff feat/multi-db-support-agent-a feat/multi-db-support-agent-b`）
- 逐文件评估：A 的更好 / B 的更好 / 两者各有优点需融合
- 融合策略：以较好的实现为基底，cherry-pick 另一个的优点

**Step 5 — 合并到主分支**：

```powershell
# 在主目录中
git checkout feat/multi-db-support
git merge feat/multi-db-support-agent-a  # 或手动应用融合结果
```

**Step 6 — 清理 worktree**：

```powershell
git worktree remove ../sqlseed-worktree-a
git worktree remove ../sqlseed-worktree-b
git branch -D feat/multi-db-support-agent-a feat/multi-db-support-agent-b
```

### 3.3 Agent C 融合决策矩阵

| 情况 | 策略 |
|------|------|
| A 和 B 实现一致 | 直接选 A（任意一个） |
| A 明显优于 B | 选 A，检查 B 是否有可借鉴的小改进 |
| B 明显优于 A | 选 B，检查 A 是否有可借鉴的小改进 |
| 各有优点 | 以较好的为基底，cherry-pick 另一个的优点 |
| 都有问题 | Agent C 自行修正，记录两个版本的教训 |

---

## 四、9 步流程适配

### 4.1 升级后的 9 步流程

**旧流程**：

```
read → identify → brainstorm → clarify → design → review → 3-agent cross-execute → apply → validate
```

**新流程**：

```
read → identify → brainstorm → clarify → design → review → worktree 竞争+融合 → apply → validate
```

### 4.2 各步骤详细说明

| 步骤 | 名称 | 变化 | 说明 |
|------|------|------|------|
| 1 | **read** | 不变 | 阅读相关代码和文档 |
| 2 | **identify** | 不变 | 识别问题和优化点 |
| 3 | **brainstorm** | 不变 | 头脑风暴，使用 brainstorming skill |
| 4 | **clarify** | 不变 | 澄清需求，一次一个问题 |
| 5 | **design** | 不变 | 设计方案，分章节呈现 |
| 6 | **review** | 不变 | 审查设计 |
| 7 | **worktree 竞争+融合** | **升级** | 替代原"3-agent cross-execute"：Agent A/B 在独立 worktree 竞争，Agent C 持续检查+融合 |
| 8 | **apply** | **调整** | 从"应用变更"调整为"将融合结果合并到 feat/multi-db-support" |
| 9 | **validate** | **增强** | 验证范围扩大：ruff + mypy + pytest + mkdocs + CLI + worktree 清理验证 |

### 4.3 关键变化说明

**步骤 7 — worktree 竞争+融合**（核心升级）：
- 旧：Agent A/B 分工改不同文件，Agent C 验证
- 新：Agent A/B 各自在独立 worktree 完成同一任务，Agent C 持续检查+融合

**步骤 8 — apply**（调整）：
- 旧：直接应用变更到工作目录
- 新：将 Agent C 融合后的结果合并到 `feat/multi-db-support` 分支
- 包含 worktree 清理操作

**步骤 9 — validate**（增强）：
- 旧：ruff + mypy + pytest
- 新：ruff + mypy + pytest + mkdocs build + CLI 验证 + `git worktree list` 确认无残留

### 4.4 适用场景判断

并非所有任务都需要 worktree 竞争+融合。引入复杂度判断：

| 任务复杂度 | 推荐模式 | 示例 |
|-----------|---------|------|
| 低（单文件小改动） | 直接修改，跳过 step 7 | 修复 typo、调整常量 |
| 中（多文件但逻辑清晰） | 传统 3 智能体分工模式 | 添加测试文件 |
| 高（核心逻辑重构、架构调整） | **worktree 竞争+融合** | analyzer.py 拆分、多数据库支持 |

---

## 五、3 层验证 gate 适配

### 5.1 从"3 层"到"3 阶段多层级"

**旧 gate**（一次性 3 层）：

```
ruff check → mypy → pytest
```

**新 gate**（按 worktree 竞争+融合流程分 3 阶段）：

```
阶段 1: Agent A/B 自检（并行）
  ├── ruff check .（各自 worktree）
  └── mypy src plugins（各自 worktree）

阶段 2: Agent C 融合后验证
  ├── ruff check .（融合结果）
  ├── mypy src plugins（融合结果）
  └── pytest --tb=short -q（融合结果）

阶段 3: 合并到主分支后最终验证
  ├── ruff check .
  ├── mypy src plugins
  ├── pytest --tb=short -q
  ├── mkdocs build --strict
  ├── sqlseed --help（CLI 验证）
  └── git worktree list（确认无残留 worktree）
```

### 5.2 各阶段详细说明

| 阶段 | 执行者 | 检查项 | 失败处理 |
|------|--------|--------|---------|
| **阶段 1** | Agent A/B 各自 | ruff + mypy | 修正后重新自检，通过后才交给 Agent C |
| **阶段 2** | Agent C | ruff + mypy + pytest | 融合问题 → 修正融合；A/B 某方问题 → 回退到该方修正 |
| **阶段 3** | Agent C | ruff + mypy + pytest + mkdocs + CLI + worktree 清理 | 任何失败 → 修正后重新验证；worktree 残留 → 清理后重新确认 |

### 5.3 关键改进

1. **自检前置**：Agent A/B 各自完成 ruff + mypy 自检后才交给 Agent C，减少 Agent C 负担
2. **融合验证**：Agent C 融合后立即验证，确保融合质量
3. **最终验证增强**：合并到主分支后增加 mkdocs build + CLI + worktree 清理验证
4. **失败回退路径明确**：每个阶段失败都有明确的回退策略

### 5.4 验证命令标准化

```powershell
# 阶段 1 & 2 通用
ruff check .
mypy src plugins

# 阶段 2 & 3 通用
python -m pytest --tb=short -q

# 阶段 3 专用
mkdocs build --strict
sqlseed --help
git worktree list  # 应只显示主工作目录
```

---

## 六、设计文档驱动适配

### 6.1 设计文档增强

**旧规范**：
- 位置：`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- 内容：背景、影响分析、详细计划、3 智能体分工、验证标准、风险与缓解、YAGNI 清单

**新规范**（增加 worktree 章节）：

设计文档模板新增 **"Worktree 竞争+融合"** 章节，包含：

```markdown
## N、Worktree 竞争+融合配置

### 任务定义
- 任务描述：[Agent A 和 Agent B 共同完成的同一个任务]
- 适用判断：[高复杂度任务，如核心逻辑重构/架构调整]

### Worktree 布局
- Agent A worktree：`../sqlseed-worktree-a`（分支 `feat/multi-db-support-agent-a`）
- Agent B worktree：`../sqlseed-worktree-b`（分支 `feat/multi-db-support-agent-b`）
- 融合目标：`feat/multi-db-support`

### Agent C 融合策略
- 比较方式：[逐文件 diff / 功能点对比]
- 融合优先级：[性能 > 可读性 > 简洁性 / 其他]

### 持续检查计划
- 检查频率：[每完成一个子任务 / 每 N 分钟]
- 检查内容：[正确性 / 风格一致性 / 边界破坏]
```

### 6.2 分支命名规范

| 分支类型 | 命名格式 | 示例 |
|---------|---------|------|
| 主开发分支 | `feat/<feature-name>` | `feat/multi-db-support` |
| Agent A 竞争分支 | `feat/<feature-name>-agent-a` | `feat/multi-db-support-agent-a` |
| Agent B 竞争分支 | `feat/<feature-name>-agent-b` | `feat/multi-db-support-agent-b` |
| 备份分支 | `feat/<feature-name>-backup` | `feat/multi-db-support-backup` |

### 6.3 设计文档审查流程调整

**旧流程**：

```
brainstorm → 写 spec → 自审 → 用户审查 → writing-plans
```

**新流程**（增加 worktree 可行性评估）：

```
brainstorm → 写 spec → 自审 → worktree 可行性评估 → 用户审查 → writing-plans
```

**worktree 可行性评估**（自审阶段新增检查项）：
- [ ] 任务复杂度是否达到 worktree 竞争+融合的门槛（高复杂度）？
- [ ] worktree 布局是否合理（路径不冲突）？
- [ ] Agent C 融合策略是否明确？
- [ ] 持续检查计划是否可行？

### 6.4 与现有设计文档的关系

现有 14 个设计文档（`docs/superpowers/specs/`）保持不变，新规范仅适用于未来的设计文档。不追溯修改历史文档。

---

## 七、风险管理体系适配

### 7.1 风险矩阵扩展

**新风险**（worktree 相关 5 项）：

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| 6 | **worktree 创建失败**（路径冲突/权限） | 低 | 阻塞 | 预检查路径，失败时清理后重试 |
| 7 | **A/B 实现差异过大，融合困难** | 中 | Agent C 负担重 | 设计阶段明确任务范围；Agent C 逐文件评估，必要时以一方为基底 |
| 8 | **worktree 残留未清理** | 中 | 磁盘占用/分支污染 | 阶段 3 验证 `git worktree list`；提供清理脚本 |
| 9 | **融合结果引入新 bug** | 中 | 功能回归 | 阶段 2 完整 pytest；阶段 3 最终验证 |
| 10 | **Agent C 持续检查干扰 A/B** | 低 | 效率降低 | Agent C 只读检查，不修改 A/B 的 worktree |

### 7.2 备份分支策略升级

**旧策略**：

```
feat/multi-db-support          # 主开发分支
feat/multi-db-support-backup   # 备份
```

**新策略**（增加 worktree 回退点）：

```
feat/multi-db-support          # 主开发分支
feat/multi-db-support-backup   # 备份（worktree 竞争前创建）
feat/multi-db-support-agent-a  # Agent A 竞争分支（临时，完成后删除）
feat/multi-db-support-agent-b  # Agent B 竞争分支（临时，完成后删除）
```

### 7.3 回退路径

| 失败场景 | 回退操作 |
|---------|---------|
| worktree 竞争阶段失败 | `git worktree remove` + `git branch -D` 清理，`git reset --hard feat/multi-db-support-backup` |
| 融合阶段失败 | 保留 A/B 分支，Agent C 重新融合；或回退到 backup |
| 合并后验证失败 | `git reset --hard feat/multi-db-support-backup` |
| worktree 残留 | `git worktree prune` + `git worktree list` 确认 |

### 7.4 YAGNI 清单扩展

新增"不做"项：
- 不为低复杂度任务创建 worktree（直接修改即可）
- 不保留 worktree 跨任务（每次任务完成后清理）
- 不让 Agent C 修改 A/B 的 worktree（只读检查）
- 不同时运行超过 2 个 worktree（A + B，Agent C 在主目录）

### 7.5 影响分析前置（增强）

设计阶段新增影响分析检查项：
- [ ] 任务复杂度是否达到 worktree 门槛？
- [ ] 是否有跨文件依赖需要在设计阶段预分配？
- [ ] worktree 路径是否与现有目录冲突？
- [ ] 备份分支是否已创建？

---

## 八、验证标准

### 8.1 设计文档验证

- [ ] 设计文档包含"Worktree 竞争+融合配置"章节
- [ ] worktree 可行性评估通过
- [ ] 分支命名符合规范

### 8.2 实施验证

- [ ] worktree 创建成功（`git worktree list` 显示 3 个条目）
- [ ] Agent A/B 各自完成 ruff + mypy 自检
- [ ] Agent C 融合后通过 ruff + mypy + pytest
- [ ] 合并到 `feat/multi-db-support` 后通过全部验证
- [ ] worktree 清理完成（`git worktree list` 只显示主工作目录）

### 8.3 回归验证

- [ ] 现有功能未受影响（pytest 1007+ passed）
- [ ] 无 worktree 残留
- [ ] 无临时分支残留

---

## 九、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| worktree 操作不熟悉 | 中 | 效率降低 | 提供标准化命令模板 |
| Agent C 融合工作量大 | 中 | 时间成本 | 逐文件评估，优先选择较好实现 |
| 磁盘空间不足 | 低 | 创建失败 | worktree 完成后立即清理 |
| 并行智能体上下文冲突 | 低 | 逻辑不一致 | Agent C 持续检查 |

---

## 十、YAGNI 清单（不做）

- 不修改现有 14 个设计文档（新规范仅适用于未来）
- 不为低复杂度任务创建 worktree
- 不保留 worktree 跨任务
- 不让 Agent C 修改 A/B 的 worktree
- 不同时运行超过 2 个 worktree
- 不引入 worktree 管理工具（使用原生 git 命令即可）
- 不自动化 worktree 创建/清理（手动操作，确保安全）
