# Mutation survivor 独立审查

审查基线：`5b0dd07231d7ed9fbc33f924087e1e9dda878100`。对象：`src/sqlseed/core/unique_adjuster.py` 当前工作树，SHA-256 `3722238418f26a9918c818e8b54f52e961339a2338424c4c70c49ea68a437b36`。

结论：8 项均可作为逐项审阅后的 survivor 接受；未发现必须补测的真实合同违例。**没有把任何一项称为严格等价，也没有宣称 mutation 为零幸存或直接等同于门禁全绿。** 当前源码、测试、mutation 配置均未修改。

| IDs | 位置 | 判断 |
| --- | --- | --- |
| 87、88、117、152、190 | 163、164、183、218、281 | 5 处 ConfigurationError 文案片段/消息；异常类型、触发条件与时机未变，不增加仅检查 XX 或完整文案的测试。 |
| 133 | 195 | debug 文案变化；日志输出并非严格相同，但不影响参数或生成结果。 |
| 91 | 168 | 采样余量系数 50→51，可能改变长度及 seeded output；无 UNIQUE/CHECK/NULL 合同违例。 |
| 103 | 177 | 等号边界会保留更短合法长度，改变结果分布；容量仍够用，非严格等价。 |

## 91：可观察差异，但没有硬约束违例

真实 SQLite 表 `items(code TEXT NOT NULL UNIQUE)`，参数 `charset="01", min_length=1, max_length=1`，`count=9, seed=42`。原实现选长度 12，mutant 选 13，因为 `50×9²=4050 ≤ 2¹²=4096 < 51×9²=4131`。两者均实际写入 9 个不同值且无错误。

系数增长 2% 会增大采样余量，在临界点增加长度；已存在的 schema 硬上限仍受约束。未发现公开合同要求恰好使用 50 或最短的某个采样宽度。可以测试容量、合法字符、schema 上限及实际 UNIQUE 行数；为区分 50/51 而固定具体宽度，会把启发式常量变成新合同。此处接受 survivor 不意味着建议应用该变异。

## 103：等号分支的数学与真实数据库证据

真实 SQLite 表具有 `UNIQUE CHECK(length(code) BETWEEN 1 AND 2)`；参数二进制字符集、长度 1..2，`count=4, seed=42`。原实现把参数缩为 2..2，生成 `01,00,10,11`；mutant 保持 1..2，生成 `0,00,1,11`。两者均完整写入 4 行且 UNIQUE/CHECK 成立。

设字符数 `b≥2`，合法长度区间 `[m,M]`，差异仅发生在 `count=b^M`。全区间容量 `Σ(b^k), k=m..M` 至少等于 `b^M`，因此新走容量分支不会在该边界错误拒绝请求。固定长度区间输出参数不变。要求所有值都达到最大长度，会新增原本未承诺的分布规则；普通边界行为测试可以新增，但不会合理杀死此 mutant。

## 独立验证

- 将当前源码与 91/103 单行变异仅编译到内存，未执行 `mutmut apply`。
- 1,578 个有界输入 × 3 版本 = 4,734 次真实 mapper/CHECK parser 参数计算；字符数 2..5、最大长度 0..5、NULL 比例 0/0.5/1，覆盖最长长度容量与总容量上下边界。
- 核验完整域容量、非空不足时异常、schema 长度区间、剩余容量、NULL 比例和原始 spec 不被改写；未发现违例。91 在此有限矩阵无参数差异；103 有 180 个合法参数差异。
- 上述两例各执行 baseline/mutant，共 4 次真实 SQLite/DataOrchestrator 生成，全部满足行数、唯一性和相应 CHECK。
- 未重跑全仓测试或性能 benchmark；未运行真实 PostgreSQL。逐项结论不是整个输入域的测试穷举。

完整参数、生成值及机器可读审查结论见 `/tmp/sqlseed-codeflow-mutation-probe.json` 和 `/tmp/sqlseed-codeflow-mutation-review.json`。
