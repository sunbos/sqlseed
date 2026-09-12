# 剩余静态告警逐项审阅

未发现必须继续修改的安全等价修复。81 条 Pylint 保留均有异常边界、精确类型、不可 hash 输入或资源所有权依据；11 组 jscpd 主要是签名/import/类型合同，但其中也包含短编排和重复 Click 声明，不能一概标为纯签名。

后续授权修复：D10 已通过私有 `_ai_model_options` 实现3个 Click options 的真正共享，目标 jscpd 1→0；3命令签名/帮助/元数据与216组输入解析均一致，32项测试通过。原始11组记录保留用于审计，其余预计10组需由父任务全仓扫描确认。D04/D05 仍可进一步共享短日期编排，但主要算法已共用 helpers，签名克隆仍会存在。

Pylint：broad-exception-caught=53, use-set-for-membership=10, try-except-raise=3, consider-using-with=2, unidiomatic-typecheck=13。

## Pylint 逐项

| ID | 位置与规则 | 保留理由 |
| --- | --- | --- |
| P01 | [examples/build_showcase_db.py:471](/Users/sunbo/Desktop/sqlseed/examples/build_showcase_db.py:471) · `broad-exception-caught` | 示例批处理逐表报告任意生成失败并继续其他表；这是最外层诊断边界。 |
| P02 | [examples/order_workflow/run.py:232](/Users/sunbo/Desktop/sqlseed/examples/order_workflow/run.py:232) · `broad-exception-caught` | 命令行最外层将任意业务/IO/adapter失败转为带非零exitcode的诊断。 |
| P03 | [plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:108](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:108) · `broad-exception-caught` | docstring承诺日志禁用或失败返回None。缓存目录创建、JSON编码、文件写入属于附属诊断，任何普通Exception均不得遮蔽已取得的LLM结果或原始业务失败。收窄为某几个I/O异常会缩减这个best-effort合同。BaseException仍自然传播。 |
| P04 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1091](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1091) · `use-set-for-membership` | generator 从待修复列配置读取，支持 None/string；保留 tuple 避免在检测路径新增对 list/dict 的哈希要求。 |
| P05 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1338](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1338) · `use-set-for-membership` | generator 为 _ColumnRuleContext 中流入的 Any；检测 string/catch_phrase 时只需相等比较，不能提前引入 set 哈希失败。 |
| P06 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1381](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1381) · `use-set-for-membership` | 待修复的 generator 是 Any；name/catch_phrase/template 匹配保留原有线性比较及异常边界。 |
| P07 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1610](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:1610) · `use-set-for-membership` | 对原始 generator 的 integer/float 检测不能改变尚未通过模型校验的非法集合输入行为。 |
| P08 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2373](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2373) · `use-set-for-membership` | 此独立后处理从 dict.get 读取 gen_c，既没有 str 断言，也不应由成员检测引入 list/dict 的 TypeError。 |
| P09 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2553](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2553) · `use-set-for-membership` | 此独立后处理从 dict.get 读取 gen_sn，保留非法集合 generator 在此分支被跳过、由原流程继续处理的行为。 |
| P10 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2719](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2719) · `use-set-for-membership` | ac_gen_sn 来自列配置 Any（对应 SQL type 的另一个 str.upper 成员检测已安全改 set）；保留 generator 的非哈希匹配语义。 |
| P11 | [plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2901](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/auto_heal/orchestrator.py:2901) · `use-set-for-membership` | 恢复来源列的 source_generator 来自原始 dict，None/string 比较无需哈希，仍保留第一同名来源列即停止的行为。 |
| P12 | [plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py:150](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/level1_subgraph_healer.py:150) · `try-except-raise` | 合法class MixedNetworkError(OSError, RuntimeError)同时属于网络与recoverable类型；原顺序传播网络异常，删除首handler则会进入recoverable并返回失败Result，违反文档网络传播合同。LLMClient为可注入Protocol，异常不只限SDK内建类。 |
| P13 | [plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py:274](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py:274) · `try-except-raise` | 合法class MixedNetworkError(OSError, RuntimeError)同时属于网络与recoverable类型；原顺序传播网络异常，删除首handler则会进入recoverable并返回失败Result，违反文档网络传播合同。LLMClient为可注入Protocol，异常不只限SDK内建类。 |
| P14 | [plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py:123](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py:123) · `try-except-raise` | 合法class MixedNetworkError(OSError, RuntimeError)同时属于网络与recoverable类型；原顺序传播网络异常，删除首handler则会进入recoverable并返回失败Result，违反文档网络传播合同。LLMClient为可注入Protocol，异常不只限SDK内建类。 |
| P15 | [plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:616](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:616) · `broad-exception-caught` | 动态SQLAlchemy reflection、Python VARCHAR值转换、dialect/DBAPI bind和INSERT均可能失败；非FK失败统一summarize_error供下一次提示，FK错误按既有规则容忍。transaction.rollback位于finally，普通Exception汇总与BaseException传播/回滚边界分别保留。缩窄捕获会令部分候选预验直接中断refinement而不再产生ErrorSummary。 |
| P16 | [plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:694](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:694) · `broad-exception-caught` | 代码明确规定reflection失败跳过此预检并依靠后续preview验证；此处不是最终成功判定。SQLAlchemy/dialect反射异常统一回落，收窄会把可降级的预检错误变为入口失败。只捕获Exception，不吞进程控制异常。 |
| P17 | [plugins/sqlseed-ai/src/sqlseed_ai/repair/executor.py:92](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/repair/executor.py:92) · `broad-exception-caught` | __init__(strategies:dict[str,RepairFn]/None)允许外部纯函数；其异常种类不能由executor穷举。普通执行/返回配置合并失败记录为unfixable并继续其它violation，不误计applied_fixes。收窄到内建策略当前异常会改变扩展策略合同。BaseException仍传播。 |
| P18 | [plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py:569](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/repair/strategies.py:569) · `use-set-for-membership` | ViolationReport.fix_params接收Any；check_values=[[1]]在原tuple比较中返回False并保持原col，换set会TypeError。不能为建议引入新的非法输入异常。 |
| P19 | [plugins/sqlseed-ai/src/sqlseed_ai/validator/single_column.py:256](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/validator/single_column.py:256) · `use-set-for-membership` | col是dict[str,Any]，gen=[]且存在数值CHECK时原tuple比较为False并返回None，换set将TypeError。该非法不可hash输入已在256个single-check差分中覆盖。 |
| P20 | [plugins/sqlseed-ai/tests/healer/conftest.py:25](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/tests/healer/conftest.py:25) · `broad-exception-caught` | 真实 LLM 测试的可用性探测边界：导入/HTTP 客户端/本机服务任一普通异常统一为不可用并触发已有 skip 合同；不是“异常即通过”的业务断言。窄化会把环境不可用改为 fixture error。此边界可能隐藏探测自身编程错误，属于另行调整测试基础设施诊断合同的权衡。 |
| P21 | [plugins/sqlseed-web/src/sqlseed_web/api.py:167](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:167) · `broad-exception-caught` | bytes 子类由数据库驱动提供，其 decode 可抛任意异常；目前明确 best-effort repr fallback。改 bytes.decode 将绕过子类方法，删除或缩窄捕获会改变该契约。 |
| P22 | [plugins/sqlseed-web/src/sqlseed_web/api.py:220](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:220) · `broad-exception-caught` | 后台 fill 任务可进入 adapter、插件和 generator；所有异常均须 complete_job，避免 running/锁永久残留。 |
| P23 | [plugins/sqlseed-web/src/sqlseed_web/api.py:485](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:485) · `broad-exception-caught` | 远端服务探测和可选 AIConfig 方法边界，任何失败必须保持固定、无凭证的可达性响应。 |
| P24 | [plugins/sqlseed-web/src/sqlseed_web/api.py:616](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:616) · `broad-exception-caught` | 行数只是 best-effort 活进度，连接关闭或任意驱动错误不能使已有 job 状态查询失败。 |
| P25 | [plugins/sqlseed-web/src/sqlseed_web/api.py:800](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:800) · `broad-exception-caught` | 现契约将所有配置读取失败转换 valid=False。load_config_from_text 包含 tempfile 创建/写入、core YAML/Pydantic校验、unlink清理，不能只捕获 ValidationError；要窄化需先明确 HTTP500 与 valid=False 的产品契约并回归。 |
| P26 | [plugins/sqlseed-web/src/sqlseed_web/api.py:885](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:885) · `broad-exception-caught` | 实验室可选 validator/schema/DB边界；HTTPException 单独传播，其余异常转换 ok=False。窄化改变已有实验室错误响应。 |
| P27 | [plugins/sqlseed-web/src/sqlseed_web/api.py:919](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:919) · `broad-exception-caught` | 实验室可选 repair pipeline/schema/DB边界；HTTPException 单独传播，其余异常转换 ok=False。窄化改变已有实验室错误响应。 |
| P28 | [plugins/sqlseed-web/src/sqlseed_web/api.py:1030](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/api.py:1030) · `broad-exception-caught` | 后台 AI SDK/validator/adapter任务隔离；真实SDK先关闭，然后任意失败都必须发布 job 终态。新共享helper保留该生命周期回归。 |
| P29 | [plugins/sqlseed-web/src/sqlseed_web/plugin_management.py:284](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/plugin_management.py:284) · `broad-exception-caught` | 安装工具及元数据核验任务边界；任意工具异常都转为固定消息，finally保证任务完成状态。 |
| P30 | [plugins/sqlseed-web/src/sqlseed_web/plugin_process.py:72](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/plugin_process.py:72) · `consider-using-with` | Popen 生命周期含有限wait、杀整个超时进程组、reap、输出reader限时join及只在reader退出后关闭stdout。普通Popen.__exit__ 的wait/pipe关闭不等价，不能机械嵌套替换。 |
| P31 | [plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:48](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:48) · `broad-exception-caught` | 第一处隔离单个数据库恢复失败以继续后续连接；第二处 best-effort关闭失败不能掩盖固定脱敏恢复失败条目。 |
| P32 | [plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:53](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:53) · `broad-exception-caught` | 第一处隔离单个数据库恢复失败以继续后续连接；第二处 best-effort关闭失败不能掩盖固定脱敏恢复失败条目。 |
| P33 | [plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:186](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:186) · `broad-exception-caught` | importlib.metadata 可由第三方 metadata finder/provider 实现并任意失败；未知元数据错误不等同未安装，保持脱敏 import_error。 |
| P34 | [plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:235](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:235) · `broad-exception-caught` | 第一处第三方metadata异常转换不可用；第二处可选插件import会执行任意初始化代码及接口验证，所有失败只能暴露状态而非依赖凭证。 |
| P35 | [plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:245](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:245) · `broad-exception-caught` | 第一处第三方metadata异常转换不可用；第二处可选插件import会执行任意初始化代码及接口验证，所有失败只能暴露状态而非依赖凭证。 |
| P36 | [plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:119](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:119) · `broad-exception-caught` | 安装和维护模式任务边界；任意安装前检查/父任务异常都必须转入固定脱敏失败状态，并继续业务恢复。 |
| P37 | [plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:130](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:130) · `broad-exception-caught` | 任意 worker 恢复异常必须转换 recovery_failed 和 service_ready=False，避免安装任务停留中间态。 |
| P38 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:194](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:194) · `broad-exception-caught` | 服务探测包括配置解析与HTTP响应处理；ImportError 已分支，任意剩余错误仍必须脱敏。 |
| P39 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:368](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:368) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P40 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:370](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:370) · `unidiomatic-typecheck` | 要求实际内建 bool 类型。虽然 bool 不允许子类化，isinstance(value, bool) 仍会接受伪装 __class__ 为 bool 的任意对象；不能笼统宣称二者对所有 Any 等价。True/False singleton 组合虽等价但只是更长的绕写，保持统一精确类型断言。 |
| P41 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai_relations.py:96](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai_relations.py:96) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P42 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai_relations.py:111](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai_relations.py:111) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P43 | [plugins/sqlseed-web/src/sqlseed_web/workbench_ai_stream.py:56](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_ai_stream.py:56) · `broad-exception-caught` | 任意异步分析异常必须发布脱敏终态事件，并在 finally 释放连接分析 gate。 |
| P44 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:702](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:702) · `broad-exception-caught` | 每表 generator/provider 可抛自定义异常；转成表级 generation_invalid。取消异常单独传播，budget异常保留具体诊断。 |
| P45 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:733](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:733) · `broad-exception-caught` | adapter、provider 初始化和 contextmanager 退出可抛任意异常；统一脱敏 validation_failed；GenerationCancelledError 单独还原原始原因。 |
| P46 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:757](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:757) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P47 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:924](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:924) · `broad-exception-caught` | 启动失败后的次级持久化失败不得阻止 finally complete_job 释放已预留任务。 |
| P48 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1037](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1037) · `broad-exception-caught` | 读取运行快照失败后的次级持久化失败不得阻止 finally complete_job。 |
| P49 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1125](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1125) · `broad-exception-caught` | 终态持久化及其有界二次尝试失败仍必须最终发布内存终态并释放 job；不能令存储异常越过该边界。 |
| P50 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1136](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1136) · `broad-exception-caught` | 终态持久化及其有界二次尝试失败仍必须最终发布内存终态并释放 job；不能令存储异常越过该边界。 |
| P51 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1152](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1152) · `broad-exception-caught` | 第一处捕获快照读取/存储初始化失败并释放任务；第二处捕获所有执行层、数据库、generator/provider失败，保留已提交数量并经 finally 发布终态。 |
| P52 | [plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1168](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1168) · `broad-exception-caught` | 第一处捕获快照读取/存储初始化失败并释放任务；第二处捕获所有执行层、数据库、generator/provider失败，保留已提交数量并经 finally 发布终态。 |
| P53 | [plugins/sqlseed-web/src/sqlseed_web/worker_control.py:104](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/worker_control.py:104) · `consider-using-with` | acquire(blocking=False) 在reader线程获得名额，由另一个 _answer 线程 finally release。with semaphore 会阻塞reader或在worker结束前过早release，破坏8并发限制。 |
| P54 | [plugins/sqlseed-web/src/sqlseed_web/worker_control.py:123](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/src/sqlseed_web/worker_control.py:123) · `broad-exception-caught` | 用户/插件 handler 通过 IPC 边界执行；HTTPException/ControlError 已分别处理，其余异常仅公开固定503且释放槽位。 |
| P55 | [plugins/sqlseed-web/tests/test_plugin_process.py:38](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-web/tests/test_plugin_process.py:38) · `broad-exception-caught` | 将后台线程的任意普通异常收集到 failures，并唤醒主线程，后续断言要求 failures 为空；不捕获会失去原始错误并可能只得到等待超时。线程和 subprocess 清理仍由 finally 执行。 |
| P56 | [scripts/complex_validation/ai_offline_validation.py:116](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/ai_offline_validation.py:116) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P57 | [scripts/complex_validation/ai_offline_validation.py:408](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/ai_offline_validation.py:408) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P58 | [scripts/complex_validation/randomized_roundtrip.py:209](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/randomized_roundtrip.py:209) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P59 | [scripts/complex_validation/randomized_roundtrip.py:273](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/randomized_roundtrip.py:273) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P60 | [scripts/complex_validation/repro_defects.py:71](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/repro_defects.py:71) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P61 | [scripts/complex_validation/repro_roundtrip.py:35](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/repro_roundtrip.py:35) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P62 | [scripts/complex_validation/run_validation.py:121](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/run_validation.py:121) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P63 | [scripts/complex_validation/smoke_test.py:93](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/smoke_test.py:93) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P64 | [scripts/complex_validation/smoke_test.py:126](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/smoke_test.py:126) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P65 | [scripts/complex_validation/smoke_test.py:133](/Users/sunbo/Desktop/sqlseed/scripts/complex_validation/smoke_test.py:133) · `broad-exception-caught` | 诊断/回归harness需要将任意意外失败记录为失败或聚合结果，并继续其他案例；缩窄会丢失报告。将“任意异常即成功”的S8负数计数验证已另行修正。 |
| P66 | [src/sqlseed/core/expression.py:228](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/expression.py:228) · `broad-exception-caught` | 工作线程必须将任意表达式/插件异常交回调用线程，否则线程失败会被误报为NULL结果。 |
| P67 | [src/sqlseed/core/features.py:336](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/features.py:336) · `broad-exception-caught` | 可选 adapter metadata 探测按既有合同保留已读取的部分结果；第三方adapter的异常集合无法穷举。 |
| P68 | [src/sqlseed/core/features.py:397](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/features.py:397) · `broad-exception-caught` | 可选 adapter metadata 探测按既有合同保留已读取的部分结果；第三方adapter的异常集合无法穷举。 |
| P69 | [src/sqlseed/core/orchestrator/_generation.py:326](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/orchestrator/_generation.py:326) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P70 | [src/sqlseed/core/orchestrator/_generation.py:413](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/orchestrator/_generation.py:413) · `broad-exception-caught` | 顶层生成边界将非配置异常汇总为GenerationResult，保留已提交行数；ConfigurationError单独传播。 |
| P71 | [src/sqlseed/core/orchestrator/_specs.py:513](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/orchestrator/_specs.py:513) · `broad-exception-caught` | 可选CHECK提取失败时保留此前比较规则，由真实INSERT检查其余约束。 |
| P72 | [src/sqlseed/core/relation.py:232](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/relation.py:232) · `broad-exception-caught` | 插件adapter metadata失败有既有FK推断fallback，不能因更换异常种类改变整表生成可用性。 |
| P73 | [src/sqlseed/core/relation.py:544](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/relation.py:544) · `broad-exception-caught` | 插件adapter metadata失败有既有FK推断fallback，不能因更换异常种类改变整表生成可用性。 |
| P74 | [src/sqlseed/core/relation.py:701](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/relation.py:701) · `broad-exception-caught` | 插件adapter metadata失败有既有FK推断fallback，不能因更换异常种类改变整表生成可用性。 |
| P75 | [src/sqlseed/core/stream.py:153](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/stream.py:153) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P76 | [src/sqlseed/core/stream.py:259](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/stream.py:259) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P77 | [tests/test_core/test_stream_budget.py:37](/Users/sunbo/Desktop/sqlseed/tests/test_core/test_stream_budget.py:37) · `unidiomatic-typecheck` | 回归断言要求精确的 GenerationBudgetExceededError/GenerationCancelledError，而非任意派生异常；同时验证取消原因与预算合同，不能为 lint 放宽异常类型断言。 |
| P78 | [tests/test_core/test_stream_budget.py:103](/Users/sunbo/Desktop/sqlseed/tests/test_core/test_stream_budget.py:103) · `unidiomatic-typecheck` | 回归断言要求精确的 GenerationBudgetExceededError/GenerationCancelledError，而非任意派生异常；同时验证取消原因与预算合同，不能为 lint 放宽异常类型断言。 |
| P79 | [tests/test_generators/test_generator_quality_regressions.py:82](/Users/sunbo/Desktop/sqlseed/tests/test_generators/test_generator_quality_regressions.py:82) · `unidiomatic-typecheck` | 参数或 JSON schema 输出必须是精确内建 int；普通 isinstance(..., int) 会接受 bool、IntEnum、int 子类和 __class__ 伪装，放宽已有输入/输出合同。 |
| P80 | [tests/test_generators/test_generator_quality_regressions.py:83](/Users/sunbo/Desktop/sqlseed/tests/test_generators/test_generator_quality_regressions.py:83) · `unidiomatic-typecheck` | 要求实际内建 bool 类型。虽然 bool 不允许子类化，isinstance(value, bool) 仍会接受伪装 __class__ 为 bool 的任意对象；不能笼统宣称二者对所有 Any 等价。True/False singleton 组合虽等价但只是更长的绕写，保持统一精确类型断言。 |
| P81 | [tests/test_generators/test_generator_quality_regressions.py:84](/Users/sunbo/Desktop/sqlseed/tests/test_generators/test_generator_quality_regressions.py:84) · `unidiomatic-typecheck` | JSON schema 回归验证生成值是内建 str，不接受带额外行为的 str 子类或 __class__ 伪装；这是输出类型断言。 |

