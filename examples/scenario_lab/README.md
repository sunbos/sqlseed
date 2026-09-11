# 订单履约业务夹具

这是一套可重复构建的 SQLite 测试场景，用于验证复杂结构浏览、字段规则、依赖检查、预览和生成边界。它包含 **24 张表、38 组物理外键、121 条合法种子**：6 组单列、25 组双列、7 组三列外键。所有数据都是固定的虚构记录，邮件使用 `.example.test` 域名。

夹具完整表达多租户订单、采购入库、发货和售后关系；`baseline.yaml` 仅配置已经实测可以安全追加的六张表。结构复杂度与自动生成支持范围分别记录，不能把“可以读取结构”理解成“可以自动生成全部业务数据”。

## 快速使用

从仓库根目录执行，需要安装本地 core；Web 探测还需要安装 `plugins/sqlseed-web`。以下命令使用仓库的 `.venv`。

```bash
# 新建独立桌面数据库。目标已存在时使用 _2、_3 等新名称。
.venv/bin/python examples/scenario_lab/build.py --next-available

# 或明确指定一个尚不存在的路径；绝不覆盖已有文件。
.venv/bin/python examples/scenario_lab/build.py --output /tmp/my_scenario_lab.db

# 只读核验，不生成数据。
.venv/bin/python examples/scenario_lab/validate.py ~/Desktop/sqlseed_scenario_lab.db

# 自动重建临时夹具，在临时副本上真实执行 core，并检查正式 Web 结构与预览。
.venv/bin/python examples/scenario_lab/verify.py --web

# 对指定库制作一致性副本后验证；原文件只读打开，生成仍仅发生在临时副本。
.venv/bin/python examples/scenario_lab/verify.py --web --source ~/Desktop/sqlseed_scenario_lab.db

# 专属回归；它不在根 pytest 的默认 testpaths 内。
.venv/bin/pytest examples/scenario_lab/test_fixture.py -q
```

默认目标为 `~/Desktop/sqlseed_scenario_lab.db`；构建器先在同目录临时文件中完成建表、种子和验证，成功后以不会覆盖已有目标的方式发布。不会连接或修改 `sqlseed_demo.db`。

在 Web 中添加这个独立数据库连接，打开配置文档并导入 `baseline.yaml`，即可检查并预览六张表。该 YAML 不绑定机器路径：Web 使用当前连接，`verify.py` 为 core 的 `fill_from_config()` 注入临时目标路径。直接把未绑定的 YAML 交给 core loader 会提示缺少 `db_path/url`；不要为解决该提示而随意指向原业务库。

## 场景与表归属

| 范围 | 表 | 关系和测试点 |
| --- | --- | --- |
| 租户与人员 | `tenants`, `warehouses`, `employees` | 两个租户；员工经理自引用；租户内仓库编号唯一 |
| 客户 | `customers`, `addresses` | 租户隔离；客户全局唯一邮箱；同一客户有两份地址 |
| 商品采购 | `suppliers`, `products`, `supplier_products` | 同租户供应商/商品；联合主键；成本不能高于售价 |
| 库存 | `inventory`, `stock_movements` | 仓库/商品三列归属；可用量 generated；采购、销售、退货流水 |
| 订单支付 | `orders`, `order_items`, `payments` | 33 列订单宽表；地址必须属于同租户同客户；行金额和总额 generated |
| 发货 | `shipments`, `shipment_events`, `shipment_items` | 发货单与当前事件的可空循环；发货明细必须属于同一订单 |
| 采购单 | `purchase_orders`, `purchase_order_items` | 日期顺序、实收数量和成本金额约束 |
| 售后 | `returns`, `return_items`, `refunds` | 原订单明细归属、退货数量和退款对账 |
| 标签与日志 | `tags`, `product_tags`, `audit_events` | 2 列标签窄表；多对多关系；无 FK 的客户邮箱业务关联 |

每个租户的固定业务链为：采购三种商品各 20 件 → 销售商品一 2 件、商品二 1 件 → 商品一退回 1 件。中心仓结存分别为 19、19、20；备用仓每种商品由调整流水入库 5 件。订单明细合计 3400 分，订单折扣 200 分、运费 100 分、税费 300 分，总额和付款均为 3600 分；售后退款 900 分。

`orders` 与其客户、地址、员工、商品、支付、采购、库存及售后都能沿结构图追溯。`audit_events.customer_email` 没有数据库 FK，baseline 的 `associations/shared_pool` 显式说明它从 `customers.email` 取值，适合验证业务关联与物理外键的区别。

## 哪些约束由谁保证

