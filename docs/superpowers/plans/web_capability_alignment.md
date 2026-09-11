# Web 能力对齐审计（2026-08-31）

> **历史审计；旧 IA 已 superseded（2026-09-07）。** 能力清单仅代表当时盘点，第 4–6 节目标导航、落地优先级和向导决策不再执行。当前依据为 [v8 整体重建契约](2026-09-07-web-v8-rebuild.md)，历史模块/API 存在不要求在新产品显示对应页面。

> 动机：用户实测反馈 heal 页与向导功能重叠、作用对象不清。本文对 5 个包做
> 颗粒度对齐盘点，给出信息架构（IA）重构方案与分阶段落地清单。

## 一、能力清单（按包，颗粒度=用户可感知的功能点）

### Core（src/sqlseed，纯库）
| # | 能力 | 备注 |
|---|------|------|
| C1 | 连接 SQLite/PostgreSQL | db_path 与 url 互斥 |
| C2 | Schema 内省（列/类型/FK/索引/唯一检测/topo 序） | `detect_unique_columns`、`get_topological_table_order` |
| C3 | 9 级列映射链 + 36 生成器 + provider 回退 | faker 必选 / mimesis 可选 / base 兜底 |
| C4 | 列参数：min/max、pattern、choice、weighted_choice、length、precision、日期边界、星期 | 见 `_dispatch` 白名单 |
| C5 | 派生列 derive_from + 表达式（DAG 排序、simpleeval 5s 超时） | |
| C6 | CHECK 处理：单列字面钳制（确定性）、跨列 inequality 约束回溯 | 跨列/OR 留给 AI |
| C7 | 唯一保障：单列/复合唯一、ConstraintSolver 回溯、autoincrement PK skip | |
| C8 | 外键：拓扑排序、父表采样、空父表两遍填充、random/coverage 策略 | 88b4579 |
| C9 | 词表 enrichment + 共享池隐式关联 + 模板池 | pluggy hook 驱动 |
| C10 | transform 脚本（行/批变换） | `load_transform` |
| C11 | 种子/locale 可复现、批量流式写出、PRAGMA 优化 | |
| C12 | 配置：YAML/JSON 读写、SnapshotManager（save/load/replay） | CLI replay 已用 |
| C13 | 公共 API：fill/connect/preview/fill_from_config/load_config | |

### CLI（sqlseed-cli）：fill / preview / inspect(--show-mapping) / init / replay
### AI（sqlseed-ai）：L1 contracts → L2 validator（单列/跨列/复合FK/shadow-FK/方言）
→ L3 repair → L4 heal（4 级+降级）→ L5 auto-heal（时间预算/子图）；CLI：ai-suggest、ai-analyze、auto-heal
### MCP（mcp-server-sqlseed）：generate_yaml、execute_fill；AI 插件另有 3 个 Gemma 工具

## 二、Web 现状（页面 × API）
| 页面 | 使用的 API | 覆盖能力 |
|------|-----------|---------|
| 连接 connect | POST /connections、/fs/browse、/meta/ai | C1 |
| 数据生成 wizard | schema/mapping/yaml-template/preview/fill/jobs/heal/auto | C2 C3 C4 C5(只读) C7 C8 C11 + heal/auto |
| 数据浏览 browse | rows、query | 查询 |
| AI 分析与修复 heal | heal/validate、heal/repair、heal/auto、/ai/config | L2/L3/L5（YAML 文本流） |
| 系统面板 meta | /meta/info、/meta/generators、/meta/hooks… | 元信息 |

## 三、差距与重叠（审计结论）
1. **重复**：heal③（heal/auto）≡ 向导「AI 一键生成」（同接口、同产物）。
2. **弱重叠**：heal② 修复 vs 核心 fill 时兜底（C6/C7/C8）vs 向导面板硬约束锁定——同一约束问题有三层防线，用户无从分辨谁在起作用。
3. **web 缺失的能力**：C12 snapshot/replay（无任何入口）；C10 transform（无）；C9 词表管理（无）；C5 表达式编辑（只读）；CLI inspect 的映射诊断视图（mapping 数据有、九级链路可视化无）；CLI init 的示例配置生成（无）。
4. **错位**：AI 配置面板挂在 heal 页（会话级切换后端），职能上属于系统设置。

## 四、目标信息架构（按真实使用流程组织）
用户旅程：连接 → 看结构 → 配配置（逐列 / AI）→ 体检 → 预览 → 填充 → 结果/历史 → （重放/浏览）

| 导航项 | 内容 | 吸收 |
|--------|------|------|
| 连接 | 现状不变 | — |
| 数据生成（主流程） | 三步向导；**step3 新增「生成前体检」**（组装当前配置 → heal/validate → 问题列表+一键修复回填）；AI 一键生成保留于此（唯一入口） | 吸收 heal③ 职能 |
| 配置中心（新） | YAML 工作台：粘贴/导入模板/向导导出、校验、修复、diff、下载 .yaml；定位=高级用户与文件交换（YAML in/out） | 承接 heal①②；删除 heal③ |
| 数据浏览 | 现状；可加行数/空值率统计 | — |
| 任务与历史（新或并入系统面板） | /jobs 已有；新增 snapshot 重放入口（对应 CLI replay） | 补 C12 |
| 系统面板 | meta/* + **AI 后端配置**（从 heal 页迁来） | 纠正 AI 配置错位 |

## 五、落地清单
- **P0（去重+流程闭环）**：向导 step3「生成前体检」；heal 页删③、导航改名「配置中心」；AI 配置迁至系统面板。
- **P1（补缺失）**：snapshot 重放入口；映射九级链路诊断视图；派生列表达式编辑（含超时提示）。
- **P2（增强）**：词表/共享池管理 UI；transform 脚本编辑器；浏览页数据质量统计。

## 六、决策记录
- 2026-08-31：确定 heal 页重定位为「配置中心」（YAML 工作台），auto-heal 唯一入口归向导。
