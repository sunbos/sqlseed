# 三分支合并审查与 Contributors 核验

核验日期：2026-09-13（Asia/Shanghai）。下文保留 `4ba5d08` 的合并前审查与当时状态；用户随后授权执行修复、完整验证及合并。后续执行记录见下一节，不以历史结论替代最新提交的检查。

## 执行记录

- 已修复 JSON/日期绑定、自引用外键及 AI MCP stdout，并增加真实 SQLite、MCP 子进程和 PostgreSQL 回归。独立复核还发现并修复 JSON 父池字符串/文本格式保真和索引级 `COLLATE NOCASE` 边界。
- main 已要求 PR 和 12 项检查，严格要求分支最新、管理员受约束、禁止强推及删除。Pages 改为 main CI 全部任务成功后构建同一提交并部署。
- 补充中英文迁移说明、Unreleased changelog；插件 Core 与 CLI/AI 兄弟包依赖限制为 `>=0.2.4.dev0,<0.3`，同步已有 lock files。
- 本地 Python 3.12 全量 3644 passed / 65 skipped，Node 669 passed；跳过项为 Docker/PostgreSQL、真实 LLM/API 配置和可选 Pillow，不能计作通过。全量测试之后的等价静态整理另做专项复验。最终远端结果和安装包以 PR #10 的最新提交检查为准；全门禁通过前保持 Draft。
- 默认 `unique_adjuster` mutation 在新建隔离快照中重新全跑：246/246 killed，0 survived/timeout/suspicious/skipped/untested，退出码 0。目标 SHA256 为 `55267e55b51f0084ab5d541c275567bb07965f291d656f718566af53161face9`。运行期间的两项其他源码等价整理不涉及该目标、runner、其两份测试或配置；不将此结果扩大为全部新代码已做 mutation。
- `fill` 参数数量问题按用户决定暂缓，保留 OPEN。未发布 PyPI，未改写历史。
- [GitHub Support 工单 #4753046](https://support.github.com/ticket/personal/0/4753046)已成功提交，但自动客服以账号仅提供自助支持为由关闭，重开按钮不可用。Contributors 尚未据此清除；详见[工单记录](github-support-draft.md)。

## 决策

应以 `codex/workbench-candidate` / PR #10 作为合入 main 的唯一候选；旧 feature 已完全包含，无需另合。但 **当前 4ba5d08 不宜立即合并**：真实 SQLite 对照复现了 JSON 双重编码、日期字符串兼容回归，以及新增 self-FK 后处理的边界缺陷。先修复并补回归，再以新提交重新验证。

候选的架构、数据库支持、入口隔离、失败计数、安装验证和 CI 加固有净收益；这不能推导出所有旧配置都兼容，也不能推导出性能全面提升。本轮没有做相同负载的性能基准比较。

## 分支关系

| 分支 | 精确提交 | 关系与建议 |
| --- | --- | --- |
| main | 976b605dac47bd6d61cfcae4ff6c7a00fa0352a5 | 合并目标；相对 candidate 没有独有提交 |
| origin/feat/contract-driven-self-healing | fb081874311d153c2cecb7f163ce02c061707ad7 | 比 main 多 220 个提交，全部在 candidate 中 |
| codex/workbench-candidate | 4ba5d08364cb85f44593c57271d339d61d5bf1f9 | 比 main 多 248 个提交；修复本报告问题后合并 PR #10 |

本地 feature `a18d232` 比远端 feature 多 7 个提交，也已全部包含在 candidate；candidate 在其后还有 21 个提交。无需另推旧 feature 来补齐这些工作。远端实际只有上述三个分支；本地另有历史备份分支。

`git merge-tree --write-tree` 检查无文本冲突，生成树与 candidate 树相同。GitHub PR #10 为 OPEN、Draft、CLEAN、MERGEABLE。无文本冲突只证明 Git 能组合提交，不证明行为没有回归。

main→candidate 共 833 文件变化、277552 行新增、9369 行删除；约 54% 新增行来自 docs 下的审计/设计资料。产品源码仍有 224 个变更文件，约 5.9 万行新增，属于较大的版本整合。

## 已复现的问题

### P1：SQLite JSON 对象被静默写成 JSON 字符串（真实回归）

位置：`src/sqlseed/database/sqlalchemy_adapter.py:194`、`:204`；生成器契约见 `src/sqlseed/generators/_json_helpers.py:33`。

最小场景：`payload JSON NOT NULL`，使用 `json` generator 生成带整数 `n` 的 object，base provider、seed=42、3 行。

| 版本 | result | 数据库实际内容 |
| --- | --- | --- |
| main | count=3、errors=[] | json_type(payload) 为 object；json_extract(payload,'$.n') 为 670487、116739、26225 |
| candidate | count=3、errors=[] | json_type(payload) 为 text；json_extract(payload,'$.n') 全部 NULL |

原因：generator 已返回序列化 JSON 文本，SQLAlchemy 的反射 JSON 类型又执行一次序列化。没有抛错，但数据语义改变。应在生成器与 typed insert 边界明确 JSON 对象/序列化文本契约，兼顾 JSON/JSONB 与普通 TEXT 列；不要仅通过放宽断言消除症状。

### P2：已有 DATE 字符串配置无法写入（真实回归）

位置：`src/sqlseed/database/sqlalchemy_adapter.py:198` 至 `:204`。

最小场景：`holiday DATE NOT NULL`，choice generator 使用 `['2026-01-01', '2026-12-25']`。

- main：写入 3 行，errors=[]，存储合法 ISO 日期。
- candidate：写入 0 行，报 `SQLite Date type only accepts Python date objects as input`。

现有转换处理了无 SQLAlchemy bind processor 的列，却未兼容合法日期字符串进入 DATE bind processor 的情况。需明确 DATE/DATETIME/TIME 输入规范化和非法值拒绝行为，并覆盖 YAML/choice 等字符串来源。

### P2：self-FK 后处理不能正确处理复合主键或 UNIQUE 外键（候选新功能缺陷）

位置：`src/sqlseed/core/orchestrator/_generation.py:437`、`:506`、`:515`、`:523`。

- 表主键为 `(tenant, slot)`、tenant 值重复，单列 `parent_code` 引用同表 UNIQUE code。后处理仅用第一个主键列定位 UPDATE，导致同一 tenant 的多行一起更新。20 行真实复现中 errors=[]，所有行指向同一个 code，并形成一个自环。
- 同一结构加入 `CHECK(parent_code != code)` 后，20 行初始数据已写入，后处理报 CHECK 错误。
- `parent_id INTEGER UNIQUE REFERENCES nodes(id)` 场景中，随机有放回选择父值，20 行初始数据已写入后触发 UNIQUE 错误。

main 在这些最小场景中原本就生成失败、写入 0 行，因此不能声称这是“原来成功现在失败”的回归。它们是候选新增两阶段 self-FK 功能中的确认缺陷。应使用完整主键元组定位，按 UNIQUE 约束规划父引用；无法支持的结构应在副作用前明确拒绝。

### P2：AI MCP stdio 输出被进度条污染（迁移保留的旧缺陷）

位置：`plugins/sqlseed-ai/src/sqlseed_ai/mcp.py:220`。

AI agent_fill 调用 `fill_table()` 未传 NullProgressBackend。独立审阅使用当前源码，仅替换 LLM 响应，实际向临时 SQLite 插入 3 行；业务 errors=[]，stdout 同时含 `Generating items ... 100% 3/3`，会污染 MCP stdio 协议流。

main 的旧实现已有相同问题；candidate Core MCP 已使用 NullProgressBackend。AI MCP 也应补齐，并通过真实子进程/协议输出回归确认。该问题不是选择旧 feature 的理由。

## 兼容性与部署风险

- CLI 从 Core 拆出。仅升级 Core 的旧用户需安装兼容的 `sqlseed-cli` 或 Core CLI extra；旧 `sqlseed.cli` import 路径不再存在。
- Core MCP 收窄为规则生成与执行两个工具；旧 AI 功能转移到 `sqlseed-ai[mcp]`，schema inspection/resource 移除。现有客户端需要迁移。
- 候选插件需要 Core >=0.2.4.dev0，不能和旧 0.2.3 混装。五包应使用同一 CI run 的产物验证。CLI/AI/Web 的 Core 依赖尚缺架构约定的上界，这是后续版本兼容风险，未证明当前运行失败。
- CHANGELOG 仍以 v0.1.20 开头，缺少此次五包迁移汇总；发布前应更新中英文 changelog 与安装迁移说明。
- 合并 main 会触发 CI、doc-sync，并因 docs/mkdocs/workflow 变化自动更新 GitHub Pages。Pages deploy 只等待自身 build，没有等待完整 CI；当前 environment 没有人工 reviewer。
- 合并不会自动发布 PyPI；发布 workflow 仍需要 release published/dispatch、v tag 和五包版本一致性校验。
- main 当前 protected=false、rulesets=[]。建议合并前配置所需检查和禁止直接推送，但本轮未改仓库设置。
- Web 没有多用户认证；PostgreSQL 复合/跨 schema 外键等已有明确支持边界。不要将本地工作台直接等同于可公开部署的多用户服务。

## 验证证据及限度

实时 GitHub 显示 PR #10 的 12 个状态均成功：9 个 CI job、doc-sync、SonarCloud、CodeFlow。CI run 34723324400 的 headSha 为 4ba5d08，覆盖 Linux Python 3.10/3.12/3.13、macOS、Windows、真实 PostgreSQL、property tests、五包 sdist/wheel 构建和隔离安装。此前本地完整 pytest 为 3562 passed / 47 skipped，mutation 为 246/246 killed。

本轮在同一现有 Python 3.12 依赖环境下，通过 PYTHONPATH 分别加载 main 的独立源码与 candidate 源码，以临时 SQLite 双跑 JSON、DATE、self-FK probes。禁用可选插件 discovery，避免已安装候选 AI 插件加载旧 Core；数据生成、SQLAlchemy/旧 adapter 与数据库均实际执行。main 的已安装 AI provider entry point 会输出导入不兼容警告，但选定的 provider 是 base。没有依赖该警告判断结果。

现有全绿结果与本报告的复现并不矛盾：这些边界尚未被现有测试覆盖。本轮是有限范围审查，没有证明不存在其他缺陷，也没有重新进行所有真实 LLM/数据库组合验证。

`docs/candidate-validation.md` 中部分旧 Sonar/mutation 状态已过期，且该文件有用户未提交修改。本轮未覆盖它。当前质量门禁证据以精确提交的 CI 和 2026-09-13 Sonar 整改报告为准。

候选包 artifact 名称当前使用 PR merge commit 的 github.sha，名称后缀并不等于 headSha；追溯安装包应同时核对 workflow run。

## 推荐合并顺序

1. 在 candidate 修复 JSON、日期输入、self-FK 和 AI MCP stdout，添加真实行为回归；保留用户暂缓的 fill 参数数量问题。
2. 补迁移说明，整理实际验收状态；对 main 配置所需门禁，明确 Pages 发布时机。
3. 新提交通过完整门禁后将 PR #10 转为 Ready，合入 main；随后核验 main 的 CI、Sonar 和文档部署。
4. 合并成功且确认无分支独有提交后，再清理旧 feature。PyPI 发布作为独立动作。

## traeagent 核验

- 当前 main 与 candidate 的按 traeagent 作者过滤的 GitHub commit API 均返回 []；本地所有可用引用的 author/committer/message 未发现 traeagent。
- Contributors 图表切换为 Period: All 后，只显示 sunbos（82）与 claude（27）；stats/contributors 同样只有这两项。
- contributors API 只列 sunbos（88）；该接口与图表计数口径不同，不将它用于证明 claude 不存在。
- 新打开的仓库首页依然显示 Contributors (3)，包含 traeagent。

已确定存在展示/统计不一致，缓存是合理推断，尚未由 GitHub 确认。当前没有需要删除的对应提交，不应为刷新头像而重写历史。已准备 `github-support-draft.md`，请求 GitHub Support 核查并刷新仓库 sidebar 的 contributor cache/index；尚未发送。

## 链接

- PR：https://github.com/sunbos/sqlseed/pull/10
- CI：https://github.com/sunbos/sqlseed/actions/runs/34723324400
- Contributors：https://github.com/sunbos/sqlseed/graphs/contributors
- GitHub 官方缓存说明：https://github.com/github/docs/blob/main/content/repositories/viewing-activity-and-data-for-your-repository/viewing-a-projects-contributors.md
