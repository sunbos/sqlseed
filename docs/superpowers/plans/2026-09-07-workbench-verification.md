# 前次工作台接入功能验证记录

> **历史功能证据，不是 v8 视觉验收。** 下列结果属于前次增量接入。用户已要求按 v8 整体重建 shell 与 presentation，当前状态以 [重建契约](2026-09-07-web-v8-rebuild.md) 为准。不能把本记录中的测试数量或“已实现”清单用于宣称重建完成。

核验日期：2026-09-07。范围为用户确认的非 AI 工作台流程；保留原有未提交改动，没有提交或推送仓库。

## 已实现

- 正式导航连接工作台和运行记录；真实 schema、成组 FK、完整依赖路径与字段搜索替代演示结构。
- 表名打开字段规则，图标打开关系图，勾选只控制生成范围。库级结构工具、配置级操作和表级数量分别放在对应位置。
- 真实 generator catalog、参数与约束编辑、派生表达式、外键来源、整表预览。未选表可以单独预览，不影响生成计划。
- 完整 core 配置往返，服务端版本化保存及重新打开；未选表的规则、无效输入的会话草稿分别保留。
- 确定性检查，保存版本、结构 hash 和来源再核验，服务端父先子后执行，失败停止后续表。
- 固定运行快照、逐表结果、重启中断状态和部分提交数量。修复核心后续批失败时丢失先前成功批次数量的问题。
- 旧请求不能覆盖新文档；离页清理轮询和弹窗；相同 epoch 的不同文档、并发预览及重复弹窗均有回归。

## 自动验证

| 检查 | 结果 |
|---|---|
| `pytest plugins/sqlseed-web/tests/ tests/test_core/test_generation_partial.py tests/test_architecture.py tests/test_doc_sync.py -q` | 166 passed |
| `node --test plugins/sqlseed-web/tests/test_*.cjs` | 123 passed |
| 原型 `sqlseed-workbench/*.test.cjs` | 103 passed |
| `ruff check` 与 `ruff format --check`：Web 包及本次核心计数改动 | 通过 |
| `mypy plugins/sqlseed-web/src/ src/sqlseed/core/orchestrator/_generation.py` | 10 source files，通过 |
| `lint-imports` | 3 contracts kept |
| `git diff --check` | 通过 |
| `uv build --wheel` | 成功；新后端与静态资源均包含在 wheel 中 |
| 实际 FastAPI 路由和静态依赖检查 | HTML shell、CSS、21 个 JavaScript 资源及所有相对 import 可用；no-cache 保留 |

Python 命令通过仓库 `.venv/bin/python` 执行。测试使用独立 workspace 文件和临时 SQLite，不写用户数据库。

HTTP 验收覆盖：连接 → 修改列参数和数量 → 保存 → 重开 → 检查与预览且库行数不变 → 真实父子表生成 → 查询持久结果与实际 JOIN。另验证旧版本、结构变化、来源变化、部分批次失败、真实 self-reference、associations、自定义 exact/pattern mapping 和显式列优先级。

## 保留的验证边界

- 浏览器工具仍拒绝访问本地原型，按用户要求停止排查；没有使用其他地址或工具绕过。DOM 测试与静态资源检查不能代替真实视觉、键盘和响应式验收。
- 本次真实数据库验收使用 SQLite；未运行真实 PostgreSQL 环境验收。
- AI 分析/修复、通用跨表循环、清空计划、Python transform、snapshot_dir、不同的每列 provider、三列以上组合 FK 和组合自引用等未支持执行路径会明确报错；配置仍可保存/导出。取消和断点续跑未接入。
- 完整文档的 `mkdocs build --strict` 因当前仓库 5 条已有告警未通过，新工作台指南没有告警：原型 README/index 输出冲突 1 条，`v4_spec_compliance_report.md` 的旧相对链接 3 条，旧 migration spec 指向站点外 `user_profile.md` 1 条。未顺带修改这些历史文档。

使用方法见 [Web 工作台指南](../../web-workbench.md)。
