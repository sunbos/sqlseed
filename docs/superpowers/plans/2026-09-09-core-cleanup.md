# 核心正确性清理与 Web 恢复 Implementation Plan

> **For agentic workers:** 按 systematic-debugging / test-driven-development 执行；独立目录并行，跨目录接口先协调。

**Goal:** 修复三表追加和 AI 实测暴露的问题，并对 `src/` 做有证据的正确性审计。

**Architecture:** 保持 offline core、adapter/provider 分层、流式生成以及 Web 显式确认写入。清理以可复现缺陷为单位，不替换引擎或重写公共 API。当前未提交成果作为基线保留。

**Tech Stack:** Python、SQLAlchemy、pytest、原生 JavaScript、Node test、浏览器验收。

## 基线与范围

- [x] 当前源码及 diff 已备份到 `/var/folders/cl/xphppvtj3qx0n89rkx8tzyd80000gn/T/sqlseed-cleanup-baseline-otkpmk4c`。
- [x] 保存 pytest / Node / ruff / mypy / import-linter 基线结果。
- [x] 约束与 stream：真实 SQLite 复现已有组合键冲突；避免全表数据预加载；检查约束登记回滚。
- [x] adapter 与编排：检查事务、PRAGMA、cursor/连接释放、自引用阶段与提交数量。
- [x] provider / config / plugins / utils：检查可选依赖、参数验证、种子与生命周期；保留合法配置兼容。
- [x] AI：DEFAULT 是否保护取决于实际取值规则；数据库分配/跳过、PK/FK/计算列、已有派生/原生规则继续保护。提示只发送结构与业务说明。
- [x] 引导：应用 AI 建议后以当前 model/epoch 显示预览下一步，不宣称业务已验证。
- [x] 恢复：失败记录提供剩余配置入口，只有计数完整且精确的追加失败可自动计算剩余行数。保留原快照；提交不确定或清空策略需人工核对，不自动重试。

## 验证顺序

1. 每个缺陷增加真实计算或数据库回归，先记录 red，再最小修改到 green。
2. 合并各目录结果后跑 core、Web Python、Node、类型、静态和架构/文档同步检查。
3. 独立临时数据库通过 Web 复验三表追加、剩余配置、AI DEFAULT 与应用后引导；不修改原演示库。
4. 汇总新改动相对本轮备份的清单、测试结果、已知能力边界和未覆盖环境。代码保持未提交供评审。

## 验收结果

- Python 全量 2709 passed / 33 skipped；Node 全量最终 472 passed。
- ruff、format、mypy、import-linter、doc-sync 通过；architecture/doc-sync 专项 31 passed。
- Web 实测剩余 order_items 100 行补齐成功，随后 users → orders → order_items 各追加 100 行成功；原演示库 SHA-256 不变。
- AI DEFAULT 实测能选择 balance、请求和应用规则；预览页应用后的引导覆盖问题已用真实交互复现、修复并重验。
- mutation 在独立源码副本运行；最终结果与环境限制以 [验收报告](../../design-review/2026-09-09-core-cleanup/README.md) 为准，不把尚未完成的 mutation 审阅记为通过。
