# 历史验收与清理说明

2026-09-28 整理了已被后续实现与检查取代的候选验收、CodeFlow 四轮原始日志及 PR #10 合并前探针。完整历史仍可从 Git 的 `15751b3` 及之前提交读取；没有改写历史或修改扫描阈值。

## 保留的事实和决策

- 2026-09-12 的 CodeFlow 整改统一了异常分类、资源所有权和共享生成职责。第三轮“暂时保留告警”的建议已被第四轮实施取代，不应重新作为待办执行。当前生命周期和异常约束由源码、回归及各目录 AGENTS.md 维护。
- [PR #10](https://github.com/sunbos/sqlseed/pull/10) 的合并前审查复现了 SQLite JSON 编码、日期绑定、自引用定位和 AI MCP stdout 问题；修复及回归已进入基线。旧报告中的“尚未合并”“缺少依赖上界”和“main 无保护”等描述仅是当时快照，不是当前仓库状态。
- 原 mutation 的 8 个幸存变异已由后续验收处理；旧候选报告不能覆盖新提交的门禁结果。每轮报告应指明目标、环境及具体提交，不把一个模块的 mutation 结果扩大为全项目覆盖。
- Sonar 的逐项判定及用户暂缓 `fill` 参数重构的决定继续保留在 [Sonar 审计目录](2026-09-13-sonar-remediation/README.md)。
- GitHub Contributors 显示差异的工单已提交，但用户选择等待统计刷新，不公开发帖，也不为此改写合法提交。保留[原工单记录](github-support-record.md)作为上下文；此次整理不重新发送工单或声称问题已经解决。

## 清理范围

- 删除旧 `candidate-validation.md`，由当前项目收尾记录替代。
- 删除旧 `2026-09-12-codeflow-remediation/` 和 `2026-09-13-branch-merge-review/` 中一次性扫描 JSON、日志、调试探针、包清单及相互矛盾的阶段性建议；保留上述摘要与工单记录。
- 保留现行品牌资源、设计系统规范、业务测试夹具、迁移规则映射，以及仍被维护指引引用的历史设计材料。
- 未清理用户数据库、虚拟环境、未保存配置或仍在运行的验收目录。

## 2026-10-06 临时文件复核

本次以 `b7a5ba507cd8192779debf56d32502ba38e8e6af` 为基线复核已跟踪文件，未发现数据库、运行日志、缓存或构建临时产物。历史设计、评审账本、业务夹具、正式演示脚本和发行验收工具继续保留。

删除两个不再作为当前验收入口的历史复现脚本；原文仍可从上述提交的 `scripts/complex_validation/` 读取，不改写 Git 历史：

- `repro_defects.py`：用于确认修复前的 generator 名称和 nullable UNIQUE 缺陷，约定“两个缺陷均重现才返回成功”，不适合作为当前版本的通过条件。
- `repro_roundtrip.py`：五个一次性问题探针在模块导入时就建库执行，失败仅打印、不提供失败退出码。保留正式回归与可重复的专项 roundtrip 工具，避免把旧探针误当成产品门禁。

相关约束由以下现行回归和专项工具维护；这里列出用途映射，不代表本次执行了完整产品验收：

| 历史问题 | 现行维护位置 |
|---|---|
| `random_float` / `random_int` 是表达式函数，不是 core generator；修复目标必须存在 | [contract 回归](../../plugins/sqlseed-ai/tests/test_contracts_builtin.py) 的 `test_expression_functions_as_generator_names_are_caught`、[repair 回归](../../plugins/sqlseed-ai/tests/test_repair_strategies.py) 的 `test_coerce_float_to_int_rewrites_random_float_to_integer`；[离线专项验证](../../scripts/complex_validation/ai_offline_validation.py) 保留检测、修复到填充的检查 |
| nullable UNIQUE 不应全部写入 NULL，且生成值仍须符合类型与 CHECK 边界 | [编排回归](../../tests/test_orchestrator.py) 的 `test_fill_nullable_unique_column_not_all_null`、[UniqueAdjuster 回归](../../tests/test_core/test_unique_adjuster.py)、[schema 约束回归](../../tests/test_core/test_schema_constraint_regressions.py) |
| 整数 UNIQUE、枚举 CHECK 和 SQLite 行内约束的组合 | [schema 回归](../../tests/test_schema.py) 的 `TestInlineUniqueWithCheckDetection`、[随机 roundtrip 工具](../../scripts/complex_validation/randomized_roundtrip.py) 中的 `age`、`qty`、`score`、`year`、`role` 语料；专项工具不替代 pytest 门禁 |

同时为 `.db`、`.sqlite`、`.sqlite3` 补齐 `-wal`、`-shm`、`-journal` 的忽略规则，防止运行时 sidecar 被误提交；未增加会隐藏正式 YAML、SQL 或 JSON 夹具的笼统规则。
