# 正式 Web 功能与生命周期审计

审计日期：2026-09-07。范围：当前磁盘上的正式 Web、共享 API、工作区持久化、core 清空与 identity 路径。本文是代码审计与设计建议，不代表所提功能已实现。没有操作用户数据库；SQLite 缺陷只在临时真实库复现与验证，PostgreSQL 未连接实库。

本轮范围依据用户最新要求重新评估导航与功能归属；历史“两导航”约束不作为本次评估的结论。保留已对齐的 v8 视觉语言，具体信息架构等待主任务综合设计。

## 1. 当前功能清单与作用范围

“基础”表示完成首次生成所必需或应容易找到；“高级”表示按需展开的细化能力；“缺口”表示当前正式界面没有完整实现。共享旧 API 可调用，不等于新版正式界面已有该功能。

### 数据库与连接

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 添加 SQLite 连接、选择服务器上的文件 | 顶栏连接管理；路径输入与服务端文件浏览 | 基础 / 全局数据库上下文 |
| 添加 PostgreSQL 连接 | 同一连接弹窗；地址、端口、库名、用户名、密码 | 基础 / 全局数据库上下文；真实 PostgreSQL 未验 |
| 查看与切换当前服务连接 | 按脱敏目标分组、标记当前连接，同一目标可展开其他会话 | 基础 / 数据库上下文 |
| 断开当前连接、移除其他会话 | 关闭相应服务连接；繁忙会话会被保护；不会自动连接别的会话 | 基础 / 连接生命周期 |
| 连接信息 | 工作台库名旁入口；目标、方言等 | 基础 / 当前数据库 |
| 持久连接档案、重命名档案、重启后恢复凭据 | **没有**；现有列表只是当前服务会话，不能称“已保存数据库” | 缺口 / 需独立产品决策，不应悄悄保存密码 |
| 刷新数据库结构 | 左侧数据库工具；刷新元数据并处理编辑冲突 | 基础 / 当前数据库 |
| 导出整库结构、导入结构 JSON | 左侧数据库工具；导入图是只读结构查看，不创建表、不切换真实写入目标 | 高级 / 数据库结构工具 |
| 整库关系图与查询定位 | 点击库名查看整库，搜索表和路径 | 基础 / 数据库结构 |
| 查看真实数据库行、运行 SELECT 查询 | 共享 API 存在，正式工作台无入口；当前样例是生成预览 | 缺口 / 若新增应明确区分“已有数据”与“生成样例” |
| 创建/修改表结构、删除数据库文件 | 未作为正式 Web 能力提供 | 不应从连接移除或结构导入推导出这些动作 |

### 生成配置

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 配置名称、保存状态 | 工作台标题；重命名、未保存/已保存状态 | 基础 / 当前生成配置 |
| 保存、打开已保存配置 | 标题附近工具；列表按当前数据库目标筛选，乐观 revision 防止覆盖 | 基础 / 配置生命周期 |
| 新建空白、另存为/复制、删除、检索配置 | 没有完整独立入口；可从运行快照新建，不能替代一般配置管理 | **主要缺口** / 配置生命周期 |
| 生成引擎与语言 | 工作台显式设置区和设置弹窗；不是每表临时选项 | 基础 / 当前配置全局设置 |
| YAML/JSON 查看、编辑、解析应用、导入与导出 | 配置文档弹窗；保留未被表单消费的完整文档字段 | 高级 / 当前配置；与结构 JSON 是不同数据格式 |
| 自定义映射、跨表 associations、batch_size、seed、enrich、optimize_pragma | core 与完整配置文档可表达；并非所有项目都有独立友好表单 | 高级 / 配置或表；需逐项检查真实执行支持 |
| transform、snapshot_dir、不同于全局的每列 provider | 文档保留，但正式执行有明确不支持诊断 | 暂不可执行；不能只因配置模型存在就放出可用开关 |
| AI 服务设置、连接测试 | AI 辅助配置面板内设置；可选插件 | 高级 / 服务设置，不属于表字段取值规则 |
| AI 分析与规则建议 | 顶部“AI 辅助配置”；结构信息分析、建议审阅后明确应用 | 辅助能力 / 当前配置；不代替检查、不自动写库 |

