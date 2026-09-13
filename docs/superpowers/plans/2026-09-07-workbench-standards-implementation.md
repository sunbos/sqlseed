# 工作台标准化与功能层级实施计划

**Goal:** 按用户已确认方案和权威交互／数据库规范，实现配置管理、紧凑工作台、统一日期、精细 AI 和可核验的清空策略，并展示实页效果。

**Architecture:** 保留 v8 单主题，扩展到工作台／配置管理／运行记录。WorkbenchDocument 仍为唯一规则状态；分析范围独立于生成范围；运行使用固定快照和服务端检查。元数据管理、日期组件、AI 范围与关系、执行策略分别使用独立模块，避免继续堆叠 workbench.js。

**Tech Stack:** Python/FastAPI/SQLAlchemy、原生 ES modules/CSS、pytest、Node 内置测试、CUA 实页检查。

## 授权与规范

用户“如果有标准，按照权威标准实现，然后看看效果”批准上一轮 [功能层级方案](../specs/2026-09-07-workbench-function-hierarchy.md)。不重复请求设计批准；保留所有混合未提交改动，不自动提交或推送。不清空或写入用户数据库，用临时数据库验收。

- W3C WCAG 2.2：2.1.1 键盘、2.4.3 焦点顺序、2.4.7 可见焦点、2.4.11 焦点不遮挡、2.5.8 点击目标、3.3.1 错误说明、3.3.2 标签、3.3.4 修改/删除数据可确认、4.1.2 名称角色状态。https://www.w3.org/TR/WCAG22/
- WAI-ARIA APG dialog / select-only combobox / tabs / datepicker：控件模式、键盘导航、返回焦点。https://www.w3.org/WAI/ARIA/apg/
- NN/g Progressive Disclosure 是设计建议，不是强制导航数量标准。https://www.nngroup.com/articles/progressive-disclosure/
- SQLite foreign keys / AUTOINCREMENT 和 PostgreSQL TRUNCATE / ALTER SEQUENCE：删除范围、事务与 identity 语义按实际方言实现，不承诺不存在的跨方言行为。

## 任务及验收

- [x] 配置管理（独立 agent）：store 原子删除/复制/重命名、drafts API、configs.js/css。删除携 revision，保留 run 快照，在途冲突真实测试；UI 搜索/目标筛选、新建/打开/复制/重命名/删除/导出，导入转工作台。新建 ?new=1、打开 ?draft=id；导入 ?new=1&import=1。事件 sqlseed:draft-deleted / renamed 使其他已加载 model 不持有失效 id。
- [x] 日期组件（独立 agent）：date-picker.js/css + editor.js。文本输入 YYYY-MM-DD、自绘日历、月份/年份切换、今天/清空、方向键/Home/End/PageUpDown/Enter/Escape，焦点回到触发器。非法输入保存草稿且不更新规则；继承部分日期参数。
- [x] AI（独立 agent）：独立分析 scope、表/列多选、业务说明、必要上下文；关系模板服务端编译、完整 DAG/类型/NULL/锁定字段校验、候选配置只读检查、关系整体审阅应用。旧 scope 和无 AI 流程保持可用，模型 HTTP 边界替换测试。
- [x] 主导航与工作台（root）：注册 configs 路由并更新动态页面标题；配置生命周期路由与事件衔接；退出页面保留草稿。结构操作移入数据库折叠面板；统一“查看样例＋当前表/已选表”动作；紧凑全局设置，取消重复字段说明区。
- [x] 字段信息／规则分工（root）：共享右抽屉分页，字段名打开只读 schema 信息，规则打开编辑器；APG tab semantics 与箭头键，切页不误应用；列级 AI 入口明确选择范围。
- [x] 执行策略（root/空闲 agent）：独立规划清空范围及 identity，不使用关闭 FK 或自动 CASCADE。本机缺少 PostgreSQL/testcontainers 验证环境，PG 清空保持服务端能力门禁；仅开放已验证的 SQLite 清空。采用可证明的事务语义并在运行摘要呈现策略与影响。临时真实库验证父子清空/未选下游阻塞/失败恢复/序列起点；未覆盖方言明确阻止而非伪造成功。
- [x] 集成验证：针对新增行为红绿测试；Node + 受影响 Python 全量、ruff/format/mypy/import-linter/doc-sync、wheel；不因数量足够而省略浏览器。
- [x] 浏览器与服务：保留用户未保存配置后加载最新服务，验证 1144×872 与窄窗口；键盘日期/菜单/分页、配置完整生命周期、AI 范围、生成策略摘要与运行记录。真实数据删除/生成仅在临时测试库进行。
- [x] 文档与交付：更新 AGENTS 当前契约、用户指南、标准到验收项映射和已执行/未执行环境记录。展示正式 Web 效果，明确真实 LLM / PostgreSQL 的验证状态。


## 实际验收记录（2026-09-07）

### 标准与检查对应

