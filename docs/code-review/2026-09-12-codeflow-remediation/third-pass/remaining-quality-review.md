# 剩余非 broad 告警与 clone 的新一轮实施建议

当前远端 ef7b279 对应 28 个非 broad Pylint 告警、10 组 jscpd。建议先做真实共享职责，不为扫描计数改签名或隐藏非法输入。本轮已另外实施 ExceptionInfo.type 两处（见末尾）；LLM 共享调用边界已实施并冻结，完成 28 个边界回归与 101 个 healer 回归；具体实现采用延迟 request closure。

## Pylint 28 条

| 类别 | 新结论与可实施范围 | 代价/边界 |
|---|---|---|
| 13 精确 type 判断 | 两处 pytest 异常断言直接用 `caught.type is ExpectedError`，官方 API 提供实际异常类，精确性不变。其余 11 处可集中为带 TypeGuard 的 exact-type primitive；例如 `has_exact_type(value: object, expected: type[T]) -> TypeGuard[T]`，内部取得 `actual = type(value)` 后做 `actual is expected`。在 Core/Web 多个 batch/attempt/数值范围验证复用它，统一拒绝 bool、IntEnum、int/str 子类及 `__class__` 伪装，并改善 mypy narrowing；测试继续验证同一精确合同。 | 不推荐各调用点只缓存变量或反转比较以躲 rule。若采用 primitive，必须明确承担跨边界精确类型政策，并用已有实际 DataStream/fill/关系参数验证证明拒绝集合不变。私有 utility 不导入上层，Core 仍离线。tmp 原型已通过 mypy strict 和同版目标 Pylint。 |
| 10 tuple membership | 可先共享真正重复的有序 generator families：`(None, 'string')` 两处，以及 `('autoincrement', 'foreign_key_or_integer')` 两处。将它们作为带业务含义的不可变私有类别，保留 tuple membership，可统一后处理分类且不引入 hash。其余文本/数值/时间组可在真实 generator policy helper 中集中，原始值保留、不提前校验或强转；调用仅匹配指定 family，不能先全量分类而增加相等运算。 | 单用 set 或 `isinstance(raw,str) and raw in set` 都不全面等价：str 子类可不可 hash，任意 malformed list/dict 也应继续原流程。仅把一次性 literal 搬到常量不算实质改善。`case None` 使用 identity，而 `(None,...)` 可能调用自定义 equality；不能把 match 当作所有 Any 上严格等价。数值 `{0,1}` 检查保 bool/float/Decimal 等现有等值语义，不改成只接受 int。 |
| 3 try-except-raise | 3 级 healer 共享真实同步 `_call_llm` + `LLMCallOutcome`。统一一次 RPC、可恢复失败分类、每级 failure log callback 和结束计时。只捕获原 `(RuntimeError, AttributeError, ValueError)`；其中 `issubclass(type(exc), OSError)` 优先自然重新抛出，多继承与真实异常类型规则不变。返回原 error identity。 | 比引入 generic capture/contextmanager 更直接，确有 3 caller 共用领域合同。不要每个 handler 就地改成 isinstance 再 raise。`isinstance(exc,OSError)` 会接受异常对象伪装的 `__class__`，与 except 的真实类型规则不同。详见后述 API/时序；与 D09 协同。 |
| 2 consider-using-with | subprocess 可提取真正 `_InstallerSession` owner（启动 process+reader，结束时按原条件 join/close）；IPC 可提取可转交的 `_RequestPermit`，reader 非阻塞取得，worker 持有到发送完成后 release，thread.start 失败由原 owner 回收。标准 ExitStack.pop_all 可以表达清理责任转交。 | 不直接使用 Popen.__exit__：它退出时关闭 pipes 并 wait，会改变异常路径等待、reader 仍活跃时的关闭行为。也不直接 `with semaphore`：reader 会阻塞或提前释放。两个 owner 都是较大生命周期重构，应在明确线程/进程清理收益时实施，不能只套壳避告警；必须保超时、killpg、输出清理和 pending/channel 语义。 |

