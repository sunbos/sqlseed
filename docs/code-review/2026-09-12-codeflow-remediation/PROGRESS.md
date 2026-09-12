# CodeFlow 整改与验证记录

目标分支：`codex/workbench-candidate`。远端基线：`5b0dd07231d7ed9fbc33f924087e1e9dda878100`。本记录中的本地结果不能替代推送后的 CodeFlow 报告。

## 范围与处理原则

用户要求按最佳实践尽可能消除错误、警告，避免依赖抑制注释。本轮修复实现、拆分复杂职责、复用资源管理与实际测试逻辑；没有增加规则排除或调高既有阈值。`.pylintrc` 将 `pyproject.toml` 中已经存在的项目政策适配给 CodeFlow 使用的 Pylint 2.17.7，并保留远端曾输出告警的 extension checkers；对应一致性测试防止配置漂移。ESLint 使用现代 JavaScript module 配置，保留 recommended 规则。

任务前用户已有的 `.sonarcloud.properties`、`docs/candidate-validation.md` 和其他无关设计文档不属于本次提交。AI orchestrator 和 Web runtime 中已有的局部清理在重构中保留。

## 扫描结果（最终源码远端复验）

| 检查 | 原始基线 | 第一轮 `064854c` | 第二轮 `ef7b279` | 最终源码 `218ab14` |
| --- | --- | --- | --- | --- |
| CodeFlow 远端总数 | 45 errors + 1987 warnings | 338 errors + 531 warnings | 0 errors + 101 warnings | **0 errors + 88 warnings** |
| ESLint 8.57.1 | 37 个 error，具体文本不可读 | 0 errors / 0 warnings | 0 errors / 0 warnings | 0 errors / 0 warnings |
| Pylint 2.17.7 | 8 errors + 1837 warnings | 338 errors + 511 warnings | 0 errors，81 条提示 | 0 errors，74 条提示 |
| jscpd 4.0.5 | 75 组 / 150 条 | 10 组 / 20 条 | 10 组 / 20 条 | 7 组 / 14 条 |

原报告的 1995 条 Python/jscpd 明细已完整采集；另外 37 个 ESLint 报告公开接口返回空 message/source，因此不推断其具体错误文本。第一轮新报告也已完整采集：281 个 report IDs、270 个文件路径、869 条诊断，逐文件、工具及提交计数一致，详见 [第二轮远端报告](second-pass/sqlseed-codeflow-postpush-summary.md)。

第一轮配置生效后，远端报告了此前未出现的 368 条赋值表达式建议、329 条依赖导入错误及其他格式/包上下文提示。第二轮本地的 81 已使用 **`.pylintrc` 所有启用规则** 扫描，不再仅追踪原报告规则。远端设置与导入上下文仍须以第二次推送结果核对，不能先把本地结果当作远端结果。

第二轮推送 `ef7b2795370873c915b9d1c9b50b59c6ac7016fb` 的 3 个远端分析全部完成：50 个报告、101 条 warning、0 errors。已补全接口截断的 2 条诊断，81 条 Pylint 的文件、行号、规则和消息与本地逐项完全一致；ESLint 无诊断，jscpd 仍为 10 组。计数改善不是通过调高阈值、禁用新增规则或添加抑制注释取得。

第二轮的 81 条提示分别为：53 条 broad-exception-caught、13 条 unidiomatic-typecheck、10 条 use-set-for-membership、3 条 try-except-raise、2 条 consider-using-with。逐项审阅涉及顶层错误转换、线程资源所有权、精确类型契约和允许不可哈希输入的成员判断；未按会破坏合同的建议机械改写。相关说明位于 `evidence/` 的 boundary review 和 retained membership 文件。jscpd 余项主要为明确参数签名、导入、TYPE_CHECKING 声明和不同结果类型的收尾代码；重复并不都构成缺陷，仍保留计数以供审核。

## 实际修复

- 消除 fixture factory 名称遮蔽，保留 fixture 对外名字、scope、依赖与 teardown；清理无用变量、重复导入和不明确的内部名字。
- 通过真实 SQLite connection helper 明确提交、回滚和关闭；通过类型保留的空集合断言 helper 复用测试契约。
- 拆分 Core CHECK/schema/mapper/FK/DAG/stream/UNIQUE/编排/adapter 复杂函数；保持流式生成、seed、异常边界和数据库约束。
- Native provider 共享数值与日期生成逻辑，保持 public signatures、RNG/native fallback 和计数行为。
- AI CHECK 推断独立成单列和跨列模块，拆分自动修复阶段及非自动修复入口；新增 ANY 数值边界回归，拒绝会溢出、下溢或丢失十进制精度的浮点转换。
- 拆分 Web 运行时、AI、安装流程、middleware、store 和执行逻辑；提取实际重复的前端草稿处理及测试 setup。
- AI CLI 的三个相同 Click 选项统一声明，216 组参数/环境变量/default_map 解析对照、签名/help/元数据完全一致，最后 32 项相关测试通过。
- 提取 CLI、验证脚本和示例重复逻辑；脚本只把预期 ValueError/IntegrityError 当作边界测试成功，避免其他内部异常被误报为成功。
- 保持可选插件只在顶层缺失时跳过测试；插件已安装但内部模块导入失败时继续报错。

