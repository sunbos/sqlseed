# PR #10 SonarCloud 整改记录

基线为 `49caea3ee2785db51c1b2d2c8940ee4f0a19cd2a`。本记录覆盖当时全部 762 个未解决 issue key；[逐项账本](issue-ledger.csv) 标明原始位置、处理方式和依据。位置以基线为准，重构后行号会变化。

## 当前状态

- 基线 762 项中，730 项已通过源码或测试整改；31 项有[逐项误报复核依据](false-positive-review.md)，尚待服务端登记；1 项按用户要求暂缓。
- 首次复扫后另有 15 个新告警已整改，包括函数作用域、编辑器控件分工、异常类型和内部未使用参数；同时补全 1 个原有测试断言。两项哈希误报换了 key，映射见[复扫账本](followup-ledger.csv)。源码整改仍待下一轮云端确认。
- `fill` 参数数量告警 `AaCOzaRHkcuVuZeQceBV` 经用户明确要求留待后续共同评审，保留 OPEN，不登记 False Positive 或 Accepted。未使用源码抑制注释。
- Windows 的 deadline 相等边界已在 `01b1584152aa1fc9f1135ea6add6fb1ab8c303be` 修复，云端 Windows job `103605398190` 通过。
- `7fda56e5c8e1574e4b1919e9f430fcf4c9ed54ff` 的 [CI run 34716148288](https://github.com/sunbos/sqlseed/actions/runs/34716148288) 全部 9 个 job 通过，docs-sync 也通过。Python 3.12 的 Codecov 上传成功，之前的 `Repository not found` 已不再复现；保留 `fail_ci_if_error: true` 和 OIDC，未修改上传流程。
- 同一提交的 CodeFlow 三个分析器已完成，0 errors / 0 warnings；第二轮源码还须再次云端确认。

## 有效分析范围

Sonar API 已核对 PR #10 的全部 590 个文件：262 个测试文件均为 `UTS`，生产源文件为 `FIL`。测试识别正常。项目公开设置没有返回 Python 版本配置；默认分支 `main` 中没有 `.sonarcloud.properties`，候选分支中的文件不能作为已生效证明。

Sonar [Automatic analysis 文档](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis) 说明额外文件配置读取默认分支，也允许在项目设置中指定部分参数。后续需在已认证服务中核对并设置 Python 3.10–3.13，不通过移出源文件、排除告警文件或降低 Quality Gate 消除问题。

## 本地验证

- 第二轮全仓 pytest：3562 passed、47 skipped；启用了 ResourceWarning 与 PytestUnraisableExceptionWarning 作为错误，生成五包覆盖率报告。跳过项依赖不可用的 Docker、真实 LLM 服务或 API key。
- Web Node：669 passed，其中新增 3 项测试先复现异步重构的旧续体问题，再验证切连接、离页和编辑后不会绘制旧页面或重开旧 AI 弹窗。
- 独立 Chrome：真实 SQLite 上 30 个页面/弹窗与视口场景，CSS 合并前后计算样式零差异、零 JavaScript 错误；516 个代表元素在 7 种视口下仅有预期移除旧 word-break 属性的差异。
- Core 40816 组、FK 96 组、AI 跨列 540533 组、AI 编排 7656 组旧新实现差分无不一致；另有独立 review 的边界对照。
- root 脚本：500 个 seed schema、4681 个 CHECK 解析输入、真实 SQLite scenario 全量导出与日志输出旧新一致。
- Ruff、format、strict mypy（163 source files）、3 条 import contracts、doc-sync 通过。
- Pylint 2.17.7 全仓 0；ESLint 8.57.1 通过；jscpd 4.0.5 对源码报告 0 clones。
- 五包 sdist/wheel 构建、twine strict、完整/最小 wheel 安装、pip check、CLI/Web help、真实 HTTP 数据生成 smoke 和 MkDocs strict 通过。隔离环境运行，未修改项目虚拟环境或既有服务。
- Mutation 在隔离源码副本运行，`make mutmut` exit 0：246/246 killed，零幸存、超时、可疑或跳过。补充采样放大因子、有限字符串精确容量和用户可见错误/日志的回归；两个无状态私有 helper 改为模块函数，移除没有职责的静态方法包装。共享源码未被 mutation 改写。
- 第二轮增加真实 SQLite 的 ASCII token 边界和 FK 闭包测试，连同 UNIQUE 相关回归共 191 个用例通过；432 组新旧闭包差分一致，metadata 读取次数由 2224 降至 1182。Web 控件 216 组事件差分和完整编辑器 23 个状态差分一致；前端全部 669 个测试通过。

## 完成条件

本地整改不等于服务端全部清零。最终须核对推送后的确切 SHA：GitHub 全部必要检查、Codecov 上传、CodeFlow 三分析器，以及 Sonar Quality Gate 和剩余 issue。误报登记必须逐项带依据；例如禁用控件对比度按 [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) 的 inactive UI 豁免核对，固定 seed 的测试数据 PRNG 不改为密码学随机源。

## 首次云端复扫

提交 `7fda56e5c8e1574e4b1919e9f430fcf4c9ed54ff` 的 SonarCloud 分析已完成：未解决项从 762 降至 52，其中包含重构后出现的新告警。第二轮已整改其中 20 项，预计仍需登记 31 个误报并保留 1 项用户暂缓告警；具体剩余数须以下一次分析为准。CodeFlow 三个分析器均完成，0 errors / 0 warnings。SonarCloud 误报登记尚未执行，浏览器连接仍失败，当前无法使用已登录会话。