Python 3.10 pattern matching 不是 exact type 替代品：class pattern 使用 isinstance，接受子类；`match type(value): case builtins.int:` 是 value pattern 的 equality，恶意 metaclass 可以伪装相等。True/False 的 singleton pattern 可用于精确布尔域，但不应为两条告警引入通用匹配框架。[Python pattern 规范](https://docs.python.org/3/reference/compound_stmts.html#class-patterns)

`ExceptionInfo.type` 是 pytest 官方公开能力，并给出 `exc_info.type is ValueError` 示例。[pytest API](https://docs.pytest.org/en/stable/reference/reference.html#pytest.raises)

Popen 的 context manager 退出会关闭标准流并等待；ExitStack 的 pop_all 可将清理责任移交另一个 stack。[Popen 文档](https://docs.python.org/3.10/library/subprocess.html#popen-objects) · [ExitStack 文档](https://docs.python.org/3/library/contextlib.html#contextlib.ExitStack)

## 10 组 jscpd（沿用旧报告编号；D10 已修复）

| Pair | 新方案与优先级 | 关键边界 |
|---|---|---|
| D01 database tests imports/fixture | 已由父任务实施：counts/transaction 两个 yield fixture 合并到现有 test_database/conftest.py，共享 sqlite_schema_adapter context manager。 | 真正统一 close ownership；7 个测试 body/schema AST 保持不变，test_database 全套通过，具体统计由父任务记录。 |
| D02 Base datetime/timestamp | 暂保留；等正式 generator alias 功能需要时再设计。 | timestamp 目前 late-bound `self._gen_datetime`；直接函数 alias 会绕过 override，kwargs wrapper/descriptor 则影响签名、defaults、参数错误或引入动态机制。当前没有重复算法。 |
| D03 Base/Native date | 与 D04/D05整体研究，目前不优先。 | Base hook + Native no-op 不等价：Faker locale fallback 显式 MethodType(BaseProvider._gen_date,self) 必须仍推进 Base counter。 |
| D04 date primitives/datetime signature | 不为两行 primitive 调用再拆 helper。 | 算法已共享；要统一实现需按“绑定的实现”固定 counter 政策，而不是按实例动态 dispatch。动态严格签名方法工厂代价高于收益。 |
| D05 datetime/time | 日期 family 有真实产品重构需求时再做。 | 必须保 date draw → time validation → time draw，包括无效时间参数时已消费 date RNG 的事实；签名必须可反射。 |
| D06 DataStream 两阶段参数 | 中：私有 RowAttempt/RowReservations 聚合 row、generated values 和已登记 composite keys，两个阶段仍分开。 | 去除真正重复传递状态并明确 rollback ownership；验证不删除旧行占用key、cancel/budget/transform回滚及backtrack顺序。不能把不同阶段合并成一长函数。 |
| D07 runtime/test imports | 中：与 D08共用私有 HealComponents 装配 factory。 | runtime/真实测试共享默认组件装配，测试仍直接构造HealOrchestrator，保 model/max_rounds=1/time_budget_seconds=120。不能换现runtime工厂而改预算。 |
| D08 TYPE_CHECKING/test imports | 配合 D07，共享typed component集合。 | constructor签名和原annotation名称保持，不把type-only依赖变成运行时导入；仅移动imports会产生新clone。 |
| D09 Level2/3结果尾部 | 已实施：LLMCallOutcome 集中 RPC 完成、原错误和时长；LevelResult/JSON parsing 各自保留，jscpd 原 1 pair 消除。 | 日志→失败clock；成功clock→content；content访问仍在recoverable catch外；error不得truth-test。单独包装except不会消掉该11行clone。 |
| D11 logging implementation/typing stub | 已由 fix_ai 实施并冻结：_caller.py 内私有 InteractionLoggingMixin，Caller/Streaming 共同继承，删除 Streaming TYPE_CHECKING 假实现。 | 无运行时反向import，不新增循环，保原logger/get_cache_dir globals。只读内存probe：SchemaAnalyzer 28个非dunder方法resolution identity、logging签名/kwdefaults相同；实际需mypy与两种日志回归。 |

D11 证据：`/tmp/sqlseed-clone-logging-mixin-probe.json`。这些方案不是所有克隆都必须消除的承诺；D02–05如严格API不动且不引入动态方法生成，就没有值得为扫描窗口支付的实现收益。

## 已授权 LLM call 边界 API 与时序

位置：`level1_subgraph_healer.py:heal`、`level2_column_healer.py:heal_column`、`level3_compact_healer.py:heal_compact`。

私有模块 `_llm_call.py` 提供 `LLMCallOutcome(response, error, elapsed_seconds)` 与 `call_llm(request: Callable[[], Any], *, started_at: float, on_failure: Callable[[Exception], None])`。client 仍由入口拥有；helper 不关闭 client、不重试、不异步、不读content。`request` 是包住原完整 `self._client.chat_completions_create(...)` 表达式的同步 closure，保留 `self._model` 等请求参数求值在原 recoverable catch 范围内。

调用前（每级重复）：start = monotonic → try RPC → 网络优先传播或可恢复失败日志 → monotonic；成功路径 monotonic 后读取 content。

调用后：每级保留原 start 采样，传入请求和失败日志callback；helper调用一次RPC并返回typed outcome。各级用 `outcome.error is not None` 构造原LevelResult；成功时读取 `outcome.response.choices[0].message.content`，再保留自己的空响应/JSON解析。这样将实际重复的请求生命周期集中，而不统一不同修复结果或扩大catch范围。

## 已实施的小改动

`tests/test_core/test_stream_budget.py` 两处使用 `caught.type`：2个受影响测试通过、Ruff/format通过、Pylint2.17同规则2→0。证据位于 `/tmp/sqlseed-stream-budget-exceptioninfo-*`。LLM 4 个 source 与新边界测试也已完成：101 passed、6 skipped（仅未启动的 LM Studio），完整 Pylint 2.17.7 目标报告为 0，mypy/Ruff/format 通过。源文件加新测试 jscpd 合扫 0；独立 45 组实际 caller 旧新差分通过。证据见 `/tmp/sqlseed-llm-call-result.json` 与 `/tmp/sqlseed-llm-call-report.md`。其余候选不扩展架构。