### 表与生成范围

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 全选、清空选择、单表加入/移出生成 | 左侧范围选择；取消选择不表示数据库没有该表 | 基础 / 当前配置的生成范围 |
| 每表生成数量 | 当前表标题；未选表可明确加入 | 基础 / 当前表 |
| 字段规则与表关系切换 | 点击左侧表名看规则、旁边结构图标看依赖 | 基础 / 当前表 |
| 完整依赖路径、上游、下游、仅相邻 | 关系图范围工具；完整路径保留传递依赖所需来源 | 高级 / 当前表关系分析 |
| 拖动画布、缩放、适应、放大阅读、展开、字段标签 | 图工具区 | 高级 / 视图，不改变生成配置 |
| 点击图节点、外键边映射、关联检查项定位 | 图和检查结果中的表/列链接 | 基础 / 定位与解释 |
| 本表预览 | 当前字段表工具；只预览本表及所需已选上游，未选父表从已有有效键取值 | 基础 / 本表及来源闭包 |
| 本表相关生成顺序 | 本表图旁依赖面板；仅投影本表相关计划 | 基础 / 当前表；不可混成全局选择列表 |
| 表现有行数、已有键来源 | 结构与检查结果；来源“仅引用”可以是未选表 | 基础 / 来源事实；不是即将生成行数 |

### 字段与规则

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 类型、主键、可空、约束、自动分配说明 | 字段表；字段名与规则都可直接打开规则编辑器 | 基础 / 当前字段 |
| 生成器推荐、搜索、全部列表、用法与示例 | 规则抽屉 | 基础 / 当前字段；高级列表按需展开 |
| 数字范围/精度、字符串长度/字符集、枚举等参数 | 生成器专用参数组件 | 基础 / 当前生成器 |
| 日期/时间格式、范围、快捷值、星期 | 日期生成器专用组件 | 基础 / 当前生成器 |
| NULL 比例、唯一约束等 | 规则编辑器；兼容性仍由正式检查核验 | 高级 / 当前字段 |
| 数据库自动分配、数据库默认值/省略写入 | 对应特殊规则模式；自增列不是普通整数生成器 | 基础 / 数据库控制的字段 |
| 外键引用来源 | 固定 schema 外键关系及采样说明；编辑不能凭空改数据库 FK | 基础 / 当前外键 |
| 同行派生字段、来源字段和表达式 | 规则抽屉；受安全表达式与列依赖限制 | 高级 / 当前字段 |
| 原生 Faker/Mimesis 方法、native_params、额外约束 JSON | 高级设置；不能作为新人完成基本输入的必要步骤 | 高级 / 当前字段 |
| 应用、取消、恢复初始规则 | 抽屉事务式修改；未应用不污染已保存配置 | 基础 / 当前规则编辑 |
| 跨表关联规则独立编辑器、规则模板库 | 没有完整友好入口，部分通过配置文档表达 | 缺口 / 后续高级配置，不宜全部堆入普通字段表 |

### 检查、预览与执行

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 检查所选表、有效来源、生成顺序与规则问题 | 顶部“依赖检查”；问题支持定位 | 基础 / 整份配置 |
| 预览所选表 | 顶部次要动作；生成只读样例，不写库 | 基础 / 整份配置，与本表预览范围不同 |
| 生成前摘要 | 主按钮“生成数据”进入；目标、已保存 revision、计划行数、各表顺序、检查结果 | 基础 / 一次执行 |
| 明确写入数据库 | 摘要最终动作；服务器重新核对 schema/config hash、revision | 基础 / 一次执行 |
| 后台执行、连接占用保护、持久记录 | 提交后运行记录与状态轮询 | 基础 / 一次运行 |
| 清空再生成、重置 identity | **正式工作台禁止** clear_before，执行固定 False | 新需求 / 需独立清空影响计划和事务实现 |
| 停止、取消、断点续作、自动重试 | 无完整正式能力 | 缺口 / 执行生命周期，不能把断开连接当取消 |
| 跨表循环、部分复杂复合 FK、其他 namespace 写入 | 当前检查明确限制 | 边界 / 应解释原因而非表现为普通生成失败 |

### 运行记录