## 第二轮修复

- 为五个 source roots、pytest importlib namespace 和直接执行的脚本提供明确分析路径；为两个脚本目录补上包标记，修复相对导入上下文。仅标明 29 个有 manifest/CI-lock 或 Windows stdlib 依据的外部模块可能不可用，内部缺失模块仍报错；4 个配置回归测试防止误屏蔽内部导入和路径漂移。
- 处理全部 368 条赋值表达式建议，同时直接内联 28 个只用于条件的临时变量。独立审阅核验求值顺序、短路、87 个文件和 1,741 个作用域；显式 union 注解保留，未改变 closure/nonlocal 绑定。
- 修复 51 条超长行、末尾换行及多余括号。长正则拆分暴露了文档校验器按源码行计数的问题，已改为 AST 读取完整字符串字面量，并添加先失败后通过的回归测试；29 个 regex 值和顺序保持一致。
- 验证脚本的列目录改用私有 NamedTuple，索引迭代改用 enumerate；1,000 个 seed 的表、列、外键和 RNG 序列与旧版一致。
- 将 Web application factory 移入 `_application.py`，保留 `app.create_app` 和 CLI 入口，消除静态循环依赖；修正派生方法的参数名，与父类关键字调用一致。独立对照了 4 种应用模式、160 个 HTTP 响应及真实临时端口 worker。
- Expression worker 使用 `list[Exception]` 传递已捕获错误，消除 optional sentinel 的推断歧义；真实线程对照保持异常对象 identity、falsy 异常、超时及 BaseException 行为。

第二轮完整验证和源码 hash 见 [verification-summary.json](second-pass/verification-summary.json)，当前位置和逐项保留理由见 [retained-findings-current.json](second-pass/retained-findings-current.json)。旧 `evidence/` 保留第一轮历史，第二轮证据独立存于 `second-pass/`。

## 第三轮：进一步复用与测试质量修复

没有把第二轮保留项直接视为全部不可改。再次独立审阅后完成以下改善：

- Web 子进程锁测试使用标准 Future 传递线程结果和原异常，删除手写异常列表及对应抑制注释；结束条件、15 秒等待上限和锁释放保持明确。
- 两处 stream 异常测试使用 pytest 的 `ExceptionInfo.type`，仍验证精确异常类型。
- LLM 可达性探针只将缺少顶层 HTTP 库、连接类失败和非 200 响应视为不可用；自身编程错误不再伪装成环境缺失而跳过测试。新增 5 项 HTTP 探针回归，修复前其中 2 项失败；没有模拟真实 LLM 响应。
- 三级 healer 共享同步 RPC 失败分类和计时，通过延迟请求保留参数求值的捕获范围，网络错误优先传播，结果携带原异常对象；不同级别的响应解析仍独立。28 项边界测试、101 项 healer 测试及 45 组独立旧新差分通过，6 个依赖 LM Studio 的用例跳过。
- Analyzer 的两个 mixin 共享实际日志实现，删除仅用于类型检查的重复假方法；方法签名、全局变量解析及既有 MRO 方法选择保持不变。87 项调用、流式和缓存路径测试通过。
- 受影响行数和原子事务测试共用 schema 建立与 adapter 关闭逻辑，由两份 yield fixture 管理；7 个用例的 SQL 和断言主体 AST 不变，整个数据库目录 337 passed、1 个 Docker 用例 skipped。

第三轮全仓本地检查为 **0 errors、74 条 Pylint 提示**，jscpd 为 **7 组、75 行、0.09%**。推送 `218ab14db47dcbc9c9a450f8d6b0e6d233854fac` 后，3 个远端分析全部完成：**0 errors、88 warnings**，38 个报告、88 条完整消息无截断；74 条 Pylint 的位置、规则和消息与本地完全一致，jscpd 为 14 条文件端提示。见 [远端原始明细](third-pass/remote-issues.json) 和 [计数核对](third-pass/remote-summary.json)。