| 规则 | 保证位置 |
| --- | --- |
| PK、NOT NULL、单列/联合 UNIQUE、租户/归属 FK | `schema.sql`，SQLite 外键连接需开启 `PRAGMA foreign_keys=ON`；构建与 core 均开启 |
| 金额范围、成本≤售价、折扣≤行金额、预留≤在库 | 行级 `CHECK` |
| 付款/发货/送达日期先后、采购预计/收货日期先后 | ISO 格式时间文本的跨字段 `CHECK`；这些检查不负责解析任意格式的日期字符串 |
| 可用库存、订单总额、明细金额、采购总成本 | SQLite `GENERATED ALWAYS ... STORED`，不可直接写入 |
| 枚举和固定创建时间 | `CHECK ... IN` 和 `DEFAULT`；固定默认日期服务于可重复夹具，不代表生产系统“当前时间” |
| 订单合计=明细合计、支付/退款对账、库存=流水净额 | `validate.py` 的跨表查询，数据库单行 `CHECK` 不会自动保证 |
| 发货/退货数量不超过订单、当前事件属于此发货单、退款支付对应原订单 | `validate.py`；物理外键只能覆盖其中一部分 |
| 客户日志邮箱存在、跨表支付/退货日期合理 | `validate.py` |

验证器会执行 `integrity_check`、`foreign_key_check` 和 **12 项明确列出的业务检查**。它不宣称验证所有可能业务政策，例如税率算法、运费政策、完整订单状态机、任意 JSON 文本或员工层级必须无环。

可空跨表循环通过合法分阶段种子实现：先插入 `shipments.current_event_id=NULL`，再插入对应事件，最后回填当前事件。`shipment_events.shipment_id` 也可空，允许导入尚未归属的物流事件。种子中所有事件最终归属发货单。员工层级有两名经理与各自的一名下属，不包含非法循环。

## baseline 与压力范围

`baseline.yaml` 使用 Faker / `zh_CN`、显式 seed 和字段规则，在现有合法种子上追加：

| 表 | 追加行数 | 配置目的 |
| --- | ---: | --- |
| warehouses | 4 | 已有租户引用、唯一仓库编号、城市和容量 |
| customers | 6 | 中文姓名、邮箱、电话及数据库默认值 |
| suppliers | 4 | 唯一编号和公司名称 |
| products | 8 | 商品语义名称、整数金额、互不冲突的成本/售价范围 |
| tags | 6 | 窄表、唯一标签 |
| audit_events | 10 | 无 FK 的 `shared_pool` 邮箱关联 |
| 合计 | **38** | 其余 18 表保持种子状态 |

此配置不是“让 24 张表全部生成”的缩写。只有表中的六项承诺已经过真实追加验证；其他复杂表用于结构与能力边界测试。seed 保证同一运行环境中的重复实验可比较，不承诺任意 Faker 版本输出一致，也不承诺对同一数据库反复执行固定 seed 永远不会与已有唯一值冲突。可重复实验应重新构建或使用 `verify.py` 的新临时副本。

`stress.yaml` 是**预期检查失败**的诊断配置，选择订单、发货和三列归属相关表。当前正式 Web 返回：

- `composite_fk_width`：三列及以上组合 FK 的完整元组配对尚未保证。双列 FK 的支持也不代表多个重叠关系或跨表业务合计已自动解决。
- `cross_table_cycle`：跨表循环需要通用分阶段回填，当前 Web 不安全执行这种计划。

Core 对跨表循环可能警告后尝试断环；这不等于保证循环关系的业务正确性。本夹具不会调用 core 对 `stress.yaml` 强行写入。员工复合自引用、跨字段条件 CHECK、跨表聚合和库存收支也没有纳入 baseline 承诺。这里没有触发器，用于把普通关系/规则问题与触发器副作用分开诊断。全部 DDL 面向 SQLite，未宣称 PostgreSQL 兼容或验收通过。

## 实测记录

2026-09-07，在当前本地工作树中完成：

- 两次重建的 SQL logical dump 完全相同，重复目标拒绝覆盖；24 表都有种子。
- SQLite 实际拒绝跨租户引用、非法折扣/日期/库存以及直接写 generated 列。
- Web 实际读取 24 表、38 组外键；baseline 检查和 10 条上限预览通过，实际数量受每表配置行数限制。
- core `fill_from_config(..., skip_ai=True)` 在临时副本中追加 38 行，121 → 159；无生成错误，外键、完整性及 12 项业务检查通过。
- 压力配置实际返回上述两个边界错误；原输入文件字节保持不变。
- 专属 pytest **5 项通过**，ruff check / format 通过。未调用真实 LLM，未运行 PostgreSQL。

文件说明：`schema.sql` 定义结构；`build.py` 提供固定合法种子；`validate.py` 只读核验；`verify.py` 负责临时副本上的真实生成和可选 Web 探测；`test_fixture.py` 为专属回归。根测试默认不会自动收集 `examples/`，需要显式执行上面的测试命令。
