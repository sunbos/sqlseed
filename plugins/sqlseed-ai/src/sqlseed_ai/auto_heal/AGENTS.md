# auto_heal：顶层修复与 CHECK 推断

继承 [AI 运行时规则](../AGENTS.md)。[orchestrator.py](orchestrator.py) 同时承载流水线和确定性 CHECK 推断；其 `Pattern N` / `Round N` 注释是回归定位词，修改前先搜索编号及相邻分支，不能当作历史临时代码删除。

## 流水线不可变条件

- `AutoHealOrchestrator.run()` 捕获 `SchemaSnapshot`，拆分 FK subgraph，在各子图运行 validate → repair → heal，最后处理 broken edges 并输出 YAML。
- `run(initial_config=...)` 以输入文件的表和规则开始修复，保留 root/table 设置及未被 violation 或 repair/heal 触及的显式列规则；不能用 schema 默认配置替换输入。`tables` / `include_dependencies` / `max_depth` 控制分析范围，未知表名在输出前拒绝。默认不传参数时仍走全库分析。
- 启动时记录 `schema_hash`，输出前重新捕获并比较；schema 变化必须报错，不能继续交付基于旧 schema 的配置。
- [time_budget.py](time_budget.py) 的 `TimeBudgetController` 控制 wall-clock 预算；保留进度 / trace 和已有超时处理，不绕过预算直接加重试。
- `_build_subgraph_config()` 在 LLM 前先推断可确定的 CHECK、UNIQUE、FK 特例；普通列通过 Core `ColumnMapper` 做名称语义映射，别复制另一套姓名、地址等匹配规则。
- 初始配置与 Step 5.5 的后处理需要一致：LLM 可能改坏或删除初始 `params` / `derive_from`，最终修复必须能恢复确定性信息。

## CHECK 推断优先级

- 在 FK 特例之后，跨列 CHECK 先于单列 CHECK；单列 CHECK 先于普通 UNIQUE / 名称映射 fallback。不要用独立随机范围覆盖已有跨列关系。
- 单列 enum / boolean CHECK 决定值域；例如 `title IN (...)` 不能落入 `title → sentence` 的名称规则。Core 的单列 enum hard truth 也要保持，不通过 AI 配置绕过它。
- `_infer_from_check_constraints()` 合并所有单列数值 / 长度边界：下限取 MAX、上限取 MIN，必要时 integer → float；不要命中第一个范围就返回。
- `_normalize_constraints()` 负责 PostgreSQL casts 与外层括号规范化，新增模式要验证规范化后的 SQL，也要覆盖原始 SQLite 表达式。
- 条件 OR 约束优先于范围 AND；OR 中含 `IN (...)` 的约束优先于普通 `IS NULL OR`。保留多 CHECK 的 pre-loop scans，否则单个分支可能提前吞掉组合条件。
- 修改 Pattern 1 / 1b / 19 等关系规则时检查负数、上下界、列顺序、NULL 与依赖环；日期规则同时检查 DATE 与 DATETIME，不能只依赖 `_time` / `_date` 名称后缀。

## 已验证的边界行为

- **精确长度 phone**：普通电话类列的 `LENGTH(col)=N` 使用 `pattern` / `[0-9]{N}`，与 Layer 3 phone 修复保持一致，避免 `string ↔ phone` 振荡；初始配置中的 UNIQUE 分支优先，见下一条。
- **UNIQUE + 精确长度**：普通字符串列用 `[A-Za-z0-9]{N}` pattern，不能让 UniqueAdjuster 扩大 `max_length` 破坏 CHECK；仍需考虑有限值域的 cardinality。
- **LIKE 格式列**：`_like_to_regex()` 按字符保留 literal 位置并生成 anchored regex。列或来源列有 LIKE CHECK 时，不推断数值 / `timedelta` 算术；`HH:MM` 文本不是 datetime 对象。
- FK 推断需传入 FK / self-reference 列集合；条件 NULL 的 FK 分支不能写 `0` 代替 `None`。保留 self-reference 与 circular FK 的现有 NULL 特例，并连同相关 CHECK 验证。
- 跨列关系被 LLM 覆盖后，Step 5.5 重新应用 `_infer_cross_column_config()`；LIKE 防护则剥离不合法算术，并恢复能保证格式的 `pattern`。
- `derive_from` 经安全检查保留后，移除并存的 `generator` / `params`，确保 `ColumnConfig` source / derived 两种模式互斥。
- 保留模板文本误放 `generator`、`?` / 非法生成器、缺失 generator、被剥 CHECK 参数的纠正逻辑；参数清理继续复用 Layer 3 的白名单函数。
- 最终配置的语义降级不能丢掉 CHECK、UNIQUE 或 FK 约束。修改会影响 Core fill 行为时，先读 [Core 规则](../../../../../src/sqlseed/core/AGENTS.md)，不要把复杂 OR 推断搬入 Core 的 deterministic-only `check_adapt.py`。

## 验证

从仓库根运行，测试位置与真实 LLM 规则见 [AI tests](../../../tests/AGENTS.md)：

```bash
pytest plugins/sqlseed-ai/tests/test_auto_heal_orchestrator.py plugins/sqlseed-ai/tests/test_auto_heal_time_budget.py
pytest plugins/sqlseed-ai/tests/test_repair_executor.py plugins/sqlseed-ai/tests/test_repair_strategies.py
pytest plugins/sqlseed-ai/tests/test_healer_degrader.py plugins/sqlseed-ai/tests/test_healer_post_repair.py
```

新增 CHECK 分支至少验证输出 generator / params / expression；涉及 fill 正确性时用 `tmp_path` 上的真实 SQLite DDL 和实际生成结果覆盖，不能只断言 mock 被调用。重用现有 Pattern 回归案例检查相邻分支的优先级。
