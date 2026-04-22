# 手工测试文档体系设计

**日期**：2026-04-22
**状态**：已确认

---

## 1. 背景

`sqlseed` 当前已经形成三个可独立分发、又彼此联动的使用单元：

- 核心包 `sqlseed`
- 可选 AI 插件 `sqlseed-ai`
- 可选 MCP 服务器 `mcp-server-sqlseed`

现有仓库文档已经能够解释项目目标和主要能力，但对于“真实使用者如何手工验证系统是否可靠”这一目标，仍缺少一套可直接执行的测试文档。与此同时，`docs/` 目录中还存在部分与当前实现不一致的描述，例如：

- `ColumnMapper` Level 3 规则数仍写为 67，而当前实现为 68
- `DataProvider` 仍按旧的 `generate_*` 形状描述，而当前 Protocol 的核心入口是 `generate(type_name, **params)`
- `docs/evaluation.md` 中对 `tests/test_core/` 的现状描述已经过时

因此，这次工作的目标不是新增功能，而是建立一套面向真实使用者的手工测试文档，并同步修正会误导测试执行的陈旧文档事实。

## 2. 目标

本次设计要指导产出一组可直接执行的手工测试文档，用于帮助用户从真实业务场景出发验证：

1. `sqlseed` 核心主路径是否可靠可用
2. `sqlseed-ai` 在理想路径与异常路径下是否表现合理
3. `mcp-server-sqlseed` 的 server/resource/tool 契约是否稳定
4. 当前项目在实际使用中还存在哪些功能缺陷、边界问题和回归风险

这套文档必须满足以下要求：

- **场景优先**：优先从真实使用链路而不是内部模块名称组织
- **可执行**：每条用例都要包含具体前置条件、操作步骤和预期结果
- **可记录**：文档本身可作为执行清单，允许测试者逐条勾选
- **可定位**：失败时能快速判断问题落在核心包、AI 插件还是 MCP 服务器
- **可复测**：后续版本可直接复用同一套文档作为回归清单

## 3. 已确认的关键决策

在头脑风暴阶段已经确认以下决策：

- **范围覆盖三个分发单元**：`sqlseed`、`sqlseed-ai` 和 `mcp-server-sqlseed` 一起纳入，而不是只覆盖核心包。
- **文档拆分为三份**：按包边界拆分，而不是按测试层级或风险维度拆分。
- **文档组织方式**：按真实用户场景从高优先级到低优先级组织，顺序固定为 `P0 -> P1 -> P2 -> P3`。
- **每条用例前使用复选框**：文档直接作为执行单使用，测试完成后可勾选。
- **每条用例固定粒度**：必须包含用例 ID、用户场景、测试目标、前置条件、步骤、预期结果、重点观察、边界延伸和结果记录。
- **纠偏同步进行**：`docs/architecture.md` 和 `docs/evaluation.md` 中已确认的陈旧事实一并修正，避免测试者被旧文档误导。
- **不把手工测试文档放在 `docs/superpowers/`**：`docs/superpowers/` 继续保留给 agent 设计和计划资产；手工测试文档放在常规文档路径下，面向人工执行。

## 4. 交付物定义

### 4.1 手工测试文档

本次工作生成三份新的手工测试文档：

- `docs/manual-tests/2026-04-22-sqlseed-core-manual-test.md`
- `docs/manual-tests/2026-04-22-sqlseed-ai-manual-test.md`
- `docs/manual-tests/2026-04-22-mcp-server-sqlseed-manual-test.md`

### 4.2 文档纠偏

同步修正以下现有文档中的已知失真：

- `docs/architecture.md`
- `docs/evaluation.md`

## 5. 读者与使用方式

这些手工测试文档的默认读者不是维护者自己，而是“刚接手项目、希望通过使用场景判断产品是否可靠的使用者/测试者”。因此文档写法必须满足以下假设：

- 测试者可能不知道内部模块名
- 测试者更关心“我要做什么”和“预期会看到什么”
- 测试者需要判断功能是否真的能用，而不是只关心代码是否优雅
- 测试者需要在失败时快速知道问题大概属于哪一层

因此文档要先给出：

- 安装与准备步骤
- 推荐执行顺序
- 需要的数据库夹具
- 可跳过项与其风险

然后再进入用例清单。

## 6. 三份文档的分工与边界

### 6.1 核心包手工测试文档

