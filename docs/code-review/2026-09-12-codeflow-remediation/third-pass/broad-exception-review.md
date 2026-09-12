# 53处 broad-exception-caught 独立复核

基线53项：1项Future已修，1项探针政策修正由root授权实施；2项metadata小设计经root评估暂不采用；14项更大领域设计不扩本轮范围；1项bytes政策变化不实施；34项暂未发现合理等价替代。

本轮只修改并冻结了 Web 的真实子进程锁测试，其余源码未改。基线是 ef7b279 对应本地报告中的53项；表中保留报告原行号，JSON另记所属函数及原函数SHA256。

## 可review的处理顺序

1. 已完成B35：标准Future承接测试线程结果，去掉手写异常列表。真实回归1 passed，Ruff/format与完整Pylint2.17.7通过。未使用executor context manager，finally释放子进程结束条件、Future等待有timeout；run_installer自身有10秒超时。
2. B19/B20是已评估的小设计候选，root决定暂不采用，当前额外私有异常与两个立即消费catch的收益有限。具体备选：一个共享metadata版本读取API明确区分未安装和记录不可读。PackageNotFoundError原样优先传播；未知普通异常转换为带original/cause的MetadataReadError；两个消费者保留原status/version/固定文本。无需改公共metadata API或依赖清单。
3. 14项较大候选按三种真实职责分别评审：候选数据库验证/修复尝试3项，Workspace运行日志5项，schema元数据6项。应先定义接口和旧异常范围矩阵，之后才实现。尤其不能把接口调用后的迭代、clock或payload错误误移出原保护范围，也不能丢失部分结果。
4. B07已由root授权修正测试政策：仅httpx缺失、RequestError或非200判不可用，意外错误应使测试失败；由root独占该文件并加HTTP边界回归，明确不主张等价。B08的bytes子类政策变化不实施。其余34项当前保留，原因逐项列出。

## 领域异常不是批量包装模板

本地读取Pylint2.17.7实现确认：except Exception中明确raise新领域异常不会触发W0718。/tmp的5项实验证明可保存original和__cause__，KeyboardInterrupt/SystemExit自然传播。这个事实只证明工具支持正常异常转换，不证明加包装层本身有架构价值。

可采用的接口必须被真实调用方依赖并表达领域失败种类；不能做capture(callable)后马上unwrap、在顶层生成入口把原整段包成GenerationFailure再立刻转回GenerationResult，或用Exception的别名/动态类/规则配置避开检查。需要原异常文本或类型的public_error/summarize_error必须明确消费original；不能让新的包装异常悄悄出现在旧public API。

## 标准库方案的边界

