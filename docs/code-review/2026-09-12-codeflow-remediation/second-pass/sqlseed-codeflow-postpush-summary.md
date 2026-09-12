# CodeFlow 新提交全量诊断核对

提交：`064854c9c90a9b890e58a314fbe5d8fba69d1508`。

采集 **281 个 report IDs / 270 个文件路径 / 869 条诊断**；**338 errors + 531 warnings** 与远端提交、rawReports、所有逐文件报告、commonIssues 的 16 规则计数全部一致。0 抓取失败，0 数量不符。

Pylint 2.17.7：338 errors + 511 warnings；jscpd 4.0.5：20 warnings（10 组文件对）；ESLint 8.57.1：0。版本来自 rawReports，逐条接口的 toolVersion 为 null，按原值保留。

## 规则计数

| 规则 | 本次 | 原远端基线 | 判断 |
|---|---:|---:|---|
| `consider-using-assignment-expr` | 368 | 0 | 本次启用的 code_style checker 报告建议；旧基线无此规则。不能仅凭报告推断旧 runner 的 py-version 或默认禁用配置。 |
| `import-error` | 329 | 0 | 分析环境无法解析导入；需核对依赖安装和 runner 路径，不能仅凭报告断言源码有错。 |
| `broad-exception-caught` | 53 | 53 | 与推送前本地已逐项审阅的保留项数量一致。 |
| `line-too-long` | 51 | 0 | 新报告中出现，消息含实际长度/阈值；完整位置均在 JSON。 |
| `CodeDuplication` | 20 | 150 | 20 个文件端告警，对应 10 组重复；完整 message 含另一端位置。 |
| `unidiomatic-typecheck` | 13 | 13 | 与推送前本地已逐项审阅的保留项数量一致。 |
| `use-set-for-membership` | 10 | 61 | 与推送前本地已逐项审阅的保留项数量一致。 |
| `relative-beyond-top-level` | 9 | 0 | 9 处相对导入的包上下文未识别；需按测试/脚本实际执行模式核实。 |
| `superfluous-parens` | 5 | 0 | 5 处括号格式建议。 |
| `try-except-raise` | 3 | 3 | 与推送前本地已逐项审阅的保留项数量一致。 |
| `consider-using-with` | 2 | 2 | 与推送前本地已逐项审阅的保留项数量一致。 |
| `missing-final-newline` | 2 | 0 | 2 处末尾换行格式建议。 |
| `arguments-renamed` | 1 | 0 | 覆盖方法参数名不同；需按父类调用约定核实。 |
| `cyclic-import` | 1 | 0 | 报告含 app→supervisor→managed_worker 路径；需区分实际运行与 lazy import 的静态循环。 |
| `consider-using-namedtuple-or-dataclass` | 1 | 0 | 1 处字典值的数据结构建议；不能仅为降告警改接口。 |
| `consider-using-enumerate` | 1 | 0 | 1 处迭代索引建议，核实等价后可整理。 |

五类已保留规则合计仍为 81：broad exception 53、精确 type 判断 13、不可 hash 输入相关 membership 10、异常优先级 try-except-raise 3、手动资源生命周期 with 建议 2。原逐项合同理由见已有 retained/boundary review；本报告仅核对计数，不替代逐行复审。

## 导入错误分布

329 条 import-error 涉及以下顶层模块。多数是项目已声明依赖或测试依赖，也有平台专属模块；接口没有提供环境安装日志，因此不能把所有错误直接归因为缺包。

| 顶层模块 | 数量 |
|---|---:|
| `pytest` | 157 |
| `fastapi` | 53 |
| `sqlalchemy` | 45 |
| `click` | 16 |
| `httpx` | 12 |
| `openai` | 7 |
| `docker` | 5 |
| `requests` | 4 |
| `sqlglot` | 4 |
| `pywintypes` | 3 |
| `simpleeval` | 3 |
| `structlog` | 3 |
| `pluggy` | 3 |
| `testcontainers` | 2 |
| `hypothesis` | 2 |
| `uvicorn` | 2 |
| `starlette` | 2 |
| `faker` | 2 |
| `winerror` | 1 |
| `mcp` | 1 |
| `msvcrt` | 1 |
| `rstr` | 1 |

