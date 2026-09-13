# 赋值表达式最终独立审阅

结论：在本次审阅范围内，未发现求值次数、短路顺序、closure/nonlocal 绑定或异常传播的遗漏。只读 source，在 `/tmp` 保存检查脚本与证据，没有修改源码或重复全量 pytest。

范围为提交 `064854c9c90a9b890e58a314fbe5d8fba69d1508` 到当前的原 368 条赋值表达式建议：初始 366 个转换及后来处理的 2 个显式注解位置。独立核对 86 份转换前快照的 AST，均与该推送提交相同；仅注解变更的另 1 个文件直接读取推送提交作为基线。

## 结构与绑定证据

- 独立读取旧 AST 的实际相邻 statement lists，核实全部 366 个赋值和对应 if 在同一作用域、同一语句序列；赋值目标就是条件首先求值的 operand。206 个比较、88 个直接 truth test、72 个 not test。没有把赋值移动到可能被短路跳过的位置。
- 独立规范化当前与旧 AST：将不带 else 的 and 条件还原成顺序嵌套 if，将最先求值位置的 NamedExpr 展开，再仅对已证明单次读取的临时变量内联。elif 的 AST 本就表示 else 内的 if。格式差异不进入 AST 比较。
- 初始 27 个删去绑定的临时变量，加上随后 `scripts/analyze_ai_logs.py` 的 derive_value，共 28 个。每个在其所属函数中仅 1 次 Store、1 次 Load，检查包含嵌套函数与 comprehension；未发现对应 global/nonlocal 声明或 locals/vars/eval/exec 调用依赖。内联保留 RHS 一次求值及条件读取时点。
- 87 个文件中 84 个规范化 AST 完全相同。剩下 3 个差异精确为：`scripts/_fact_extractors.py` 的已单独审阅 AST extractor、`tests/test_doc_sync.py` 的配套回归、`src/sqlseed/core/expression.py` 的错误容器替换。没有未归因差异。Web app 迁移已专项独立核验，这里合并新工厂和 facade 的原函数进行比较。
- 使用 Python compiler symtable，独立比较 85 个范围内文件、1,741 个 function/comprehension scopes 的 free/nonlocal 符号。唯一差异是 expression worker closure 的 error_container→errors，与明确的容器替换一致；其余 closure/nonlocal 绑定相同。
- `core/orchestrator/_generation.py` 的 values 保留无初始值的 `list[str | int]` 注解，原 RHS 移到紧随其后的 walrus。CLI 测试的私有 `_AI_PLUGIN_AVAILABLE` 去掉 bool 注解，RHS AST 完全一致且 `is not None` 必定产生 bool；这是明确允许的模块注解元数据变化，不声称模块 `__annotations__` 完全相同。

## expression 错误容器补核

该变更将初始化 `[None]` 的 optional sentinel 替换为 `list[Exception]`，worker 的一次 evaluate 最多捕获并 append 一次 Exception。主线程 join 后先检查是否超时，然后在 errors 非空时抛出 errors[0]。检查的是普通 list 是否为空，不会调用异常对象的 `__bool__`；timeout、daemon 和 BaseException 捕获范围不变。

独立加载推送前实现与当前实现，执行真实线程差分：

- 两个实现各 10 个正常返回值，均保留对象 identity，包括 None、False、0、空容器及自定义对象。
- 两个实现各 6 个异常，均传播同一对象，含普通运行错误、`__bool__` 返回 False、`__bool__` 主动抛错、OSError/ValueError 多继承异常。每次用户函数只在线程内调用一次。
- 两个实现均保持 timeout 异常类型名与消息、daemon 属性；使用 Event 有界释放线程并确认回收。
- 自定义 BaseException 仍交由 threading.excepthook，未被改成 Exception 捕获；保持原有返回行为。
- 同 seed 的 30 次复合随机表达式结果完全一致。

上述共 36 个正常/异常/timeout/control 实例检查，加 30 对 seed 结果，全部通过。没有把测试通过扩张为任意线程调度或依赖内部栈帧反射的证明。

## 证据

- `/tmp/sqlseed-walrus-independent-review.py` 与 `-result.json`：366 个逐项 witness、28 个临时变量证据、87 文件规范化结果和源码 hash。
- `/tmp/sqlseed-walrus-closure-review.py` 与 `-result.json`：1,741 个作用域的 compiler binding 核对及最终注解检查。
- `/tmp/sqlseed-expression-error-independent-probe.py` 与 `-result.json`：真实线程旧新比较。
- `/tmp/sqlseed-walrus-independent-diffs/`：规范化后余下专项差异，供审阅定位。

本审阅不重复其它代理负责的 NamedTuple、fact extractor、纯格式变更、Web factory 迁移或参数名变更；这些只按已有独立证据划定边界，没有隐藏未知源码差异。