## jscpd 逐组

### D01 — imports_and_fixture_declaration

- [tests/test_database/test_insert_actual_count.py:3](/Users/sunbo/Desktop/sqlseed/tests/test_database/test_insert_actual_count.py:3) ↔ [tests/test_database/test_sqlalchemy_transaction.py:3](/Users/sunbo/Desktop/sqlseed/tests/test_database/test_sqlalchemy_transaction.py:3)，16行检测窗口。

from __future__/TYPE_CHECKING、pytest/IntegrityError/adapter/helper imports，加同名局部 database(tmp_path) 声明；真实 DDL 分别验证 ignored insert/trigger 计数与显式事务原子性，内容不同。共同 SQLite 连接已走 helper。把正常 imports 或不同数据库 fixture 合并只为减少 token 重复会降低测试自足性。

### D02 — strict_signature_and_documentation

- [src/sqlseed/generators/base_provider.py:446](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/base_provider.py:446) ↔ [src/sqlseed/generators/base_provider.py:395](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/base_provider.py:395)，24行检测窗口。

BaseProvider._gen_timestamp 与 _gen_datetime 的关键字参数/默认值/返回 datetime 合同一致；timestamp 的实际实现已经委托 self._gen_datetime，保留动态 override 与签名反射。不是第二套算法。