其余 74 条分别是 51 条顶层/可选能力异常边界、11 条精确类型合同、10 条保留不可哈希输入语义的成员判断、2 条手工资源所有权提示；逐项位置和理由见 [最新清单](third-pass/retained-findings-current.json)。剩余 clone 涉及明确的 generator 签名、两阶段流式状态传递和运行时/类型声明的组件依赖，未用动态签名或单用途包装层换取计数下降。

最新验证与独立审阅见 `third-pass/`。更大的领域异常层、进程所有者重构等方案已评估；目前没有足够的行为或维护收益来证明应为静态提示实施这些架构变更。未新增规则禁用、提高阈值或添加逐行抑制。

## 验证

- 最终完整 pytest：**3412 passed，47 skipped**，308.66 秒；将 ResourceWarning 和 PytestUnraisableExceptionWarning 提升为错误。
- Web Node：**666 passed，0 skipped**。
- Ruff check、417 文件 format check、156 source files 的 mypy、3 项 import-linter contracts 和生成文档标记检查全部通过；architecture/doc-sync 包含在最终完整 pytest 中。
- 五包 sdist → wheel 构建、10 个发行产物 twine strict、完整与 core + Web 最小非 editable 安装、pip check、源码目录外的实际 wheel smoke、MkDocs strict 全部通过。
- 第三轮重建的 sdist、wheel 和已安装 payload 共 218 个文件逐字节一致，明确包含新的 `_application.py` 和 `_llm_call.py`；旧两轮产物与证据保持不变。
- 发行验证使用临时 Python 3.12 环境；macOS x86_64 缺少 cryptography 50.0.1 的上游 wheel，使用现有同版本构建缓存完成 CI 锁版本安装，未更改任何依赖版本或仓库清单。用户主环境和 8630 服务保持原状。
- 独立审阅覆盖 Core、provider、Web、AI 与脚本。AI 原始单体到当前模块通过 14,000 个跨列变体、2,434 个完整 run 变体；最终 ANY 补丁通过 14,029 个数值边界复核，接受值通过 YAML 往返。审阅发现的数值精度及可选导入问题已修复并重新验证。

第一轮命令和日志在 `evidence/verification-summary.json`；后续完整验证以 [第三轮验证摘要](third-pass/verification-summary.json) 及同目录证据为准。

## 未通过与未覆盖的验证

最终 `make mutmut` 在隔离源码副本中完成：**236 个变异，228 killed、8 survived，退出码 2**，因此 mutation gate 尚未通过。8 项变异 diff 与第一轮 240 个变异中的 8 项逐条相同，没有新增幸存类别。6 项改变诊断/日志文案，另外 2 项改变采样容量系数或相等边界的合法采样策略；它们不是严格等价变异。810 次独立参数核验没有发现约束违例，详见 [mutation 审阅](second-pass/sqlseed-codeflow-mutation-postpush-review.md)。不通过精确锁定日志全文的自证测试制造通过结果。

最终完整测试中的 `tests/integration/test_ai_real_llm.py` 7 个真实 LLM 用例均通过。真实 PostgreSQL/Docker、要求 LM Studio 的 6 个 healer 用例、缺少 API key 及 Pillow 的测试跳过；跳过原因保留在完整日志中。`examples/scenario_lab/test_fixture.py` 的一个三列外键边界集成用例在原始 HEAD 和当前版本都失败，已确认属于既有问题，且不在默认 pytest 收集范围；本轮没有放宽数据库边界来掩盖它。

## 远端状态

三轮源码均已推送并采集完整 CodeFlow 结果。最终源码提交为 `218ab14db47dcbc9c9a450f8d6b0e6d233854fac`；后续仅补充验证记录。远端 errors 已清零，warnings 保留 88 条，不能将其描述为所有告警清零。

基线 PR CI 的 Python 3.12 测试实际通过（3306 passed、22 skipped）；该 job 因 Codecov 上传返回 `Repository not found` 而失败，与测试断言无关，详见 `evidence/sqlseed-baseline-ci-review.json`。

第一轮推送的 CI `34694082379` 中 lint、packages、integration、property、Python 3.10/3.13、macOS 和 Windows job 均成功；Python 3.12 job 仍在 Codecov 上传阶段返回同一 `Repository not found`。本任务不更改用户已有的 SonarCloud 配置或第三方账号设置。

第二轮 CI `34700401559` 的上述 8 个 job 同样成功，独立 doc-sync `34700401558` 成功；Python 3.12 job 仍仅在 Codecov 上传阶段失败，服务返回同一 `Repository not found`。

最终源码 CI `34705230507` 中 lint、packages、integration、property、Python 3.10/3.13、macOS、Windows 共 8 个 job 全部成功，doc-sync `34705230488` 成功。唯一失败仍是 Python 3.12 job 的 Codecov 上传阶段，返回 `Repository not found`；见 [CI 核对](third-pass/ci-review.json)。
