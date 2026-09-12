# CodeFlow 整改与验证记录

目标分支：`codex/workbench-candidate`。远端基线：`5b0dd07231d7ed9fbc33f924087e1e9dda878100`。本记录中的本地结果不能替代推送后的 CodeFlow 报告。

## 范围与处理原则

用户要求按最佳实践尽可能消除错误、警告，避免依赖抑制注释。本轮修复实现、拆分复杂职责、复用资源管理与实际测试逻辑；没有增加规则排除或调高既有阈值。`.pylintrc` 将 `pyproject.toml` 中已经存在的项目政策适配给 CodeFlow 使用的 Pylint 2.17.7，并保留远端曾输出告警的 extension checkers；对应一致性测试防止配置漂移。ESLint 使用现代 JavaScript module 配置，保留 recommended 规则。

任务前用户已有的 `.sonarcloud.properties`、`docs/candidate-validation.md` 和其他无关设计文档不属于本次提交。AI orchestrator 和 Web runtime 中已有的局部清理在重构中保留。

## 扫描结果（第二轮修复，待远端复验）

| 检查 | 原始基线 | 第一轮推送 `064854c` | 第二轮本地 |
| --- | --- | --- | --- |
| CodeFlow 远端总数 | 45 errors + 1987 warnings | 338 errors + 531 warnings | 待推送复验 |
| ESLint 8.57.1 | 37 个 error，具体文本不可读 | 0 errors / 0 warnings | JS 未再修改 |
| Pylint 2.17.7 | 8 errors + 1837 warnings | 338 errors + 511 warnings | 0 errors，81 条提示 |
| jscpd 4.0.5 | 75 组 / 150 条 | 10 组 / 20 条 | 10 组，110 行，0.13% |

原报告的 1995 条 Python/jscpd 明细已完整采集；另外 37 个 ESLint 报告公开接口返回空 message/source，因此不推断其具体错误文本。第一轮新报告也已完整采集：281 个 report IDs、270 个文件路径、869 条诊断，逐文件、工具及提交计数一致，详见 [第二轮远端报告](second-pass/sqlseed-codeflow-postpush-summary.md)。

第一轮配置生效后，远端报告了此前未出现的 368 条赋值表达式建议、329 条依赖导入错误及其他格式/包上下文提示。第二轮本地的 81 已使用 **`.pylintrc` 所有启用规则** 扫描，不再仅追踪原报告规则。远端设置与导入上下文仍须以第二次推送结果核对，不能先把本地结果当作远端结果。

81 条提示分别为：53 条 broad-exception-caught、13 条 unidiomatic-typecheck、10 条 use-set-for-membership、3 条 try-except-raise、2 条 consider-using-with。逐项审阅涉及顶层错误转换、线程资源所有权、精确类型契约和允许不可哈希输入的成员判断；未按会破坏合同的建议机械改写。相关说明位于 `evidence/` 的 boundary review 和 retained membership 文件。jscpd 余项主要为明确参数签名、导入、TYPE_CHECKING 声明和不同结果类型的收尾代码；重复并不都构成缺陷，仍保留计数以供审核。

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

## 验证

- 最终完整 pytest：**3374 passed，47 skipped**，503.98 秒；将 ResourceWarning 和 PytestUnraisableExceptionWarning 提升为错误。
- Web Node：**666 passed，0 skipped**。
- Ruff check、414 文件 format check、155 source files 的 mypy、3 项 import-linter contracts 和生成文档标记检查全部通过；architecture/doc-sync 包含在最终完整 pytest 中。
- 五包 sdist → wheel 构建、10 个发行产物 twine strict、完整与 core + Web 最小非 editable 安装、pip check、源码目录外的实际 wheel smoke、MkDocs strict 全部通过。
- 第二轮重建的 sdist、wheel 和已安装 payload 共 217 个文件逐字节一致，明确包含新的 `_application.py`；旧产物与证据保持不变。
- 发行验证使用临时 Python 3.12 环境；macOS x86_64 缺少 cryptography 50.0.1 的上游 wheel，使用现有同版本构建缓存完成 CI 锁版本安装，未更改任何依赖版本或仓库清单。用户主环境和 8630 服务保持原状。
- 独立审阅覆盖 Core、provider、Web、AI 与脚本。AI 原始单体到当前模块通过 14,000 个跨列变体、2,434 个完整 run 变体；最终 ANY 补丁通过 14,029 个数值边界复核，接受值通过 YAML 往返。审阅发现的数值精度及可选导入问题已修复并重新验证。

完整命令和日志在 `evidence/verification-summary.json` 及同目录证据中。

## 未通过与未覆盖的验证

最终 `make mutmut` 在隔离源码副本中完成：**236 个变异，228 killed、8 survived，退出码 2**，因此 mutation gate 尚未通过。8 项变异 diff 与第一轮 240 个变异中的 8 项逐条相同，没有新增幸存类别。6 项改变诊断/日志文案，另外 2 项改变采样容量系数或相等边界的合法采样策略；它们不是严格等价变异。810 次独立参数核验没有发现约束违例，详见 [mutation 审阅](second-pass/sqlseed-codeflow-mutation-postpush-review.md)。不通过精确锁定日志全文的自证测试制造通过结果。

真实 PostgreSQL/Docker、真实 LLM 和缺少 API key 的测试未执行，部分可选依赖测试跳过。`examples/scenario_lab/test_fixture.py` 的一个三列外键边界集成用例在原始 HEAD 和当前版本都失败，已确认属于既有问题，且不在默认 pytest 收集范围；本轮没有放宽数据库边界来掩盖它。

## 远端状态

第一轮 `064854c9c90a9b890e58a314fbe5d8fba69d1508` 已推送并采集完整 CodeFlow 结果。第二轮源码已完成回归及独立审阅，待推送后复验。不得将上述本地改善描述为远端所有警告已清零。

基线 PR CI 的 Python 3.12 测试实际通过（3306 passed、22 skipped）；该 job 因 Codecov 上传返回 `Repository not found` 而失败，与测试断言无关，详见 `evidence/sqlseed-baseline-ci-review.json`。

第一轮推送的 CI `34694082379` 中 lint、packages、integration、property、Python 3.10/3.13、macOS 和 Windows job 均成功；Python 3.12 job 仍在 Codecov 上传阶段返回同一 `Repository not found`。本任务不更改用户已有的 SonarCloud 配置或第三方账号设置。
