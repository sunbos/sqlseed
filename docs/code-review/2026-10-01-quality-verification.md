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

[CI 36838107405](https://github.com/sunbos/sqlseed/actions/runs/36838107405) 对应提交 `59d7ff02b5dfb11cb615ff11c70d1adb0fa91cdb`，在最终外键解析策略重构与本地 JSON 格式修复之前完成：

| 环境 | 结果 |
| --- | --- |
| Linux Python 3.10、3.12、3.13 | 各 4,266 passed、47 skipped |
| Windows Python 3.12 | 4,220 passed、93 skipped |
| macOS Python 3.12 | 4,207 passed、106 skipped |
| 其他 CI 门禁 | lint、packages、PostgreSQL integration、property tests 全部通过 |

上述 pytest 日志没有 warnings；两份 Codecov 上传均通过 GPG 与 SHA256 校验、完成上传并清理隔离 keyring，上传 warnings 为零。macOS runner 容量提示是 notice。PR 上跳过文档部署属于既有规则，strict MkDocs 构建仍执行。

本轮 `sync_docs.py --check` 与 strict MkDocs 构建通过，没有项目构建 warning。Material 主题仍直接输出一条关于未来 MkDocs 2.0 的[上游迁移提示](https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/)；它不经过 MkDocs 的警告计数，不能据此宣称原始输出完全没有警告字样。已安装与 CI 的 MkDocs 为 1.6.1，Material 依赖明确要求 `mkdocs<2`。根 `uv.lock` 已将主题对齐已验收的 9.7.7，其他依赖版本不变，三个已有锁文件均校验通过。不为消除该提示屏蔽输出或降低版本。

本地 mutation gate 的 246 个 mutant 全部被杀死，survived、suspicious、timeout、skipped、untested 均为零；目标源码与两份测试哈希与本轮工作树一致。该定向门禁不能代替完整产品测试。

## 外部扫描与待完成事项

- 提交 `59d7ff0` 的 CodeFlow 原始结果为 0 errors、2 warnings，指向 Core 与 Web 的方法参数声明重复。外键解析策略重构已删除 Web 的整段规格解析覆写；仍须核对新提交的实际扫描结果，不能提前宣布零 warnings。
- 同一提交的 Sonar quality gate 通过，open 或 confirmed issues、bugs、vulnerabilities、code smells、security hotspots 均为零，accepted 或 ignored 为零。但 scanner `warningCount` 为 1：泛指源文件编码问题。883 个已跟踪文本文件严格 UTF-8 解码通过，没有定位到问题文件；不能凭推断转码或排除正常资产。
- [Sonar 自动分析](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/automatic-analysis) 不提供详细扫描日志且不能与 CI 分析同时启用。CI 迁移草案已准备：固定官方扫描工具、保持扫描范围、复用真实覆盖率并保存任务与门禁证据。启用仍需仓库 `SONAR_TOKEN` 和关闭 Automatic Analysis；本机登录凭据不自动转交 GitHub。迁移不保证编码提醒自动消失。
- CodeRabbit 仓库配置已准备，尚未验证 GitHub App 对本仓库的授权与实际审查；配置文件本身不代表服务已经生效。
- 已归档 mutation worktree，已跟踪文件中没有测试数据库、日志或缓存。部分缓存及测试临时目录清理被自动审批以“策略阻止”拒绝，相关文件保留；不能宣称所有临时文件均已清理。

最新代码需通过独立评审、本地针对性验证及其对应提交的远端 CI 后再合并。历史日志与临时探针保留在临时目录或 CI artifact，本记录不提交原始日志、数据库或凭据。