- [concurrent.futures官方文档](https://docs.python.org/3/library/concurrent.futures.html)：Future.result传递工作异常；Executor上下文退出会等待，shutdown(wait=False)也不能阻止解释器退出时等待线程。因此本次有界测试适用，具有daemon超时放弃合同的ExpressionEngine和后台任务不能直接替换。Future done callback不是可靠的BaseException传递合同。
- [contextlib官方文档](https://docs.python.org/3/library/contextlib.html)：ExitStack用于按顺序释放资源，普通callback不会抑制异常。把Exception判断写进__exit__或push回调仍是同一广泛抑制政策，不能以语法不同冒充职责改善；默认异常传播还可能遮蔽原失败。
- [HTTPX异常层级](https://www.python-httpx.org/exceptions/)适合网络失败合同，但不覆盖配置读取、模块导入、JSON或应用回调失败。
- [SQLAlchemy异常文档](https://docs.sqlalchemy.org/en/20/core/exceptions.html)提供SQLAlchemyError/StatementError等类型与原异常信息；当前try还覆盖Python值处理和可注入adapter，不能仅凭库名把捕获缩为SQLAlchemyError。

## 与audit协作：另3处LLM try-except-raise方案

这3处不属于上述53项。Level1/2/3可共享一个真正同步的LLM调用阶段，返回LLMCallOutcome(response,error,elapsed)。它统一请求执行、已知失败分类与计时，调用方保留自己的LevelResult、JSON规则和content读取。只有原(RuntimeError,AttributeError,ValueError)被转换成结果；用issubclass(type(exc), OSError)优先重新抛出OSError多继承异常，避免isinstance受异常__class__伪装影响。

失败分支必须在原exception活动上下文中执行failure_logger，然后读取clock；成功先clock，再由调用方在捕获区外访问response.choices/message/content。原异常对象直接保存在error并用is not None判断，避免falsy异常被当成功。logger/clock/callback异常继续传播，不能放进同一个新增广捕获。clock应显式传入当前monotonic，避免默认参数预绑定改变测试注入；原请求字段读取也应保留在原保护范围。该共享调用阶段可消除3处重复异常优先级及Level2/3生命周期尾部clone，无须新线程。方案已与audit对齐，尚未实施。

## 逐项结论

| ID | 原位置 | 分类 | 原合同与处理建议 |
| --- | --- | --- | --- |
| B01 | `examples/build_showcase_db.py:471` | 当前保留 | 逐表批处理必须记录任意生成失败并继续。 保留当前最外层报告边界；迁移pytest等执行器会改变示例输出与执行方式，单用Future无业务收益。  |
| B02 | `examples/order_workflow/run.py:231` | 当前保留 | 命令行入口把任意业务失败转成自定义非零退出诊断。 保留；删除捕获改默认traceback或全局excepthook会改变直接main调用、错误文本或全局状态。  |
| B03 | `plugins/sqlseed-ai/src/sqlseed_ai/analyzer/_caller.py:108` | 当前保留 | 附属LLM日志明确承诺失败返回None，不遮蔽响应或原始业务错误。 保留；IO异常清单不能覆盖时间/序列化/路径失败。新增只被此处使用的写日志异常包装层没有足够职责收益。  |
| B04 | `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:611` | 较大领域设计，本轮不实施 | 真实回滚INSERT把任意候选/反射/driver失败汇总，FK错误例外。 可另设计候选数据库验证边界，与B05共享反射操作；领域失败必须保存原异常供pgcode/message/summarize_error，不能只捕获SQLAlchemyError，rollback顺序不变。  |
| B05 | `plugins/sqlseed-ai/src/sqlseed_ai/refiner.py:687` | 较大领域设计，本轮不实施 | computed列反射失败允许依赖后续preview，不能转成最终通过。 与B04设计独立的候选schema反射契约；只捕获该领域失败，保留后续preview降级。单包Table调用仍不覆盖computed列迭代失败。  |
| B06 | `plugins/sqlseed-ai/src/sqlseed_ai/repair/executor.py:91` | 较大领域设计，本轮不实施 | 注入RepairFn、返回值转换与配置合并失败均计unfixable，继续下一列。 可另设计RepairAttempt/StrategyFailure接口，覆盖完整一次策略执行及应用；保存原异常、原顺序和现有部分修改行为。只包装外部函数仍漏dict(after)/AppliedFix失败。  |
| B07 | `plugins/sqlseed-ai/tests/healer/conftest.py:25` | Root授权修政策 | 真实LLM fixture将导入、HTTP及其他普通失败统一转不可用skip。 Root已授权并独占实施测试政策修正：httpx缺失、RequestError或非200返回False，其余意外异常传播并补HTTP边界回归。明确属于行为修复，不主张等价；本代理不改该文件。  |
| B08 | `plugins/sqlseed-web/src/sqlseed_web/api.py:166` | 需改政策 | bytes子类可重写decode并抛任意错误，现有fallback是repr(value)。 若产品明确wire bytes始终按底层内容显示，可用bytes.decode(value, errors="replace")并调整子类契约；当前不是等价改动。窄化异常同样改变fallback。  |
| B09 | `plugins/sqlseed-web/src/sqlseed_web/api.py:218` | 当前保留 | 任意生成/adapter/job成功发布错误都要写入脱敏失败终态。 保留最外层job失败隔离；Future会改变线程生命周期且结果仍需转换，ExitStack只负责清理不能自动生成原终态。  |
| B10 | `plugins/sqlseed-web/src/sqlseed_web/api.py:478` | 当前保留 | AI配置、HTTP和响应处理的任意普通失败都变成固定脱敏连通响应。 保留；仅用HTTPX RequestError不覆盖配置/响应错误。未来可统一B24的探针服务，但现有两种配置入口不同，不以加一层catch包装换零告警。  |
| B11 | `plugins/sqlseed-web/src/sqlseed_web/api.py:608` | 当前保留 | 活跃行数属于可丢失进度，连接关闭及任意adapter错误不使job查询失败。 保留；只做rowcount包装再立即降级没有独立职责收益。若未来统一只读进度API，应同时解决连接生命周期。  |
| B12 | `plugins/sqlseed-web/src/sqlseed_web/api.py:790` | 当前保留 | 配置文本通过临时文件加载；任意解析/配置/IO失败转valid=False，HTTPException原样抛出。 保留HTTP结果边界；可另做真正纯文本config parser消除临时文件，但仍需定义未知失败对API的策略，不能只列ValidationError/YAML异常。  |
| B13 | `plugins/sqlseed-web/src/sqlseed_web/api.py:875` | 当前保留 | heal_validate的任意snapshot/contract/validator失败都返回现有ok=False诊断。 保留入口的失败到响应转换；改变为HTTP500或只拦领域已知失败属于响应合同变化。  |
| B14 | `plugins/sqlseed-web/src/sqlseed_web/api.py:909` | 当前保留 | heal_repair的任意snapshot/pipeline失败都返回现有ok=False诊断。 保留，理由同B13；普通自定义repair策略可能抛出任意Exception。  |
| B15 | `plugins/sqlseed-web/src/sqlseed_web/api.py:1020` | 当前保留 | 后台auto-heal包含插件加载、认证、schema、LLM与终态发布，任意失败必须脱敏收尾。 保留任务所有者边界；拆职责不能消除最外层失败隔离政策，Future替换daemon工作线程不等价。  |
| B16 | `plugins/sqlseed-web/src/sqlseed_web/plugin_management.py:282` | 当前保留 | 安装任务包括临时目录/约束文件/子进程/metadata核验，失败仍发布最终task状态。 保留安装事务的最外层脱敏边界；缩窄为subprocess异常会漏文件/metadata/回调异常。  |
| B17 | `plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:48` | 当前保留 | 逐连接恢复可因插件/adapter失败，失败项记录并继续其他连接。 保留每项恢复隔离；显式连接资源管理可改善清理组织，但不能自动替代失败列表合同。  |
| B18 | `plugins/sqlseed-web/src/sqlseed_web/runtime_session.py:53` | 当前保留 | 恢复失败后的close异常是次要错误，不得遮蔽原恢复失败。 保留；ExitStack默认会传播或替换异常，__exit__中用isinstance(Exception)抑制只是另一种广捕获写法。  |
| B19 | `plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:186` | 设计已评估暂不采用 | metadata.version未知失败不证明包未安装，必须保留import_error状态。 推荐有界领域API：共享读取installed version，PackageNotFoundError原样传播，其余Exception raise MetadataReadError(original) from original；调用方仅捕获这两类。 Root评审决定暂不增加wrapper：新增私有异常与两个立即消费catch的当前收益有限。方案仅作已评估设计候选。 |
| B20 | `plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:235` | 设计已评估暂不采用 | metadata.version区分缺失与已安装但metadata不可读。 采用B19同一读取API，两个真实消费者共享“缺失/不可读”合同；原version/status与脱敏文本不变，BaseException继续传播。 Root评审决定暂不增加wrapper：新增私有异常与两个立即消费catch的当前收益有限。方案仅作已评估设计候选。 |
| B21 | `plugins/sqlseed-web/src/sqlseed_web/settings_environment.py:245` | 当前保留 | 任意可选模块import初始化或public contract错误均令能力不可用。 保留能力探测边界；ImportError不足以覆盖模块顶层代码失败，新的单用途ImportFailure包装没有额外收益。  |
| B22 | `plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:119` | 当前保留 | maintenance、安装及恢复前状态保存失败必须更新脱敏任务状态并尝试恢复服务。 保留维护任务边界；只用domain安装错误会漏controller/metadata/状态保存的任意错误。  |
| B23 | `plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:130` | 当前保留 | 恢复business本身任意错误必须明确标记recovery_failed/service_ready=False。 保留恢复结果边界；若允许异常直接逃逸，将无法可靠呈现服务不可用状态。  |
| B24 | `plugins/sqlseed-web/src/sqlseed_web/workbench_ai.py:194` | 当前保留 | backend探测含settings/密钥/HTTP/JSON/model形状，ImportError另有AI缺失响应。 保留；HTTPX网络层级不覆盖全流程。与B10统一探针需独立接口设计，不能通过盲加广域异常包装声称解决。  |
| B25 | `plugins/sqlseed-web/src/sqlseed_web/workbench_ai_stream.py:56` | 当前保留 | Analysis callable任意失败转流式终态事件，finally释放工作gate。 保留daemon任务的事件转换；标准TPE改变退出等待，Future callback的异常也不能可靠代替原线程异常传播与终态顺序。  |
| B26 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:698` | 当前保留 | 逐表preview任意provider/generator错误变成对应表issue，取消单独传播。 保留逐表验证结果边界；窄化会改变独立错误隔离，GenerationCancelled优先级不得丢失。  |
| B27 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:729` | 当前保留 | 整体生成检查的初始化/依赖/sample失败汇总validation_failed，取消保持原原因。 保留顶层检查结果边界；移到通用capture再立刻转回ValidationIssue只增加间接层。  |
| B28 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:920` | 较大领域设计，本轮不实施 | 启动失败后的次要持久化失败不得阻止complete_job，原启动异常继续抛出。 可设计RunJournal失败记录契约，与B29-B32共享；须连同time/public_error/payload构造的旧捕获范围保留，不能只包装store.update_run。  |
| B29 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1032` | 较大领域设计，本轮不实施 | snapshot读取失败后的失败记录也可能失败，仍必须释放job。 同RunJournal设计；只捕获JournalWriteError并保留原error、finally完成job。store=None和clock失败必须在差分矩阵覆盖。  |
| B30 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1120` | 较大领域设计，本轮不实施 | 终态持久化失败要追加原脱敏诊断并进行一次有界降级写入。 RunJournal可统一持久化失败种类，必须保存original给public_error；二次写入次数、已提交行数、终态error与finally完成job不变。  |
| B31 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1131` | 较大领域设计，本轮不实施 | 有界第二次终态写入失败仅记录日志，仍执行complete_job。 采用同一JournalWriteError，保留二次payload与clock在旧保护范围；不能采用自动无界retry或吞进程控制异常。  |
| B32 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1147` | 较大领域设计，本轮不实施 | get_store及get_run任意失败会走snapshot失败收尾。 RunJournal加载API需同时正规化初始化与读取失败；不得只把get_run换成包装器而漏get_store。其他public WorkspaceStore调用仍保持旧原异常合同。  |
| B33 | `plugins/sqlseed-web/src/sqlseed_web/workbench_runtime.py:1163` | 当前保留 | 工作任务执行任意异常均汇总，finally写终态；已commit不能误报rollback。 保留任务最外层边界，storage domain只改善子调用，不能覆盖任意插件/执行/发布失败。  |
| B34 | `plugins/sqlseed-web/src/sqlseed_web/worker_control.py:122` | 当前保留 | 跨进程RPC handler任意异常必须返回固定503，同时HTTPException/ControlError保留具体响应。 保留RPC信任边界；改为只捕获已知错误会泄漏细节或断开连接。未来统一RPC框架属于更大协议迁移。  |
| B35 | `plugins/sqlseed-web/tests/test_plugin_process.py:41` | 已修 | 手写线程结果/异常列表仅用于把worker错误带回测试主线程。 已用ThreadPoolExecutor/Future传递真实结果与原异常；finally先finish.touch解除子进程循环，再shutdown(wait=False)与result(timeout=15)，锁在独立finally释放。  |
| B36 | `scripts/complex_validation/ai_offline_validation.py:116` | 当前保留 | 验证harness把任意fill错误转(False,错误类型与文本)。 保留报告边界；转pytest参数化是有效未来测试迁移，但改变脚本调用接口与报告格式。  |
| B37 | `scripts/complex_validation/ai_offline_validation.py:421` | 当前保留 | MCP import初始化任意失败应记录该节失败并继续报告。 保留harness失败边界；只捕获ImportError会漏依赖初始化的RuntimeError等错误。  |
| B38 | `scripts/complex_validation/randomized_roundtrip.py:218` | 当前保留 | 随机roundtrip的逐表core生成错误要累积失败并继续。 保留独立案例报告边界；Future仅为了自动捕获而增加线程没有价值。  |
| B39 | `scripts/complex_validation/randomized_roundtrip.py:282` | 当前保留 | 随机AI roundtrip把任意fill错误转案例失败。 保留；若迁移为pytest须明确取代现有脚本的运行/聚合接口，不能声称输出完全相同。  |
| B40 | `scripts/complex_validation/repro_defects.py:71` | 当前保留 | 缺陷repro用crash文本保存任意失败的真实诊断。 保留诊断边界；删catch会提前中断复现报告。  |
| B41 | `scripts/complex_validation/repro_roundtrip.py:35` | 当前保留 | 单case的connect/fill/query错误输出FAIL，后续case继续。 保留；具体异常列表不能覆盖任意generator和driver。  |
| B42 | `scripts/complex_validation/run_validation.py:119` | 当前保留 | 复杂验证逐表错误存入映射，后续表继续。 保留聚合报告边界；与其他harness共用结果捕获仍需要同一广捕获，或改报告框架。  |
| B43 | `scripts/complex_validation/smoke_test.py:93` | 当前保留 | provider兼容性fill/query/检查任意失败要记该case失败。 保留报告边界；此处不是失败即成功，未知错误仍明确失败。  |
| B44 | `scripts/complex_validation/smoke_test.py:126` | 当前保留 | count=0仅ValueError算预期；其他任何Exception都明确算错误类型失败。 保留独立负例报告；仅删除广捕获会改变脚本继续能力，不能把pytest.raises(Exception)当改进。  |
| B45 | `scripts/complex_validation/smoke_test.py:133` | 当前保留 | count=1真实fill与rowcount任意错误均报告case失败。 保留逐例诊断边界，继续其他场景。  |
| B46 | `src/sqlseed/core/expression.py:224` | 当前保留 | daemon表达式线程把普通错误带回调用线程，超时可返回而不等长任务退出。 保留当前超时模型；标准TPE线程在解释器退出时被join且context退出会等任务，不是等价替代。Future本身不会执行或自动捕获；私有WorkItem/全局excepthook不采用。  |
| B47 | `src/sqlseed/core/features.py:333` | 较大领域设计，本轮不实施 | 可选SQLite DDL读取通过任意adapter/result协议，失败返回空DDL。 可设计SchemaMetadataReader负责执行、fetch和解码；须把整个结果消费纳入MetadataReadError，而非仅包装execute。  |
| B48 | `src/sqlseed/core/features.py:394` | 较大领域设计，本轮不实施 | 可选SQLite index谓词提取在后续失败时保留已读结果。 同SchemaMetadataReader设计，领域结果必须携带部分谓词或保持增量读取；全量列表后一次失败丢掉partial不等价。  |
| B49 | `src/sqlseed/core/orchestrator/_generation.py:413` | 当前保留 | 公开fill_table把操作失败转GenerationResult并保留已提交计数，参数与ConfigurationError另行传播。 保留现有真实生成结果边界；用新GenerationFailure包住整段再立即拆回Result只是语法绕行，逐个扩展边界正规化也不能覆盖其后任意操作失败。  |
| B50 | `src/sqlseed/core/orchestrator/_specs.py:508` | 较大领域设计，本轮不实施 | 可选CHECK比较提取失败保留此前匹配，由INSERT最终检查。 SchemaMetadataReader若扩展到CHECK消费/解析，可正规化失败并携partial；只包装get_check_constraints不能覆盖迭代/表达式访问/解析失败。  |
| B51 | `src/sqlseed/core/relation.py:230` | 较大领域设计，本轮不实施 | cycle-breaker的column metadata失败跳过本表，按输入顺序继续fallback。 共享SchemaMetadataReader列读取契约可有界消除此处；此原try仅包get_column_info，不能顺便把nullable_map消费纳入捕获改变错误范围。  |
| B52 | `src/sqlseed/core/relation.py:537` | 较大领域设计，本轮不实施 | nullable查找及column迭代的任意失败采用既有True fallback。 SchemaMetadataReader应提供nullable查询操作并正规化整个消费；保持未找到和读取失败的既有返回，不能扩大B51对应捕获范围。  |
| B53 | `src/sqlseed/core/relation.py:691` | 较大领域设计，本轮不实施 | NULL FK关联CHECK获取失败跳过可选修复，后续解析错误原样传播。 共享SchemaMetadataReader的CHECK读取可有界消除；只正规化原get_check_constraints调用，不能顺带吞掉for循环解析错误。  |

## 本地证据

`/tmp/sqlseed-broad-exception-review/`中保存修改前后Pylint、真实pytest、Future和领域异常探针及结果；`report.json`覆盖全部53项并记录分类计数。原始AST摘录另存`/tmp/sqlseed-broad-review-input.json`。探针只在/tmp创建，未安装到用户环境。