## 其它新增小规则的完整位置

| 规则 | 文件:行 | 原始消息 |
|---|---|---|
| `arguments-renamed` | `plugins/sqlseed-web/src/sqlseed_web/supervised_plugins.py:104` | Parameter 'operation_plan' has been renamed to 'plan' in overriding 'SupervisedPluginManager._run' method |
| `cyclic-import` | `plugins/sqlseed-web/src/sqlseed_web/worker_control.py:1` | Cyclic import (sqlseed_web.app -> sqlseed_web.supervisor -> sqlseed_web.managed_worker) |
| `relative-beyond-top-level` | `plugins/sqlseed-web/tests/test_workbench_acceptance.py:16` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `plugins/sqlseed-web/tests/test_workbench_ai.py:22` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `plugins/sqlseed-web/tests/test_workbench_ai_relations.py:22` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `plugins/sqlseed-web/tests/test_workbench_runtime.py:15` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `scripts/complex_validation/ai_offline_validation.py:32` | Attempted relative import beyond top-level package |
| `missing-final-newline` | `scripts/complex_validation/randomized_roundtrip.py:343` | Final newline missing |
| `relative-beyond-top-level` | `scripts/complex_validation/randomized_roundtrip.py:29` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `scripts/complex_validation/randomized_roundtrip.py:30` | Attempted relative import beyond top-level package |
| `consider-using-namedtuple-or-dataclass` | `scripts/complex_validation/randomized_roundtrip.py:54` | Consider using namedtuple or dataclass for dictionary values |
| `consider-using-enumerate` | `scripts/complex_validation/randomized_roundtrip.py:153` | Consider using enumerate instead of iterating with range and len |
| `missing-final-newline` | `scripts/complex_validation/repro_roundtrip.py:43` | Final newline missing |
| `relative-beyond-top-level` | `scripts/complex_validation/run_validation.py:27` | Attempted relative import beyond top-level package |
| `relative-beyond-top-level` | `scripts/complex_validation/smoke_test.py:24` | Attempted relative import beyond top-level package |
| `superfluous-parens` | `src/sqlseed/core/check_adapt.py:116` | Unnecessary parens after '=' keyword |
| `superfluous-parens` | `src/sqlseed/core/stream.py:79` | Unnecessary parens after 'not' keyword |
| `superfluous-parens` | `src/sqlseed/core/stream.py:81` | Unnecessary parens after 'not' keyword |
| `superfluous-parens` | `src/sqlseed/core/stream.py:83` | Unnecessary parens after 'not' keyword |
| `superfluous-parens` | `src/sqlseed/core/stream.py:84` | Unnecessary parens after 'not' keyword |

## 采集方法和边界

- 公共 GraphQL `https://api.getcodeflow.com/v2`，逐 `commitFileIssues`，`vcs=2`、`onlyNew=false`；读取指定提交，无任何写 API。
- `fileIds` 只覆盖 270 个 ID；合并 `reports.id` 得到 281 个，保留同文件不同工具报告，不按路径误去重。每条诊断附 `report_id`。
- 通过 curl + GraphQL aliases，每批 8 个报告、2 并发；保留成功缓存，超时有限重试。
- 官方 query 的 `options` union 在 jscpd 上报运行时类型解析错误，故去除此附加字段；`line/column/endLine/endColumn/isError/message/new/nodeType/ruleId/severity/tool/toolVersion` 均完整采集。未请求不必要的 source 正文。
- 原始服务端 `new` 字段原样保留，不用于判断代码改动是否新增告警。
- 只写 `/tmp` 中采集与汇总产物，没有修改源码、配置、测试、提交或推送。

产物：`/tmp/sqlseed-codeflow-postpush-all-issues.json`、`/tmp/sqlseed-codeflow-postpush-summary.json`、逐报告缓存 `/tmp/sqlseed-codeflow-postpush-files/`。