文件：`docs/manual-tests/2026-04-22-sqlseed-core-manual-test.md`

该文档负责验证 `sqlseed` 核心主路径和绝大多数基础能力，包括：

- Python API：`fill()`、`connect()`、`preview()`、`fill_from_config()`、`load_config()`
- CLI：`fill`、`preview`、`inspect`、`init`、`replay`
- 配置：YAML/JSON、模板生成、快照回放
- 生成主链路：自动映射、外键、SharedPool、派生列、transform、enrich、唯一约束、批量插入
- 数据库层：`sqlite-utils` 与 raw sqlite3 回退路径
- 可选 provider 与缺依赖时行为
- 插件契约中能直接影响核心体验的行为，例如 batch transform 和 SharedPool hook

其优先级分层如下：

- **P0 真实主路径**
  - 零配置单表填充
  - preview 后正式填充
  - 多表外键自动维护
  - 基于 YAML/JSON 配置生成
  - snapshot 保存与 replay 回放
- **P1 常见进阶场景**
  - 指定 provider / locale / seed
  - `batch_size` / `clear_before`
  - 自定义列规则
  - 派生列与 transform 脚本
  - enrich 利用已有数据分布
- **P2 边界与异常**
  - nullable / default / autoincrement / 空表
  - 复合唯一、约束回溯
  - provider 缺失、未知 generator、配置非法
  - `GenerationResult.errors` 软失败路径
- **P3 回归热点**
  - SharedPool 隐式关联
  - hook 链式 batch transform
  - PRAGMA 优化与恢复
  - `choice` / `foreign_key` / seed 稳定性

### 6.2 AI 插件手工测试文档

文件：`docs/manual-tests/2026-04-22-sqlseed-ai-manual-test.md`

该文档负责验证 `sqlseed-ai` 的用户价值和异常恢复能力，包括：

- 安装与可选导入边界
- `AIConfig` 配置与环境变量兼容行为
- `SchemaAnalyzer`
- `AiConfigRefiner`
- `sqlseed ai-suggest`
- `sqlseed_ai_analyze_table` / `sqlseed_pre_generate_templates`
- 缓存与 schema hash

其优先级分层如下：

- **P0 真实主路径**
  - 为已有表生成 AI YAML 建议
  - AI 产物直接喂给核心生成
  - 自纠正闭环把无效配置修正到可执行
- **P1 常见进阶场景**
  - 切换 model / API key / base URL
  - 模板池是否正确只作用于复杂列
  - cache 命中与失效
- **P2 边界与异常**
  - API key 缺失
  - base URL 错误
  - 模型不可用
  - 非法 JSON / 响应结构异常
  - 网络失败和 AI 不可用时的软失败
- **P3 回归热点**
  - `SQLSEED_AI_*` 与 `OPENAI_*` 双环境变量兼容
  - AI 不可用时不拖垮核心主流程

### 6.3 MCP 服务器手工测试文档

文件：`docs/manual-tests/2026-04-22-mcp-server-sqlseed-manual-test.md`

该文档负责验证 server 层契约和跨包联动，包括：

- 模块入口：`python -m mcp_server_sqlseed`
- resource：`sqlseed://schema/{db_path}/{table_name}`
- tools：`sqlseed_inspect_schema`、`sqlseed_generate_yaml`、`sqlseed_execute_fill`
- 序列化 shape
- 与核心包、AI 插件的联动闭环

其优先级分层如下：

- **P0 真实主路径**
  - 启动 server
  - inspect schema
  - generate yaml
  - execute fill 闭环
- **P1 常见进阶场景**
  - resource 读取指定表 schema
  - 先 AI 生成 YAML，再执行填充
  - tool 返回结构是否适合客户端消费
- **P2 边界与异常**
  - 非法 db path
  - 不存在的表
  - `yaml_config` 过大
  - 未安装 AI 插件时 `sqlseed_generate_yaml` 的退化输出
- **P3 回归热点**
  - schema hash 稳定性
  - 对象序列化 shape 稳定性
  - 工具报错时 server 不崩

## 7. 文档之间的依赖关系

三份文档不能完全彼此独立，因为它们共享环境和部分测试数据。为避免重复与不一致，采用以下依赖策略：