| 能力 | 当前正式入口与实现 | 层级 / 归属 |
|---|---|---|
| 运行列表、当前记录定位、刷新/轮询 | “运行记录”一级页面 | 基础 / 历史运行 |
| 成功、失败、排队、运行中、未执行、中断 | 运行整体与每表状态；旧不完整记录不臆造成功 | 基础 / 实际结果 |
| 计划行数与已提交行数 | 独立总计和每表字段；不确定计数标记“至少” | 基础 / 计划与实际，不是数据库现存总行数 |
| 目标、配置版本、执行时间、错误原因 | 运行详情；Unix 秒转换为本地日期显示，保留原始持久化值 | 基础 / 运行证据 |
| 查看/下载冻结配置、从快照新建配置 | 详情操作；新建后需按当前结构重新检查 | 高级 / 追溯与复用 |
| 搜索、目标/状态筛选、分页、删除/保留策略 | 无完整 UI；API 默认最近 50 条，最大 200 条 | 缺口 / 数据增多后的管理能力 |

## 2. 路由与代码归属

正式前端 `static/js/app.js` 只动态挂载 `pages/workbench.js` 和 `pages/runs.js`。连接入口在 `workbench/connection.js`；编辑器、图、AI、session 各自独立。旧 `connect/wizard/browse/meta/heal` 文件仍在仓库，不在正式导航。

| API 组 | 当前路由 |
|---|---|
| 连接与文件 | `GET/POST /api/connections`、`DELETE /api/connections/{id}`、`GET /api/fs/browse` |
| 工作台元数据 | `GET /api/workbench/connections/{id}/schema`、`GET /api/workbench/generators` |
| 生成配置 | `GET/POST /api/workbench/drafts`、`GET/PUT /api/workbench/drafts/{id}`、`POST /api/workbench/parse`、`POST /api/workbench/export` |
| 检查与生成 | `POST /api/workbench/check`、`POST /api/workbench/preview`、`POST /api/workbench/runs` |
| 历史运行 | `GET /api/workbench/runs`、`GET /api/workbench/runs/{id}` |
| AI 辅助 | `GET/POST /api/workbench/ai/config`、`POST /api/workbench/ai/test`、`POST /api/workbench/ai/suggest` |
| 共享历史 API | `/api/meta/*`、旧表 schema/mapping/topo-order/yaml-template、旧 preview/fill、rows/query、config parse/serialize、heal validate/repair/auto、jobs |

源码入口：[workbench.py](../../../plugins/sqlseed-web/src/sqlseed_web/workbench.py)、[workbench_store.py](../../../plugins/sqlseed-web/src/sqlseed_web/workbench_store.py)、[workbench_runtime.py](../../../plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py)、[workbench_schema.py](../../../plugins/sqlseed-web/src/sqlseed_web/workbench_schema.py)、[共享 API](../../../plugins/sqlseed-web/src/sqlseed_web/api.py)。

## 3. 配置删除的现状与安全实现边界

当前没有后端删除方法，也没有前端删除入口；不能仅增加一个按钮。`workspace_drafts` 与 `workspace_runs` 是工作区 SQLite 中两个独立表，没有引用约束或 cascade。每份配置只存当前 revision，运行记录则包含 `document`、目标、schema hash、配置名称、draft id/revision 和计划的独立不可变快照。

执行工作线程读取运行记录的 `document`，不依赖日后配置仍存在。因此后续删除配置可以保留历史与正在运行的任务，且不应删除数据库、其他配置或运行记录。运行详情应能显示“原配置已删除，运行快照保留”。这与当前“删除连接仅关闭服务会话”的生命周期也应明确分开。

建议实现要点：

1. 增加 store 原子删除与 `DELETE /api/workbench/drafts/{id}`，携带 expected revision；不存在返回明确结果，已被别人更新返回冲突。
2. 与 `create_run(require_current_draft=True)` 的工作区写事务协调：运行先完成建档则保留运行；删除先完成则新的提交明确失败，不能生成缺少对应确认版本的任务。
3. 删除当前编辑配置时清除已保存 id/revision，并明确回到新配置或配置列表；避免下一次保存仍 PUT 已不存在的 id。未保存编辑的保留/放弃需要一致的界面流程。
4. 配置管理应一起提供新建、复制/另存、重命名、打开、导入、导出、删除与目标筛选。当前连接目标未匹配时可以查看/导出配置，但执行必须重新连接并检查。
5. 运行快照保持不可变；从旧快照恢复属于新建配置，不复活被删 id。配置文档不持久化连接密码或服务密钥。

## 4. 清空与 ID 重置：现有实现不可直接作为新版开关

### 4.1 当前真正可达的行为

