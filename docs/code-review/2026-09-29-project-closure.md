# 2026-09-29 项目收尾核验

后续补充：对 `e8ecd29` 的 86 条 CodeFlow 告警逐项审查后发现 5 个可复现边界缺陷；本页记录的是当时门禁与验收场景，不代表后续审计发现已经处理。修复范围、告警处置与新提交验证见[CodeFlow 后续整改](2026-09-29-codeflow-hardening.md)。

[PR #20](https://github.com/sunbos/sqlseed/pull/20) 与后续修复的 [PR #21](https://github.com/sunbos/sqlseed/pull/21) 均已合并，最终代码核验基线为 `main` 的 `6d57912847df1bc2ddea108ff895faff3e2c8db4`。该基线的 CI、文档同步与部署、Sonar 质量门禁均已通过；原先未通过的三条真实模型用例已完成补充复验。以下分别记录各提交的证据及适用范围，不以旧检查替代新提交。本记录补充 [PR #19 历史验收](2026-09-28-project-closure.md)，保留此前失败、跳过、登录阻塞及复验过程，不扩大为所有模型、浏览器或功能均已验收。

## 原始要求与交付证据

| 要求 | 已完成的工作与证据 |
| --- | --- |
| 从设计、使用和首次体验审查 UI | 正式四页和浮层统一双语、字体、主题、控件及键盘焦点；流程步骤可导航，减少重复入口。默认配置补充预览行数和随机种子，AI 建议可在应用前微调。具体行为见[工作台指南](../web-workbench.md)和[组件标准](../design-review/glass-workbench/component-standard.md)，设计依据与实测范围分别记录。 |
| 降低检查与恢复的认知负担 | 清空失败保留重建意图，突出审阅并补齐关联表；不将追加规则通过表示成清空通过。无效数量定位具体表，数据库切换不继续绑定异库草稿。跨表循环显示实际引用与能力限制，不提供无效重试或追加建议。 |
| 联动核验数据库与五包代码 | 修复 AI 请求、缓存、验证和导出中的目标保真，拒绝缺表和错误目标；Core 读取保留特殊标识符、JSON / 日期表示及事务连接。真实 SQLite 回归覆盖预览不写库、清空影响范围、失败回滚、已提交行数、连接释放和外键完整性；CI 验证 PostgreSQL 与五包安装边界。 |
| 多角度边界与复杂关系图测试 | 26 表、55 条关系夹具覆盖多层、复合、自引用和跨表循环。修复悬停抖动、箭头缩放、手动百分比和 Ctrl / Command + 滚轮交互；循环范围的批量预览失败不再阻塞可独立预览的单表。回归同时覆盖非法输入、取消、迟到响应、旧样例、焦点与减少动态效果。 |
| 更新项目文档并清理过期产物 | 根与插件 README、指南、开发安装、迁移、CHANGELOG 和维护规则已与 manifest / 实现核对；品牌资源同步。已替代的报告和探针按[清理说明](history.md)处理，历史决策有明确归属。仓库无新增未跟踪临时产物，构建输出与原始验收证据位于系统 TEMP。 |
| 审查后推送并检查工作流 | PR #20、#21 已独立审查、推送及合并；PR 和合并后 main 的检查分别核对，main Sonar 三项误报已逐项处置并复核门禁。未降低检查门槛，未将 skipped 或扫描任务成功等同于所有诊断消失。 |

浏览器证据包含中英文、浅深主题、360px 窄屏、键盘、数据库切换、规则编辑返回预览，以及复杂图的慢移和缩放。清空恢复实测从 5 表扩至 9 表，实际写入 900 行，未选表计数保持不变且外键检查为空；正式安装环境完成 Mimesis 安装、卸载和服务恢复。最新界面另复查循环说明、NULL 规则、缩放及独立单表预览。这些结论限定于对应场景与 Windows Chromium，不代表所有组件组合、浏览器、操作系统或整站 WCAG 均已验收。

## 检查结果及提交归属

- PR #20 合并前最终源码验证：Python **4,030 passed、95 skipped、17 warnings**；Node **958 passed、0 skipped**。跳过原因与原始失败记录保留，不能将跳过计为成功。
- Ruff、格式检查、mypy（173 个源文件）、import-linter（3 项边界）、文档同步和 MkDocs strict 构建通过。
- Web wheel 构建、严格元数据及新增静态资源核对通过；对应提交的 CI `packages` 另验证五包构建、已安装入口及最小环境。没有执行 PyPI 发布，不以本地 wheel 代替正式发行验收。
- `unique_adjuster` mutation 最终 **246 killed、0 survived**。初轮 1 项耗时可疑（`suspicious`）及原门槛下的实际复验记录均保留；此后该变异范围源码未变，不扩大为全项目 mutation 覆盖。
- PR 提交 `a7833fb` 的 [CI](https://github.com/sunbos/sqlseed/actions/runs/36486295658) 和[文档同步](https://github.com/sunbos/sqlseed/actions/runs/36486295238) 通过，SonarCloud PR 门禁、Codecov patch 和 CodeFlow 检查通过；CodeFlow 仍有维护告警。PR 的 `docs` 部署按条件跳过，严格构建由 lint 执行。
- PR #20 合并提交 `2a2ee08` 的 [main CI](https://github.com/sunbos/sqlseed/actions/runs/36487610479) 和[文档同步](https://github.com/sunbos/sqlseed/actions/runs/36487609916) 通过，包括 Linux Python 3.10 / 3.12 / 3.13、Windows、macOS、PostgreSQL、property tests、五包验收及 Pages 构建和部署。当时 main 的独立 Sonar 门禁仍未通过；最终处置单独记录于下文。
- PR #21 最终提交 `535439b` 的 [CI](https://github.com/sunbos/sqlseed/actions/runs/36497580198) 和[文档同步](https://github.com/sunbos/sqlseed/actions/runs/36497579932) 通过，连同 SonarCloud、Codecov patch 和 CodeFlow 共 13 项成功检查；PR 文档部署仍按条件跳过。CodeFlow 为 0 error、86 warning，不以通过状态宣称零告警。
- PR #21 合并提交 `6d57912` 的 [main CI](https://github.com/sunbos/sqlseed/actions/runs/36498593220) 和[文档同步](https://github.com/sunbos/sqlseed/actions/runs/36498592867) 通过，包括测试矩阵、五包安装验收以及文档构建和部署。同一提交的 SonarCloud GitHub 检查与 main 质量门禁均已复核成功。

## 真实模型复验与 Sonar 处置

### 真实模型

历史 4 项真实 LLM 失败中，缺表诊断的确定性代码问题已修复并回归；另外 3 项在 2026-09-29 完成原用例复验。backend 保持 `lm_studio`，模型保持 `google/gemma-4-e2b`，没有用其他模型替代。

| 用例 | 保留的历史失败事实 | 本轮最终复验 |
| --- | --- | --- |
| `tests/integration/test_ai_real_llm.py::TestAISuggestCLIRealLLM::test_ai_suggest_no_verify_produces_well_formed_yaml` | 返回空建议，CLI 退出码为 1。 | 通过 |
| `plugins/sqlseed-ai/tests/test_ai_plugin.py::TestSchemaAnalyzerDialect::test_analyze_schema_sqlite_real_llm` | 返回 `None`，当时原因未证实。 | 通过 |
| `plugins/sqlseed-ai/tests/test_ai_plugin.py::TestSchemaAnalyzerDialect::test_analyze_schema_llm_response_structure` | 返回 `None`，当时日志明确记录 `Connection error`。 | 通过 |

2026-09-29 初次补查时，`localhost:11434/api/tags` 和 `localhost:1234/v1/models` 均在 2 秒内未返回。随后通过既有 `lms` CLI 唤醒本机 LM Studio，加载已经下载的 E2B 模型，以 8192 context 恢复服务。原始 `full-project-pytest.log` 和仅记录 4 项跳过的 `real-llm-four-rerun.log` 保留；后来的服务恢复不能把旧跳过改写成通过，也不能把全部历史失败归因于网络。

服务恢复后的首轮为 **2 passed、1 failed**，失败仍在 CLI。单独诊断重放得到 **1 passed**，但捕获的响应拼接了 `users` 与 `orders` 两个 JSON 对象；这次偶然通过不能替代修复，也不能反推首轮空建议的具体原因。随后收紧单表上下文，明确其他表只作参考、仅返回请求表的一个 JSON 对象，并为 CLI 非流式直接分析补齐空回答、无效 JSON、截断及终级停止的安全诊断，没有扩大请求预算或覆盖失败时的旧 YAML。

修复后的三个原用例合并运行得到 **3 passed，64.71 秒**。保持原模型、300 秒 timeout、4096 输出 token 上限及 0.3 temperature，保留原断言和重试预算。证据为本任务 `sqlseed-closeout-real-llm-10f7840cdd4c4abda67df4ece649ce3b` 临时目录中的 `pytest-repo-venv.log`、`diagnostic-pytest.log`、`pytest-final.log` 和 `results-final.xml`。

这三项验证范围是 CLI YAML 与 schema 分析，不是 `fill` 写入或任意模型的推理质量保证。固定 HTTP / SSE 与真实 SQLite 回归另验证协议、请求次数、输出文件及数据库不变；这些确定性回归与真实模型结果分别记录。

独立审查另发现流式路径没有检查长度截断标记，真实 SSE 回归证明可解析的截断前缀曾被导出。后续修复为 `call_llm_streaming()` 增加默认关闭的 `strict_json` 参数，仅由 CLI 直接分析显式启用；空终止帧中的 `finish_reason=length` 同样拒绝导出。原 Python 调用与 verification/refiner 默认行为保留，不将非流式真实模型复验扩张为全部流式模型已经验收。

该修复的五文件定向回归为 **182 passed，48.14 秒**，包含新增的 28 项响应诊断回归，核对流式 / 非流式、两种直接分析选项、独立终止帧、Python 默认兼容、既定请求次数、输出 YAML 与数据库不变。修复前的失败记录保留；此结果不替代后续提交的完整 CI。

后续扫描针对新增代码报告复杂度问题，已提取流式进度节流、解析策略和上下文超限提示，独立审查确认默认行为、错误分类及请求预算保持，同组回归复跑通过；最终提交 `535439b` 的远端结果见上文。另有 4 条 CodeFlow 导入顺序告警，均位于新测试的 `pytest.importorskip("sqlseed_ai")` 之后：这些导入必须等待可选插件存在性检查，提前导入会破坏缺插件时的跳过行为。逐项核对后保留该顺序，不将其视为阻断，也未关闭扫描规则。

### main Sonar 逐项复核

main 此前 `new_security_rating` 为 C，要求 A；PR 门禁已通过，两者的基线和新代码周期不同。以下三个工作流位置未由 PR #20 修改，最初因会话未认证无法提交处置。2026-09-29 会话恢复后，已分别提交具体英文审查依据并标为误报；公开 API 回读三项均为 `status=RESOLVED`、`resolution=FALSE-POSITIVE`，各有一条审查说明。

| Issue / 规则 | 位置与已提交的误报依据 |
| --- | --- |
| `AaDlnfI37VHKXLDTpDFo` / `githubactions:S8541` | `.github/actions/setup-env/action.yml`：该步安装被测仓库的本地 editable 包，使用 `--no-deps --no-build-isolation`；第三方依赖此前已按锁定哈希安装。 |
| `AaDlnfGQ7VHKXLDTpDFm` / `githubactions:S8541` | `.github/workflows/doc-sync.yml`：同样只安装本地 Core / CLI，远程依赖由前置锁定步骤负责。 |
| `AaDlnfIl7VHKXLDTpDFn` / `yaml:S2068` | `.github/workflows/ci.yml`：密码属于一次性 PostgreSQL 测试 service，通过 runner 的 localhost 访问临时 testdb，不是生产凭据。 |

处置后，main 质量门禁 API 返回 `OK`，`new_security_rating=1`（A），其他条件均为 `OK`，`ignoredConditions=false`。分析 revision 为 `6d57912847df1bc2ddea108ff895faff3e2c8db4`，analysis key 为 `c4f71ab2-e7f1-41cb-8903-f4cd581101e3`；[同一提交的 GitHub 检查](https://github.com/sunbos/sqlseed/commit/6d57912847df1bc2ddea108ff895faff3e2c8db4/checks)中 SonarCloud Code Analysis 也已成功。未关闭规则、调整阈值或扩大排除范围。

Sonar Summary 同时显示 Passed，并按该 main 分析的新代码周期记录 245 项 New Issues；这些非阻断维护项仍然保留，不代表 PR #21 新增了 245 项问题。该分析未导入覆盖率，`new_coverage` 条件虽为 `OK`，但没有 `actualValue`，不能据此声称覆盖率达到 80%。门禁通过不代表全仓零诊断或所有代码均有测试覆盖。

## 能力与清理边界

- 通用跨表循环生成、组合自引用初始化、PostgreSQL 清空重建仍未接入。界面明确拒绝并提供定位说明，是本次交付的能力边界；本轮收尾不要求新增这些功能。
- macOS / Linux 的真实视觉、Safari / Firefox 和完整辅助技术验收没有执行。CI 的系统兼容性测试不能替代这些实测。
- 用户仍在使用的本机 51196 / 8630 预览服务及其隔离数据库有意保留，不声明“零后台进程”。TEMP 中原始日志、截图、失败与复验记录作为证据保留；仓库内归属不明的历史 `test.db`、共享虚拟环境和缓存没有删除。清理范围是已确认无用的项目产物，不是用户数据或仍在使用的预览环境。

原始验收输出保存在本任务 TEMP 目录，持久交付依据为以上提交、PR、CI artifact 及维护文档。后续补充提交必须重新核对相应检查，不沿用本页数字代表新源码已经通过。
