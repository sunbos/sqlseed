# SQLite 订单生成、诊断与离线重放

这个示例用 sqlseed 的 public Python API 实际生成四张关联表，共 92 行。它适合检查字段规则、外键依赖、同一行派生、数据库约束，以及保存规则后的重复执行。所有业务记录都经过 `fill_from_config()` 生成和写入，脚本只负责建表与查询验收。

## 运行

在已安装当前 sqlseed 源码的 Python 环境中，从仓库根目录执行：

```bash
python examples/order_workflow/run.py --output-dir /tmp/sqlseed-order-demo
```

输出目录必须尚不存在。再次演示时换一个目录，脚本不会覆盖或清空已有目标。使用 Base 内置引擎，固定 seed 和日期，全程 `skip_ai=True`，不需要 Mimesis、AI 插件或模型服务。尚未安装 core 时，可先执行 `python -m pip install -e .`。

脚本先演示一次**预期失败**：商品价格规则设为负数，与数据库 CHECK 没有交集。终端会出现 `check_no_intersection` 错误日志，随后执行修正后的配置。最终退出码为 0，且输出“生成并验证 92 行，两个新库逻辑数据一致”才表示整个演示通过。

## 场景与约束

| 表 | 行数 | 关系与规则 |
|---|---:|---|
| `users` | 12 | 用户名、邮箱唯一，注册时间固定为 `2026-01-01 09:00:00` |
| `products` | 8 | SKU 唯一，价格以整数分保存并受 CHECK 限制，库存和启用状态使用数据库默认值 |
| `orders` | 24 | 引用用户，订单号唯一，状态为 pending / paid / shipped，付款与发货时间按状态派生 |
| `order_items` | 48 | 引用订单与商品，同一订单内商品唯一，数量 1–5，单价查找商品价格，下单时间查找订单时间 |

三条外键声明在 [schema.sql](schema.sql) 中，生成规则见 [rules.yaml](rules.yaml)。显式 `foreign_key` 规则同时指定 `ref_table`、`ref_column` 和 `strategy: coverage`。规则按依赖生成父表，再生成子表。本例还验证每个订单至少有一条明细。

同一行关系采用现有 `derive_from` / `expression`：已付款订单在创建后两小时付款，已发货订单在付款一天后发货。`unit_price_cents` 使用已有的 `lookup('products', 'price_cents', value)`。明细金额 `line_total_cents` 是 SQLite generated 列，由数据库计算 `quantity * unit_price_cents`，不配置生成器。

## 输出与验收

| 产物 | 用途 |
|---|---|
| `orders.db`、`rules.yaml` | 已生成的完整结果，以及绑定此数据库路径的修正规则 |
| `report.json` | 实际提交数、行数、CHECK / FK 检查、业务关系检查、坏规则诊断和两个新库的逻辑数据摘要 |
| `schema.sql` | 本次建表结构副本 |
| `replay.db`、`replay.yaml` | 已建表但未生成数据的目标，以及绑定它的规则，供首次 CLI / Web 重放 |
| `verification/bad.db`、`bad-rule.yaml` | 被拒绝的负价格规则和失败后数据库，报告记录生成前后行数 |
| `verification/second.db`、`second.yaml` | 同条件独立生成的第二份数据库与规则，用于复现检查 |

成功条件包括每表实际行数准确、`PRAGMA integrity_check` 为 `ok`、`foreign_key_check` 为空，以及单价、行金额、时间关系和订单明细覆盖检查全部通过。两份新库按主键排序后的**逻辑记录**必须相同，不比较 SQLite 文件字节。

坏规则真实触发 sqlseed 的 `ConfigurationError`，诊断指出 `price_cents` 的 `[-100, -1]` 与 CHECK 的 `[100, 100000]` 没有交集。这次失败发生在写入前，脚本读取并记录坏库四表行数均为 0。修正为 `500–5000` 后再生成。这个结论只描述本例，不代表所有运行错误都会回滚此前已提交的批次。

报告记录 provider、locale、每表 seed、固定日期范围、Python / SQLite / sqlseed 及 SQLAlchemy / Pydantic / PyYAML 版本、schema 与规则摘要。相同 seed 的复现要求相同软件环境、结构、规则和新的空数据库，不保证跨版本输出一致。

## 从保存规则重放

安装本地 CLI 插件后，执行脚本结尾打印的命令。以上输出目录对应：

```bash
sqlseed fill --config /tmp/sqlseed-order-demo/replay.yaml --no-ai
```

这会向保留的空 `replay.db` 写入同样的 92 行。也可以直接使用 public Python API：

```python
from sqlseed import fill_from_config

results = fill_from_config("/tmp/sqlseed-order-demo/replay.yaml", skip_ai=True)
for result in results:
    print(result.table_name, result.count, result.errors)
```

两种方式选择一种执行即可。同一份数据库重复追加可能遇到 UNIQUE 约束，需要再次运行示例建立新的输出目录。YAML 内含绑定的绝对路径，移动输出目录后应更新 `db_path`。

在 Web 中，可以连接 `orders.db` 查看完整结构、关系和已有数据。要测试生成流程，连接尚未使用的 `replay.db`，导入其 `replay.yaml`，保留四表规则，再检查并生成。CLI 和 Web 共用这一份重放目标，使用其中一种生成后，另一种应换一份新库。本示例的自动验收覆盖 Python API 和 CLI，Web 操作由使用者执行。

## 订单金额与 AI 的边界

订单合计通过查询明细获得，示例不承诺生成引擎维护跨表 SUM 字段：

```sql
SELECT o.order_no, COUNT(i.id) AS line_count,
       SUM(i.line_total_cents) AS total_cents
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.id
GROUP BY o.id
ORDER BY o.id;
```

本例不模拟库存扣减、退款、税费或完整跨表状态机，也没有运行 PostgreSQL。需要更广的压力场景时，继续使用 [scenario_lab](../scenario_lab/README.md)。

AI 可以作为可选的规则建议步骤：安装并配置 AI 插件后分析结构，审阅建议，检查并保存确认后的 YAML，再通过 `skip_ai=True` 或 `--no-ai` 离线执行。这里提供的规则是明确编写并验收的示例，报告中的 `ai_called` 为 `false`，不代表已执行或验证过真实模型分析。

## 开发验证

```bash
pytest tests/test_order_workflow.py -q
ruff check examples/order_workflow tests/test_order_workflow.py
ruff format --check examples/order_workflow tests/test_order_workflow.py
mypy examples/order_workflow/run.py
```

测试在临时 SQLite 中断言真实数据、约束拒绝、保存 YAML 的 API / CLI 重放，以及已有目录内容保持不变。未安装 CLI 插件时仅 CLI 用例跳过。