`TableConfig.clear_before`、Python API 的 `fill`/`fill_from_config` 和旧 Web fill API 已存在。正式工作台在 `workbench_runtime.py` 中产生 `clear_not_supported`，并在实际执行时固定 `clear_before=False`，所以目前生成是追加。

`SQLAlchemyAdapter.clear_table()` 先对单表 `DELETE FROM`，再调用方言 sequence reset，并立即提交；不是独立的整库清空计划。`fill_from_config()` 按父表优先顺序逐表“清空后生成”，没有先按子表优先统一清空、再按父表优先生成的两个阶段。后续生成失败也不能恢复已经提交删除的旧数据。

### 4.2 SQLite 首次连接外键关闭缺陷：本轮已最小修复

根因在 `SQLAlchemyAdapter.connect()`：先 `inspect(engine)` 打开连接，再注册每连接 `PRAGMA foreign_keys=ON` 监听；首个已进 pool 的连接错过监听。临时真实 SQLite 中，父表被子表 `ON DELETE RESTRICT` 引用时，原实现允许删除父行，`PRAGMA foreign_key_check` 返回孤儿引用。

本轮仅把 inspector/optimizer 初始化移动到 listener 注册之后，没有扩展清空能力。新增 `tests/test_database/test_sqlalchemy_foreign_keys.py`，覆盖文件路径/URL 首次连接禁止孤儿插入、禁止删除被引用父行，以及 pool 重建后继续强制外键。修复前 4 failed/2 passed，修复后 6 passed。SQLite 官方要求每个连接独立启用外键，不能假设默认打开：[SQLite Foreign Key Support](https://www.sqlite.org/foreignkeys.html)。

### 4.3 PostgreSQL sequence 定位存在高风险缺陷：未修改、未实库验证

`src/sqlseed/database/_dialect.py:197` 的查询：

```sql
SELECT c.column_name,
       pg_get_serial_sequence(a.attrelid::regclass::text, c.column_name)
FROM information_schema.columns c
JOIN pg_attribute a ON a.attname = c.column_name
WHERE c.table_name = %s AND c.table_schema = 'public'
```

`a.attrelid` 没有约束到目标表，仅按列名连接。清空 `users(id)` 可以查询到其他含 `id` 表的 sequence，随后第 211 行对全部返回项执行 `ALTER SEQUENCE ... RESTART WITH 1`。这不是正常可接受的“重置当前表”。现有 PG 单元测试返回 mock 行，没有验证真实系统目录查询。

其他边界：硬编码 `public`；以 `split('.')` 拆已引用名称会误处理名称内的点；固定 1 忽略 sequence 自定义起点；raw DBAPI cursor 与捕获的 SQLAlchemy 异常边界不一致。建议先以精确 relation OID/namespace 与列定位所属 sequence，保持 identifier 原样安全引用，核验 owned/共享 sequence；必须补真实 PostgreSQL 回归后才开放新版 reset。

### 4.4 “ID 从 1”需要按列类型解释

| 场景 | 正确语义与当前边界 |
|---|---|
| SQLite 普通 INTEGER PRIMARY KEY rowid alias | 空表自动分配通常从 1；追加时根据现存 rowid 分配 |
| SQLite 显式 AUTOINCREMENT | 历史高水位存在 `sqlite_sequence`；清空数据本身不会自动清除历史序号，当前 primitive 会删除对应 sequence 记录 |
| SQLite 复合主键、WITHOUT ROWID、文本/UUID 主键 | 不存在通用可重置的自增序号；不能承诺全部 ID 从 1 |
| PostgreSQL serial / identity | 属于 sequence 语义；重启到“数据库声明的起点”和“强制起点 1”不同，需要反射与明确展示 |
| 编号模板、用户自定义序列生成器 | 是配置生成规则，与数据库 identity 不是同一设置 |

SQLite rowid 与 AUTOINCREMENT 的区别见 [SQLite Autoincrement](https://www.sqlite.org/autoinc.html)。PostgreSQL `RESTART` 不带值采用 sequence 声明的起点，`RESTART WITH 1` 指定 1，见 [ALTER SEQUENCE](https://www.postgresql.org/docs/current/sql-altersequence.html)。

### 4.5 外部依赖与事务必须先解决

- **清空范围与生成范围分开建模。** 清空父表会影响仍引用它的子表，不能只计算生成所需的上游；需要检查所有下游及跨 namespace 引用。用户只选父表时默认阻塞受影响范围外的数据，明确列出需处理的表，不自动扩大删除范围。
- **当前图快照不足以证明清空安全。** `workbench_schema._foreign_keys()` 丢弃 `ondelete/onupdate/deferrable` 等 options；只枚举默认 namespace，再补它引用的外部父节点，不枚举其他 namespace 指向本库的子 FK。触发器、分区/继承、sequence 所有权同样未纳入影响快照。
- **RESTRICT 与 CASCADE 不是相同方案。** 外键强制打开后 RESTRICT 可能阻止删除；CASCADE/SET NULL 则可能删除或修改未选表。即使重建相同 id，旧子行可能被错误关联到新的不同实体，不能靠“最终键都存在”判安全。
- **不要关闭 FK 来绕过检查。** 正确的替换方案需要删除阶段子表优先，生成阶段父表优先，并在明确事务边界内再次验证。如果要承诺失败恢复旧数据，清空与所有写入需共享事务或有等价的可验证恢复方案；当前单表清空提交、流式多次 batch commit 不满足这个承诺。
- **PostgreSQL 不应直接 TRUNCATE CASCADE。** PostgreSQL 的 CASCADE 会扩大到引用表；RESTRICT 要求所有被引用相关表同时列入，RESTART IDENTITY 仅重启被清空列拥有的 sequence，操作还会持有排他锁。它与 DELETE 的触发器行为不同：[PostgreSQL TRUNCATE](https://www.postgresql.org/docs/current/sql-truncate.html)。

后续界面建议：生成模式基础选项为“追加数据”；待上述后端方案完成后再提供“替换指定表数据”，其摘要独立展示将删除的表及行数、受影响引用、将生成的行数、每个 identity 的重置方式。ID 设置不能放在普通字段生成器中，也不能把危险动作藏在高级 JSON 中当成正式支持。

## 5. 信息架构建议

两导航目前能承载“连接一个库、编辑当前配置、执行、查看结果”的短流程；问题是配置的创建/复用/删除、全局连接上下文与编辑器全挤在弹窗，用户无法判断正在管理对象还是编辑内容。不能以顶部按钮数量或历史约束来决定导航。

推荐优先验证 **工作台 / 配置管理 / 运行记录** 三个任务入口：

- **工作台**：编辑当前配置，固定显示数据库与配置上下文；范围、字段、关系图；主动作生成，次动作检查/预览。基础引擎与语言留在可见设置区。清空/追加属于配置执行策略，在摘要再次核对。
- **配置管理**：可搜索、按数据库目标筛选的配置列表；新建、打开、复制、重命名、导入/导出、删除；每项显示目标、最后修改、版本。打开后到工作台，不再另造一套编辑页。
- **运行记录**：按目标、状态、时间筛选与分页；计划/实际、错误定位、不可变快照与复用。
- **数据库连接与 AI 服务设置**：顶栏统一全局上下文入口。连接弹窗应区分当前服务会话和未来可能新增的持久档案。只有在需求确认包含大量持久数据源、权限与数据库概览时，才考虑把“数据库”升为第四个导航，不能把今天的会话列表伪装成数据源管理产品。

另一可行方案是把“配置管理”作为首页、工作台作为其编辑详情，使一级导航只有“生成配置 / 运行记录”；这种两入口与当前“工作台 / 运行记录”含义不同，需要原型验证返回路径与新手直接生成体验。推荐先比较这两个方案，避免同时出现两个功能重复的配置编辑页。

视觉继续使用 v8 的密度、颜色、按钮层级、圆角和表格样式。变化应落实在对象归属与生命周期，而不是恢复旧页面或单纯增加更多顶栏按钮。

## 6. 验证记录与未决项

- SQLite 最小修复真实回归：6 passed，已观察修复前 4 个预期失败。
- 数据库层、adapter 编排、schema、relation：357 passed，1 skipped；跳过项需要 testcontainers/PostgreSQL，不能视作 PG 验证。
- Web 后端、orchestrator、public API 与 architecture 受影响回归：225 passed。
- 修改文件 ruff check/format 通过；database mypy 11 个 source files 通过；import-linter 3 个 contracts 通过。
- PostgreSQL sequence 缺陷仅有代码证据与官方语义核对，未运行 PostgreSQL。本轮保持正式 Web 清空/reset 不可用。
- 配置删除、导航调整、清空影响计划、原子替换属于本轮审计建议，尚未在本文中声称实现。
