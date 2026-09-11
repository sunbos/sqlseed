# 订单演示实施计划

**目标：** 用现有 public Python API 实际生成四表订单数据，保存规则、失败诊断和可重复验收证据。

**结构：** schema.sql 只定义 SQLite DDL；rules.yaml 只定义现有配置语法；run.py 调用 fill_from_config() 并用只读 SQL 验证真实结果；README.md 说明使用与能力边界。

**验证环境：** Python、SQLite、sqlseed Base provider；不调用模型。仅创建新的输出目录。

- [x] 先写 tests/test_order_workflow.py：验证四表实际行数、外键与 CHECK、同条件两个新库数据相同、坏规则真实失败、保存 YAML 可重放、已有目录内容不变。
- [x] 运行 pytest tests/test_order_workflow.py -q，记录入口尚未实现的 RED：5 failed。
- [x] 实现四表结构与固定 seed/日期规则；明细单价从商品查找，行金额由 SQLite generated 列计算，订单合计只通过查询展示。
- [x] 实现 python examples/order_workflow/run.py --output-dir <新目录>，先执行不可满足的负价格规则；修正配置写入两份空库并比较逻辑数据，另保留一份空库供用户重放。
- [x] 运行上述 pytest、Ruff 与独立脚本；在 report.json 记录实际结果和版本、规则、schema 的复现条件。最终测试包含 CLI 重放，共 6 passed；Ruff check / format 与示例 mypy 通过。
- [x] 编写中文 README，明确 SQLite 验收范围、同 seed 不等于向已有库重复追加安全、未实现跨表 SUM 生成与未调用 AI。

本任务不提交，也不更改其他示例或核心实现。
