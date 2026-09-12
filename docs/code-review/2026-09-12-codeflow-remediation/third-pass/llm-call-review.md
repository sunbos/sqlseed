# 共享 LLM 调用边界：实现与验证

三个 healer 的同步请求、失败分类、失败日志和结束计时现集中到私有 `_llm_call.py`，各层保留自己的 prompt、客户端、LevelResult、content 读取与 JSON/config 校验。没有新增重试、资源关闭、响应形状验证或异步框架。

- `request` closure 保留原参数求值的捕获范围。
- 网络异常按真实异常类型优先传播，包含 OSError 与 ValueError 等的多继承；伪装 `__class__` 不改变分类。
- 原错误对象保持身份，falsy exception 不会被当成成功。
- 失败顺序仍为 RPC → logger → clock；成功顺序仍为 RPC → clock → content。
- logger 和 clock 自身的异常、错误上下文保持原语义；借用的 client 不会被关闭。

另将两个 stream-budget 测试的精确异常类型断言改为 `ExceptionInfo.type`，仍使用 `is` 比较具体异常类。

验证：新增边界用例从 20 RED（新实现尚不存在）到 28 GREEN，另有 6 个真实 caller 用例在旧实现即通过；相关 healer 全套为 **101 passed、6 skipped**，跳过项只因 LM Studio 未启动。两项 stream-budget 测试通过。Ruff、format、mypy 通过；Pylint 2.17.7 五文件完整报告为空，原 3 条 try-except-raise 消除；两项测试原 C0123 也消除。jscpd 4.0.5 原三 source 中的 1 对重复消除，4 source 加新测试合扫为 0 对，使用原默认配置。

AST 逐项证明三个 caller 的 public signature、请求前准备、完整请求表达式、日志表达式、全部响应解析后续代码及其它模块代码不变。独立代理已经完成 source review，无阻断问题；45 组真实三 caller 旧新差分通过，比较完整 Result、请求、日志和时序。

证据：

- `/tmp/sqlseed-llm-call-result.json`：机器可读结果和 6 个文件 SHA-256。
- `/tmp/sqlseed-llm-call-healer-tests.log`：101/6 测试及 skips。
- `/tmp/sqlseed-llm-call-ast-result.json`：AST 核对。
- `/tmp/sqlseed-llm-call-pylint-full.json`：完整 Pylint 2.17.7 五文件结果。
- `/tmp/sqlseed-llm-call-jscpd-combined/jscpd-report.json`：source 与测试合扫。

源码与测试已冻结；没有 commit 或 push。全仓门禁由父任务执行。
