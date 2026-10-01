# 2026 年 10 月 1 日质量核验

后续扫描核验更新至 2026 年 10 月 2 日。

本记录核验 [PR #26](https://github.com/sunbos/sqlseed/pull/26) 的生成行为和质量检查。该 PR 尚未合并；Sonar 仍有一条编码扫描告警需要定位。本文保留具体提交与实测边界，不能由通过的门禁推定所有工具均为零警告。继续使用现有自动分析；迁移 CI 或接入 CodeRabbit CLI 均不作为本轮的必经步骤。

## 数据库生成范围

SQLite 追加模式支持已有有效父键的单列物理外键循环。检查、预览与执行使用写入前冻结的父键池；实际追加将所有所选表置于同一事务，任一写入失败回滚本次全部新增记录，原有记录保留。普通非循环追加仍按原有批次提交。

隔离的 26 表业务数据库使用 Base 引擎，每表追加 100 行，新增 2,600 行，原有 28 行保留，总行数为 2,628，外键检查为零。浏览器另以每表 3 行验收：新增 78 行，原有 28 行保留，控制台没有 errors 或 warnings。这两组数据只证明对应夹具，不代表任意 schema 均受支持。

新增回归确认普通子表能引用同次追加的新父键，显式配置关联继续生效，而循环边始终引用已冻结的旧父键。策略放在外键解析环节，继承原有规格解析参数，不修改 Core public API。

CodeRabbit 后续审查发现冻结池复用了普通来源检查的 10,000 条上限，小于 Core 单列外键的 100,000 条上限。冻结池已改为 100,000，普通检查仍为 10,000；查询上限严格限定正整数。真实 SQLite 验收使用 10,003 个已有父键，实际追加的记录包含第 10,001–10,003 个键，外键检查为零。循环、执行、运行状态与持久化回归共 114 passed、零 warnings，读数和写入均未使用数据库 mock。

从空表生成的跨表循环、组合或重叠外键或配置关联构成的循环、PostgreSQL 循环追加及循环清空重建仍明确阻止。不能用调整生成行数、NULL 比例或重置自增计数解除这些限制；没有引入通用 backfill 或关闭数据库约束。

## 真实模型验收

使用本机已有的 LM Studio 与 `google/gemma-4-e2b`，在隔离数据库上执行真实 AI、CLI、MCP 和 healer 集成测试，启用 `--require-llm`，不将服务缺失或模型错误改成跳过。

首次完整运行 16 项：15 项通过、1 项失败、零 warnings。失败发生在 CLI 直接建议模式：本地模型返回无效 JSON，CLI 保留失败状态且没有写出配置。严格本地调用当时仅以提示词要求 JSON，未请求采样格式约束。

修复后严格 LM Studio 调用使用 JSON Schema 对象采样，Ollama 使用 JSON 对象模式；流式与非流式保持一致。只在服务明确不支持该格式时回退一次，认证、无关 400 与服务器错误继续失败。生成参数、提示预算、标识符保护和严格业务解析保留。完整严格复验结果为 **16 passed、79 deselected、零 warnings**，耗时 661.51 秒；原失败 CLI 用例包含在该套复验中。MCP 验收包括真实模型请求和隔离 SQLite 写入，不由模拟响应推定。

本轮本地 Ruff 检查与格式核验通过（492 个文件），mypy strict 通过（175 个源文件），三项 import-linter 合约与 `pip check` 通过。Web 前端回归 1,022 passed、零 failed 或 skipped；冻结来源与普通外键行为回归 69 passed、零 warnings。独立评审未发现新的可行动问题，另实跑 AI 协议回归 82 passed、零 warnings。

## 已有远端检查

[CI 36892761008](https://github.com/sunbos/sqlseed/actions/runs/36892761008) 对应提交 `c06bca75e50b13b6e57aeff9edac82f4a3477b9e`，包含外键解析策略重构、本地 JSON 格式修复、配置关联与事务快照回归、真实 PostgreSQL 工作台测试、冻结池上限与审查修复：

| 环境 | 结果 |
| --- | --- |
| Linux Python 3.10、3.12、3.13 | 各 4,314 passed、47 skipped |
| Windows Python 3.12 | 4,265 passed、96 skipped |
| macOS Python 3.12 | 4,252 passed、109 skipped |
| PostgreSQL integration / property tests / doc-sync | 59 / 3 / 18 passed，零 skipped |
| 其他 CI 门禁 | lint、packages 全部通过；Node 1,022 passed，零 failed |

上述 pytest 日志没有 warnings；两份 Codecov 上传均通过 GPG 与 SHA256 校验、上传明确对应此提交并清理隔离 keyring。Codecov patch 门禁通过，显示覆盖率为 99.06%，目标为 89.16%。project check 没有发布，历史提交也仅发布 patch，不能虚构其成功状态。Actions 没有 error 或 warning annotations；macOS runner 容量提示是 notice。Sonar 的扫描器告警另行核验，见下文。PR 上跳过文档部署属于既有规则，strict MkDocs 构建仍执行。

针对先前 Codecov 评论列出的 8 行新增未覆盖代码，已补真实 SQLite 回归，验证配置关联成环阻止清空重建、范围内外依赖边界、检查及预览不改变原有记录和自增序列，以及非法事务标记不落盘、运行快照重启后保持且不能篡改。两份完整测试文件共 50 passed、零 warnings，定向覆盖报告确认命中其中 5 行。PostgreSQL 检查、预览和绕过前端直接启动的三个真实服务测试在 CI 全部通过，拒绝发生在创建任务之前，旧记录、序列与草稿均保持不变。最新覆盖报告仅剩两行未覆盖：违反已固定构造契约时的防御异常，不通过破坏契约的 mock 凑覆盖率。

PostgreSQL 测试服务已显式使用 SCRAM 密码认证，真实 CI 完成初始化及全部 59 项集成测试，原有 `initdb trust` warning 消失。原始数据库日志仍包含故意触发的 FK/触发器拒绝，用于证明失败回滚；不能把这种预期测试证据描述为产品报错，也不能宣称日志完全没有 ERROR 字符串。没有过滤日志或降低测试要求。

CodeRabbit 指出的覆盖率上传签名者问题已复现：旧隔离 keyring 可在上游二次导入时接受另一主键，并通过它签署的文件。修复在核验并导入唯一官方主键后，限制后续导入只能更新既有主键，并关闭自动导入/获取。真实 GnuPG 验证确认官方签名继续通过，另一主键的有效签名、篡改的官方数据及无效签名均被拒绝；未执行任何测试上传器。上游签名、SHA256、OIDC 和上传失败门禁均保留，`c06bca75` 的 Linux/Windows 原始上传日志均确认新限制实际加载、官方签名与 SHA256 通过、准确提交上传完成，隔离 keyring 清理成功。

本轮 `sync_docs.py --check` 与 strict MkDocs 构建通过，没有项目构建 warning。Material 主题仍直接输出一条关于未来 MkDocs 2.0 的[上游迁移提示](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)；它不经过 MkDocs 的警告计数，不能据此宣称原始输出完全没有警告字样。已安装与 CI 的 MkDocs 为 1.6.1，Material 依赖明确要求 `mkdocs<2`。根 `uv.lock` 已将主题对齐已验收的 9.7.7，其他依赖版本不变，三个已有锁文件均校验通过。不为消除该提示屏蔽输出或降低版本。

本地 mutation gate 的 246 个 mutant 全部被杀死，survived、suspicious、timeout、skipped、untested 均为零；目标源码与两份测试哈希与本轮工作树一致。该定向门禁不能代替完整产品测试。

## 外部扫描与待完成事项

- [提交 `c06bca75e50b13b6e57aeff9edac82f4a3477b9e` 的 CodeFlow 扫描](https://app.getcodeflow.com/github/sunbos/sqlseed/commits/c06bca75e50b13b6e57aeff9edac82f4a3477b9e) 返回 “Good job! No issues.”，0 errors、0 warnings。上一提交的 4 条测试代码 warning 已消除：共享重复的循环来源定义，删除 docstring 后多余的 `pass`，整理空列表比较。全部输入、事务与真实结果断言保留；相关两文件 41 项回归通过、零 warnings，独立评审确认无行为改变。
- 提交 `c06bca75` 的 Sonar quality gate 全部 5 项条件通过，unresolved、bugs、vulnerabilities、code smells、security hotspots、accepted、false positive 均为零，未忽略门禁条件。上次 `python:S5778` 问题已由分析自动关闭为 FIXED；参数构造移到异常断言外后，存储模块 34 项回归通过、零 warnings。对应 CE task 为 `AaD4UDf6ehJTyeFf0bEg`，analysis 为 `dc3d5b85-f5cd-428c-9c92-816dabd21500`。
- 该 Sonar 分析的 scanner `warningCount` 仍为 1：泛指源文件编码问题。对同一 `c06bca75` 的 904 个 Git blob 重新核验，885 个文本文件严格 UTF-8 解码通过，且无 NUL 或替换字符；其余 19 个文件由实际文件头识别为 PNG、JPEG 或 WOFF2。10 张历史截图的 `.png` 后缀此前已按实际 JPEG/JFIF 格式修正为 `.jpg`，哈希不变；修正后的扫描仍然报警，不能归因于这些图片。该次扫描运行配置本身已明确使用 UTF-8，重复声明相同编码没有修复依据。
- 后续独立核查了 Sonar 发布的全部文件组件：该 PR 的 19 个和 main 的 324 个组件均不包含上述 19 个二进制资产。依据下述官方已知问题，准备以精确路径将这些图片与字体排除出文本代码扫描；没有排除任何源码、测试、脚本、CI 文件或整个目录。根自动分析配置与项目服务设置保持同一份路径清单，旧项目设置为 UNSET 且已留存回退证据。此范围修正仍需下一次实际自动扫描及代码分析范围对比确认；若告警未消失，恢复原设置而不扩大排除范围。
- [Sonar 自动分析](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/automatic-analysis) 不提供详细扫描日志，不能导入覆盖率，也不能与 CI 分析同时启用。项目已有 Actions 测试和 Codecov，保留这套组合仍可满足当前日常开发检查。CI 迁移草案作为可选诊断方案保留，尚未应用；不要求为了本轮收尾新增 token 或关闭 Automatic Analysis。[官方支持说明](https://community.sonarsource.com/t/where-can-i-find-the-scanner-logs-in-the-sonarqube-cloud-ui/184606/7)也提供另一条路径：凭上述后台任务 ID 查询自动分析日志，确认触发告警的文件。官方记录过 PR 扫描计算变更信息时对二进制识别字符集产生告警的[类似情况](https://community.sonarsource.com/t/suspicious-multiple-warnings-about-encoding-on-binary-files/153706)，但尚无本项目具体文件证据，不能直接宣称误报已确诊或问题已解决。
- CodeRabbit 对 `c06bca75` 的实际复查没有产生可操作问题，5 项 pre-merge checks 通过，函数说明覆盖率为 86.63%，超过原有 80% 门槛。签名者和冻结池两项旧讨论均已解决，其中冻结池讨论由维护侧在源码、真实回归与新报告确认后关闭。已为本 PR 涉及的 Python 函数补充职责与不变量说明，纯说明文件通过剥离 docstring 后的 AST 对比确认无行为改变。后续提交仍须另行复查。
- 本机另已安装官方 CodeRabbit Windows CLI 0.8.2，两份可执行文件签名及安装自检通过，但 CLI 仍为 signed out，未运行本机审查或购买订阅。GitHub 报告注明本轮使用 Advanced 套餐内额度；未登录账单页面，不能推定是试用还是付费。[官方套餐说明](https://docs.coderabbit.ai/management/plans)提供长期 Free/OSS 接入，CLI 每人每小时 3 次，超限扩展另行收费。维护者只考虑免费接入，需本人登录并确认套餐及按量计费为 Off，超限时等待额度恢复；GitHub App 与 CLI 是独立接入。
- 已归档 mutation worktree，已跟踪文件中没有测试数据库、日志或缓存。部分缓存及测试临时目录清理被自动审批以“策略阻止”拒绝，相关文件保留；不能宣称所有临时文件均已清理。

最新代码需通过独立评审、本地针对性验证及其对应提交的远端 CI 后再合并。历史日志与临时探针保留在临时目录或 CI artifact，本记录不提交原始日志、数据库或凭据。