### D03 — strict_override_signature

- [src/sqlseed/generators/_native_provider.py:41](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/_native_provider.py:41) ↔ [src/sqlseed/generators/base_provider.py:369](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/base_provider.py:369)，9行检测窗口。

NativeProvider._gen_date 覆写 BaseProvider 同名生成器，因此必须公开相同关键字签名/defaults/返回 date；native 不推进 Base placeholder counter，不能简单删除 override。

### D04 — signature_with_shared_primitive_calls

- [src/sqlseed/generators/_native_provider.py:51](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/_native_provider.py:51) ↔ [src/sqlseed/generators/base_provider.py:392](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/base_provider.py:392)，16行检测窗口。

片段跨 _gen_date 末尾的两行共同 helper 调用和 _gen_datetime 严格签名。日期数值算法已经共享 resolve_date_bounds/random_date/normalize_weekdays；Base 在这些调用前 _next_id，native 不推进计数。继续拆分两行编排可行，但签名重复仍存在，不能据此宣称算法未去重。

### D05 — short_composition_and_signature

- [src/sqlseed/generators/_native_provider.py:67](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/_native_provider.py:67) ↔ [src/sqlseed/generators/base_provider.py:423](/Users/sunbo/Desktop/sqlseed/src/sqlseed/generators/base_provider.py:423)，12行检测窗口。

