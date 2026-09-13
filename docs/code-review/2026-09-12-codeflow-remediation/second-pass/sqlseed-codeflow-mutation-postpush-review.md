第二轮 mutation 独立复核：236 项中 228 killed、8 survived，timeout/suspicious/skipped 均为 0。8 项均与上轮已提交 evidence 的变异增删行完全相同，没有新增幸存类别或已证明必须修复的行为缺陷。**不是严格等价，也不是零幸存；`make mutmut` 原始出口仍为 Error 2。**

| 本轮 ID | 上轮 ID | unique_adjuster.py 行号 | 类别 |
| --- | --- | --- | --- |
| 84 | 87 | 160 | ConfigurationError message |
| 85 | 88 | 161 | ConfigurationError message |
| 88 | 91 | 165 | sampling_headroom |
| 100 | 103 | 174 | bounded_capacity_equality |
| 114 | 117 | 180 | ConfigurationError message |
| 130 | 133 | 192 | debug log message |
| 149 | 152 | 215 | ConfigurationError message |
| 186 | 190 | 278 | ConfigurationError message |

6 项诊断变化分别是 5 处 ConfigurationError 文案和 1 处 debug 日志。文字可观察地不同，但异常类型、触发条件、参数和控制流不变；无需添加仅检查 XX 的文案快照。

88 对应原91：count²×50→51 在二进制字符集、count9、无schema硬长度上限时，原长度12变成13；本轮实际参数计算再次重现。两者容量足够，硬约束逻辑未变。它会改变 seeded output，不能称为等价或据此应用变异。

100 对应原103：count<=最长容量改为<，等号时保留原有完整长度区间。本轮count4、二进制长度1..2由2..2变为1..2。对b>=2，count=b^M时完整区间容量Σb^k至少为count，不会新造成非空容量不足。要求全取最长长度会额外固定未承诺的分布。

新探针使用隔离copy真实 mapper/参数计算，270个有界输入×3版本=810次计算，覆盖字符数2/3/5、上限0..4、NULL比例0/0.5/1、最长容量等号及完整容量+1。未发现容量、硬长度、NULL或输入参数改写违例；100存在90个合法参数差异。未重跑真实数据库或全套测试，上轮SQLite运行仅作为历史证据。

全部8项通过隔离copy下 `mutmut show` 独立读取，source SHA256保持 `4532f18e390075685e77d302720ed04fd8c944a0be5916168b520c219781e35c`。没有修改仓库源码、测试、配置、用户环境或旧证据。详细diff、映射、探针和限制见同名JSON。