- 核心包文档负责提供“通用测试数据库准备”与基础夹具
- AI 文档直接引用核心文档中的基础数据库与环境准备，不重复复制一整套
- MCP 文档引用核心文档准备好的数据库，并额外说明 server 启动与客户端调用方式
- 每份文档都要说明“如果跳过上一份文档，会缺失哪些前置条件”

## 8. 用例写法与模板

每条用例都使用复选框开头，使文档可直接作为执行清单。例如：

```md
- [ ] CORE-P0-001 零配置填充单表

  用户场景：我刚装好 sqlseed，想最快确认它能自动给 users 表生成可用数据。
  测试目的：验证默认 provider、默认映射和默认批量写入主路径可用。
  前置条件：...
  操作步骤：
  1. ...
  2. ...
  预期结果：
  1. ...
  2. ...
  重点观察：
  - ...
  边界延伸：
  - ...
  结果记录：
  - 通过/失败：
  - 备注：
```

固定字段为：

- 用例 ID
- 用户场景
- 测试目的
- 前置条件
- 操作步骤
- 预期结果
- 重点观察
- 边界延伸
- 结果记录

## 9. 场景优先级与排序规则

为确保测试者先验证最重要的价值，再逐步下沉到高风险边界，三份文档统一采用以下排序原则：

1. **P0 真实主路径**
   - 最接近日常真实使用
   - 一旦失败，说明产品主价值尚不可靠
2. **P1 常见进阶场景**
   - 高概率真实出现
   - 常见于“初次可用后继续深入使用”的阶段
3. **P2 边界与异常**
   - 重要但不高频
   - 直接影响稳定性、可恢复性和用户信心
4. **P3 回归热点**
   - 用于版本升级、重构后复测
   - 重点锁定脆弱契约和容易回归的行为

## 10. 覆盖策略：从业务价值到技术边界

这组文档不采用“内部模块全覆盖”的写法，而采用“业务价值主线 + 技术边界补齐”的策略：

- 先证明使用者最关心的事情能不能做成
- 再验证真实使用中常见的定制和联动
- 再下沉到边界、异常、软失败和退化路径
- 最后给出版本回归时最值得优先复测的热点清单

这种策略的目的不是减少覆盖，而是让测试顺序更接近真实价值判断路径：

- “它有没有用”
- “它是否足够灵活”
- “它会不会在麻烦场景下坏掉”
- “它最可能在哪些地方回归”

## 11. 需要同步修正的现有文档事实

至少要同步修正以下已确认的陈旧事实：

- `docs/architecture.md`
  - `ColumnMapper` 内置精确规则数从 67 改为 68
  - `DataProvider` 描述从旧的 `generate_*` 主接口改为当前 `generate(type_name, **params)` 事实
- `docs/evaluation.md`
  - `ColumnMapper` 规则数从 67 改为 68
  - `tests/test_core/` 覆盖情况从旧状态改为当前真实状态

如果在撰写手工测试文档过程中发现其他会直接误导测试执行的陈旧描述，也应一并修正，但不扩展为大规模无关文档重写。

## 12. 非目标

本次工作明确不做以下事情：

- 不新增自动化测试代码
- 不修改核心实现逻辑以“配合文档”
- 不把全部内部实现细节都塞进手工测试文档
- 不重写整个 README
- 不把所有 `docs/` 文件统一大翻修

本次工作的边界是：

- 产出可执行的三份手工测试文档
- 修正会直接误导测试的现有文档事实

## 13. 成功标准

这次工作的成功标准不是“文档更漂亮”，而是：

1. 测试者可以不依赖维护者口头解释，直接按文档执行手工测试
2. 测试者能按包边界逐步验证 `sqlseed`、`sqlseed-ai` 和 `mcp-server-sqlseed`
3. 每条用例都有明确、可观察的预期结果，而不是模糊检查项
4. 文档足够全面，能帮助测试者系统发现当前版本潜在 bug
5. 现有 `docs/` 中会误导手测的陈旧事实被纠正

## 14. 后续执行顺序

在该设计被确认后，执行顺序固定为：

1. 新建 `docs/manual-tests/` 目录
2. 先写核心包手工测试文档
3. 再写 AI 插件手工测试文档
4. 最后写 MCP 服务器手工测试文档
5. 同步修正 `docs/architecture.md` 与 `docs/evaluation.md`
6. 自查三份文档是否：
   - 覆盖了主路径
   - 覆盖了高风险边界
   - 具有可勾选的执行结构
   - 没有明显占位符或模糊描述