片段含四行日期/时间组合及 _gen_time 签名。两端保持 date draw → time bounds validation → time draw 次序；Base 还须先 _next_id，而 native 不计数。可继续抽取四行组合 helper，但这只减少很短的已共享 primitive 编排，无法消除必要的公开签名；需验证失败时 RNG/counter 次序。

### D06 — distinct_phase_signature

- [src/sqlseed/core/stream.py:558](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/stream.py:558) ↔ [src/sqlseed/core/stream.py:538](/Users/sunbo/Desktop/sqlseed/src/sqlseed/core/stream.py:538)，7行检测窗口。

DataStream._register_row_composites 与 _check_row_inequalities 参数相同，分别完成 UNIQUE 注册及独立采样列比较；共享 rollback 已提取 _rollback_row_constraints。检测片段只有签名/docstring，合并函数会重新混合职责。

### D07 — runtime_vs_test_imports

- [plugins/sqlseed-ai/src/sqlseed_ai/runtime.py:63](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/runtime.py:63) ↔ [plugins/sqlseed-ai/tests/healer/test_heal_orchestrator_real.py:17](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/tests/healer/test_heal_orchestrator_real.py:17)，7行检测窗口。

runtime.build_heal_orchestrator 的函数内 lazy imports 与真实 healer 组合测试 imports 重复。前者保护可选插件加载边界，后者直接构造组件以覆盖真实集成；把 imports 变为聚合转导出无业务去重收益。