| 依据 | 实施与验收 |
| --- | --- |
| WCAG 2.1.1 / 2.4.3 / 2.4.7 / 2.4.11，APG combobox | 下拉单一 Tab 停靠点、方向键浏览、Enter/Space/Tab 确认、Escape 取消；浮层使用视口可用空间，语言末尾选项可访问，关闭返回触发器，父弹窗保持打开。 |
| APG date picker dialog / tabs | 同主题 ISO 日期输入、年月跳转、日历网格键盘操作、无效输入提示；字段信息与取值规则有独立 tabpanel 和可返回焦点，取消不应用。 |
| WCAG 3.3.4 数据修改可确认 | 配置删除显示名称/数据库/版本并默认聚焦取消；清空计划显示精确范围、已有行数、生成数量与独立重置选项，显式确认后执行。 |
| NN/g 渐进披露 | 引擎和语言常显；高级配置、结构工具、AI 服务设置按需展开。三项主导航由实际功能职责决定。 |
| SQLite FK / AUTOINCREMENT / 事务语义 | 不关闭外键、不扩大到未选表；先子后父清空、先父后子生成，所有读写共用事务；重置历史计数独立选择，失败恢复原数据和序列。 |

以上是对应条目的工程实现与专项验证，不是完整 WCAG 合规认证；尚未执行所有屏幕阅读器和操作系统组合验收。

### 浏览器与真实数据

- 正式 Web 在 1144×872 和 760×872 窗口检查：三项导航、紧凑设置、数据库折叠工具、统一样例入口、字段／规则分工、下拉和日历均可操作；最终页面无新 error/warn 日志。
- 配置复制、搜索、重命名、JSON 导出和删除通过实际 UI 完成；删除仅作用于名为“标准化验收临时副本”的验收副本。原配置、原草稿及运行快照保留。
- 单独创建真实临时 SQLite，customers 与 orders 各有 1 条旧数据，原 ID 为 100 / 500。通过 UI 选择两表各生成 3 行，确认清空及重置后运行成功，记录显示计划 6 / 实际提交 6。
- 只读 SQL 核对两表 ID 均为 1、2、3；PRAGMA foreign_key_check 无异常。未选表影响、并发变化、失败回滚、提交前计数及序列恢复由真实 SQLite 回归覆盖。用户原数据库的 SHA-256 前后相同。
- 原浏览器草稿已先保存，再重启服务并恢复同一数据库、原 AI 服务设置及草稿。生成／清空验收从未作用于用户数据库。
- 当前 Ollama 的 gemma4:31b-cloud 在独立临时副本完成真实 AI 分析，2.768 秒返回指定 quantity / unit_price / total 三列的同组建议。服务端 product 模板、完整候选配置和样例检查通过：1×19.94=19.94，2×15.89=31.78，5×19.47=97.35；副本 hash 未变。
- 此真实 AI 结论仅覆盖该 product 样例；其余模板、边界、越界修改、NULL／类型／循环／约束等由确定性协议回归覆盖，不据此宣称所有模型语义正确。

### 自动化与构建

- 前端 Node：316 项通过。
- 首次全量 Python：2471 passed、34 skipped、6 failed。6 项均因测试后端选择器将服务返回的完整模型 ID 错误截短而报 404；这暴露了原测试 fixture 的真实缺陷。修复及最终重跑结果记录于下方，保留首次结果以区分发现与验收。
- ruff check、format、mypy（135 个 source files）、3 条 import-linter 契约、doc-sync 与 diff-check 通过。doc-sync 保留 CLAUDE 示例 marker-name 的既有提示，不影响检查结果。
- core 与 Web wheels 已构建，新增 configs/date-picker/AI relations/execution 文件包含在包内；RECORD 哈希与静态资源相对引用检查通过。
- 未执行 PostgreSQL 清空集成、缺失媒体依赖和额外真实后端的用例按环境跳过。没有合并或提交，因此未运行与本次修改无关的 unique_adjuster mutation 合并门禁。


### 全量检查发现的问题与最终结果

- 测试后端现在返回 Ollama 实际提供的完整模型 ID，并按模型标签边界匹配；新增 14 项回归。修复名称后原 6 个真实 LLM 用例中的 5 项通过，另一项暴露实际 mapper 参数污染。
- 显式 sentence 规则会被字段名称推断重新注入 text 的 min_length/max_length；显式 text 也可能继承 string 的 charset。现仅在同生成器间保留默认参数，string/text 跨生成器仅继承共有长度参数。新增 10 项确定性 spec 与真实 Faker/Mimesis 只读预览回归；无效的显式用户参数仍报错。
- 修复后原 6 个真实 LLM 用例全部通过，未增加重试预算或削弱断言。随后完整 pytest 重跑：**2502 passed，33 skipped，52.59 秒**。完整 Node 重跑仍为 **316 passed**。
- 跳过项包括未安装 testcontainers 的 PostgreSQL、缺失 Pillow 的媒体、未运行的 LM Studio 和未配置密钥的特定后端；不把它们算作成功验证。

- 最后独立审阅修复 nullable、无真实 DEFAULT 的显式 skip 目标被误锁：用户明确选中该列可接受 AI 建议，skip 来源、真实 DEFAULT、PK/FK/计算列和高级规则仍受保护。4 项真实 SQLite 回归验证只读 evidence 与拒绝边界；末尾变更后 **Web Python 223 passed**（含 AI 47 项），完整前端仍 **316 passed**，ruff/format/mypy 再次通过。
- 最终 core/Web wheels 与 113 个当前源文件逐字节一致，71 个 Python 文件编译通过，120 条 RECORD 哈希、52 条静态及动态 import 引用核验通过。验收产物与详细报告位于 `/tmp/sqlseed-standards-wheels/`。
- 最终服务健康检查通过，原数据库连接、原草稿和 AI 偏好已恢复，用户数据库 SHA-256 仍与验收前相同。未提交、合并或推送。
