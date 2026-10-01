# 2026 年 10 月 1 日质量核验

本记录核验 [PR #26](https://github.com/sunbos/sqlseed/pull/26) 的生成行为和质量检查。该 PR 尚未合并；完整收口仍需最新提交的远端扫描和外部服务配置。本文保留具体提交与实测边界，不能由通过的门禁推定所有工具均为零警告。

## 数据库生成范围

SQLite 追加模式支持已有有效父键的单列物理外键循环。检查、预览与执行使用写入前冻结的父键池；实际追加将所有所选表置于同一事务，任一写入失败回滚本次全部新增记录，原有记录保留。普通非循环追加仍按原有批次提交。

隔离的 26 表业务数据库使用 Base 引擎，每表追加 100 行，新增 2,600 行，原有 28 行保留，总行数为 2,628，外键检查为零。浏览器另以每表 3 行验收：新增 78 行，原有 28 行保留，控制台没有 errors 或 warnings。这两组数据只证明对应夹具，不代表任意 schema 均受支持。

新增回归确认普通子表能引用同次追加的新父键，显式配置关联继续生效，而循环边始终引用已冻结的旧父键。策略放在外键解析环节，继承原有规格解析参数，不修改 Core public API。

从空表生成的跨表循环、组合或重叠外键或配置关联构成的循环、PostgreSQL 循环追加及循环清空重建仍明确阻止。不能用调整生成行数、NULL 比例或重置自增计数解除这些限制；没有引入通用 backfill 或关闭数据库约束。

## 真实模型验收

使用本机已有的 LM Studio 与 `google/gemma-4-e2b`，在隔离数据库上执行真实 AI、CLI、MCP 和 healer 集成测试，启用 `--require-llm`，不将服务缺失或模型错误改成跳过。

首次完整运行 16 项：15 项通过、1 项失败、零 warnings。失败发生在 CLI 直接建议模式：本地模型返回无效 JSON，CLI 保留失败状态且没有写出配置。严格本地调用当时仅以提示词要求 JSON，未请求采样格式约束。

修复后严格 LM Studio 调用使用 JSON Schema 对象采样，Ollama 使用 JSON 对象模式；流式与非流式保持一致。只在服务明确不支持该格式时回退一次，认证、无关 400 与服务器错误继续失败。生成参数、提示预算、标识符保护和严格业务解析保留。完整严格复验结果为 **16 passed、79 deselected、零 warnings**，耗时 661.51 秒；原失败 CLI 用例包含在该套复验中。MCP 验收包括真实模型请求和隔离 SQLite 写入，不由模拟响应推定。

本轮本地 Ruff 检查与格式核验通过（492 个文件），mypy strict 通过（175 个源文件），三项 import-linter 合约与 `pip check` 通过。Web 前端回归 1,022 passed、零 failed 或 skipped；冻结来源与普通外键行为回归 69 passed、零 warnings。独立评审未发现新的可行动问题，另实跑 AI 协议回归 82 passed、零 warnings。

## 已有远端检查

[CI 36856644464](https://github.com/sunbos/sqlseed/actions/runs/36856644464) 对应提交 `8a024830c1926230c7b6c3c4b25a3b396b671d3d`，包含最终外键解析策略重构、本地 JSON 格式修复和测试辅助逻辑去重：

| 环境 | 结果 |
| --- | --- |
| Linux Python 3.10、3.12、3.13 | 各 4,292 passed、47 skipped |
| Windows Python 3.12 | 4,246 passed、93 skipped |
| macOS Python 3.12 | 4,233 passed、106 skipped |
| PostgreSQL integration / property tests / doc-sync | 56 / 3 / 18 passed，零 skipped |
| 其他 CI 门禁 | lint、packages 全部通过；Node 1,022 passed，零 failed |

上述 pytest 日志没有 warnings；两份 Codecov 上传均通过 GPG 与 SHA256 校验、上传明确对应此提交并清理隔离 keyring。Codecov patch 门禁通过，覆盖率为 96.24%，目标为 89.16%。project check 没有发布，历史提交也仅发布 patch，不能虚构其成功状态。macOS runner 容量提示是 notice，Actions 没有 warning 或 error annotations。PR 上跳过文档部署属于既有规则，strict MkDocs 构建仍执行。

针对 Codecov 评论列出的 8 行新增未覆盖代码，已补真实 SQLite 回归，验证配置关联成环阻止清空重建、范围内外依赖边界、检查及预览不改变原有记录和自增序列，以及非法事务标记不落盘、运行快照重启后保持且不能篡改。两份完整测试文件共 50 passed、零 warnings，定向覆盖报告确认命中其中 5 行。PostgreSQL 拒绝分支新增真实服务测试并纳入专用 CI job，须等待远端实测；另外两行仅在违反已固定的构造契约时抛出防御异常，不通过破坏契约的 mock 凑覆盖率。

PostgreSQL 容器原始日志另有一条初始化警告：本地连接默认使用 `trust` 认证。测试服务已增加显式 SCRAM 密码认证参数；其容器启动、原有 56 项 PostgreSQL 回归、新增工作台边界测试及警告消失仍需下一提交的 CI 实证。没有过滤日志或降低测试要求。

本轮 `sync_docs.py --check` 与 strict MkDocs 构建通过，没有项目构建 warning。Material 主题仍直接输出一条关于未来 MkDocs 2.0 的[上游迁移提示](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)；它不经过 MkDocs 的警告计数，不能据此宣称原始输出完全没有警告字样。已安装与 CI 的 MkDocs 为 1.6.1，Material 依赖明确要求 `mkdocs<2`。根 `uv.lock` 已将主题对齐已验收的 9.7.7，其他依赖版本不变，三个已有锁文件均校验通过。不为消除该提示屏蔽输出或降低版本。

本地 mutation gate 的 246 个 mutant 全部被杀死，survived、suspicious、timeout、skipped、untested 均为零；目标源码与两份测试哈希与本轮工作树一致。该定向门禁不能代替完整产品测试。

## 外部扫描与待完成事项

- [提交 `8a024830` 的 CodeFlow 扫描](https://app.getcodeflow.com/github/sunbos/sqlseed/commits/8a024830c1926230c7b6c3c4b25a3b396b671d3d) 状态为 “Good job! No issues.”，结果页面没有问题条目。已删除 Web 的整段规格解析覆写，并共享测试中的 HTTP 格式拒绝处理，保留全部参数化范围与断言；协议回归 82 项全部通过、零 warnings。此结论仅对应明确提交，后续提交仍须重新核验。
- 提交 `8a024830` 的 Sonar quality gate 通过，全部 5 项条件通过，open 或 confirmed issues、bugs、vulnerabilities、code smells、security hotspots 均为零，accepted 或 false positive 为零，未忽略门禁条件。对应 CE task 为 `AaD3Qx3nCH08y69O06mt`，analysis 为 `51cf2633-8e07-4bd5-b659-66e8f2d49c91`。scanner `warningCount` 仍为 1：泛指源文件编码问题。884 个已跟踪文本文件严格 UTF-8 解码通过，19 个二进制文件均验证为正常资产。发现其中 10 张历史截图实际为 JPEG/JFIF，已将后缀从 `.png` 改为 `.jpg`，逐张哈希不变且没有旧路径引用。没有证据证明这就是 Sonar 警告来源，需后续扫描确认；不凭推断转码或排除正常资产。
- [Sonar 自动分析](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/automatic-analysis) 不提供详细扫描日志且不能与 CI 分析同时启用。CI 迁移草案已准备：固定官方扫描工具、保持扫描范围、复用真实覆盖率并保存任务与门禁证据。启用仍需仓库 `SONAR_TOKEN` 和关闭 Automatic Analysis；本机登录凭据不自动转交 GitHub。迁移不保证编码提醒自动消失。
- CodeRabbit 仓库配置已准备，尚未验证 GitHub App 对本仓库的授权与实际审查。另已安装官方 Windows CLI 0.8.2，`coderabbit.exe` 与 `cr.exe` 的 Authenticode 签名有效，安装自检通过；账户状态为 signed out，尚未运行审查或购买订阅。[官方套餐说明](https://docs.coderabbit.ai/management/plans)提供长期 Free/OSS 接入，CLI 每人每小时 3 次，超限扩展另行收费。维护者只考虑免费接入；实跑前需本人登录并确认套餐及按量计费为 Off，超限时等待额度恢复。PR App 与 CLI 是独立接入，配置文件或安装成功均不代表审查已经执行，也不作为现有项目门禁通过的依据。
- 已归档 mutation worktree，已跟踪文件中没有测试数据库、日志或缓存。部分缓存及测试临时目录清理被自动审批以“策略阻止”拒绝，相关文件保留；不能宣称所有临时文件均已清理。

最新代码需通过独立评审、本地针对性验证及其对应提交的远端 CI 后再合并。历史日志与临时探针保留在临时目录或 CI artifact，本记录不提交原始日志、数据库或凭据。