### D08 — type_checking_vs_test_imports

- [plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py:33](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/orchestrator.py:33) ↔ [plugins/sqlseed-ai/tests/healer/test_heal_orchestrator_real.py:17](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/tests/healer/test_heal_orchestrator_real.py:17)，7行检测窗口。

healer.orchestrator 的 TYPE_CHECKING 类型依赖与真实集成测试运行时 imports 相同。类型检查与运行时职责不同；不为 token 克隆引入运行时依赖或改测试工厂。

### D09 — distinct_result_types_shared_tail

- [plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py:280](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/level2_column_healer.py:280) ↔ [plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py:129](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/healer/level3_compact_healer.py:129)，11行检测窗口。

Level2Result/Level3Result 分别保留 column/compact 级语义；片段横跨异常结果尾部（error、elapsed_seconds、prompt_tokens）和成功响应 elapsed/content/空响应判断。没有独立重复 LLM 调用或解析算法；通用结果工厂/基类会新增结果类型耦合，且需保留每级时钟采样与异常路由。

### D10 — 已修复 shared_cli_declarations

- [plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py:473](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py:473) ↔ [plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py:348](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py:348)，10行检测窗口。

此处记录原始位置。现已由 `_ai_model_options` 统一3个相同选项，按 Click 的逆序装饰保留显示和解析顺序，不包装callback；完整证据见 [D10修复结果](/tmp/sqlseed-ai-cli-options-result.json)。

### D11 — implementation_vs_typing_contract

- [plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:64](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:64) ↔ [plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_streaming.py:43](/Users/sunbo/Desktop/sqlseed/plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_streaming.py:43)，11行检测窗口。

LLMCallerMixin._log_llm_interaction 的真实签名与 StreamingHandlerMixin 的 TYPE_CHECKING host-method 声明重复。后者运行时不存在，提供 mixin 组合类型合同；提取统一 Protocol 是更大类型架构变更，不属于消除重复实现。

## 复核边界

- 保留代表静态建议不适用于当前合同或抽象收益不足，不代表代码永远不能改善。
- jscpd mild token窗口可跨函数边界；不能将11组都描述为纯签名，也不能将其都描述为11套重复业务算法。
- 本轮只读审阅没有重跑全仓lint/jscpd/pytest；已核对现有report路径、行号、源片段、AST handler和专门边界证据。

JSON 中含81处 source fragment/hash、证据来源及11组双侧完整片段，可逐项复审。
