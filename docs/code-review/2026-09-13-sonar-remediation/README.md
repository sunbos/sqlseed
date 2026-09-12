# PR #10 SonarCloud 整改记录

基线为 `49caea3ee2785db51c1b2d2c8940ee4f0a19cd2a`。本记录覆盖当时全部 762 个未解决 issue key；[逐项账本](issue-ledger.csv) 标明原始位置、处理方式和依据。位置以基线为准，重构后行号会变化。

## 当前状态

- 726 项已通过源码或测试整改，等待云端复扫确认。
- 36 项经源码核查列为误报候选，等待独立复核和 SonarCloud 中逐项登记；未使用源码抑制注释。
- Windows 的 deadline 相等边界已在 `01b1584152aa1fc9f1135ea6add6fb1ab8c303be` 修复，云端 Windows job `103605398190` 通过。
- 同一提交的 Python 3.12 job `103605398231` 仍在 Codecov 上传步骤收到 `Repository not found`，需要修复服务端仓库接入；保留 `fail_ci_if_error: true` 和 OIDC。
- 同一提交的 CodeFlow 三个分析器已完成，0 errors / 0 warnings；整合后的源码还须再次云端确认。

## 有效分析范围

Sonar API 已核对 PR #10 的全部 590 个文件：262 个测试文件均为 `UTS`，生产源文件为 `FIL`。测试识别正常。项目公开设置没有返回 Python 版本配置；默认分支 `main` 中没有 `.sonarcloud.properties`，候选分支中的文件不能作为已生效证明。

Sonar [Automatic analysis 文档](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis) 说明额外文件配置读取默认分支，也允许在项目设置中指定部分参数。后续需在已认证服务中核对并设置 Python 3.10–3.13，不通过移出源文件、排除告警文件或降低 Quality Gate 消除问题。

## 本地验证

- 全仓 pytest：3504 passed、47 skipped；启用了 ResourceWarning 与 PytestUnraisableExceptionWarning 作为错误，生成五包覆盖率报告。跳过项依赖不可用的 Docker、真实 LLM 服务或 API key。
- Web Node：669 passed，其中新增 3 项测试先复现异步重构的旧续体问题，再验证切连接、离页和编辑后不会绘制旧页面或重开旧 AI 弹窗。
- 独立 Chrome：真实 SQLite 上 30 个页面/弹窗与视口场景，CSS 合并前后计算样式零差异、零 JavaScript 错误；516 个代表元素在 7 种视口下仅有预期移除旧 word-break 属性的差异。
- Core 40816 组、FK 96 组、AI 跨列 540533 组、AI 编排 7656 组旧新实现差分无不一致；另有独立 review 的边界对照。
- root 脚本：500 个 seed schema、4681 个 CHECK 解析输入、真实 SQLite scenario 全量导出与日志输出旧新一致。
- Ruff、format、strict mypy（163 source files）、3 条 import contracts、doc-sync 通过。
- Pylint 2.17.7 全仓 0；ESLint 8.57.1 通过；jscpd 4.0.5 对源码报告 0 clones。
- 五包 sdist/wheel 构建、twine strict、完整/最小 wheel 安装、pip check、CLI/Web help、真实 HTTP 数据生成 smoke 和 MkDocs strict 通过。隔离环境运行，未修改项目虚拟环境或既有服务。
- Mutation 在隔离源码副本运行，尚待最终结果。已补充采样放大因子及有限字符串精确容量的 3 个边界 case，原有两个幸存变异先 RED，再以正式源码 GREEN。

## 完成条件

本地整改不等于服务端全部清零。最终须核对推送后的确切 SHA：GitHub 全部必要检查、Codecov 上传、CodeFlow 三分析器，以及 Sonar Quality Gate 和剩余 issue。误报登记必须逐项带依据；例如禁用控件对比度按 [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) 的 inactive UI 豁免核对，固定 seed 的测试数据 PRNG 不改为密码学随机源。
