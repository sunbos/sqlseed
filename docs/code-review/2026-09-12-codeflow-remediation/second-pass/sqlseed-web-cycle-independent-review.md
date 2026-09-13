# Web factory 循环解耦独立审阅

结论：未发现本次拆分或覆盖方法参数重命名引入的行为遗漏。只读审阅，不修改 source/tests/config，不提交或推送。

审阅范围：`plugins/sqlseed-web/src/sqlseed_web/app.py`、`_application.py`、`managed_worker.py`、`supervised_plugins.py`。已读取根、Web 包、Web source/tests 的 AGENTS，以及 ARCHITECTURE 中 Web 边界。

- 拆分前精确快照 `/tmp/sqlseed-app-before-factory-split.py` 中 6 个顶层函数，与新 `_application.py`/`app.py` 合并后的 AST 完全一致：4 个 middleware helpers、create_app、main。比较包含函数签名、内层 lifespan/route handlers、装饰器及所有语句顺序。工厂 imports 原序列也一致，仅 argparse 留在 console facade。
- `managed_worker.py` 相对推送提交 064854c9 的 AST，仅 lazy factory import 从 `sqlseed_web.app` 改为 `sqlseed_web._application`；其它 worker 流程完全相同。
- `sqlseed_web.app.create_app is sqlseed_web._application.create_app`；公开 `__all__` 为 create_app/main，factory 签名不变。`python -m sqlseed_web --help` 正常，未启动服务。
- `_STATIC_DIR` 仍是同一 package parent/static。四种 manage_plugins/supervised_worker 组合的路由排列、中间件排列与完整 OpenAPI 均相同。
- 160 个真实 TestClient 差分场景（4 模式 × 8 请求 × 5 origin/host/header 条件）中，status、body、headers 完全相同，包括 index/static/missing asset、health、管理状态、非法 AI 配置、跨域和 rebinding Host。差分使用明确传入的 ManagementService 边界实例，未启动真实监听或用户环境管理；下面的现有测试另外覆盖真实 lifespan 和 worker。
- `SupervisedPluginManager._run` 相对推送前实现，归一化 plan→operation_plan 后 AST 完全相同；与 `PluginManager._run` 的 inspect.signature 一致，并可通过 operation_plan/before 关键字绑定。

实际验证：

1. `pytest plugins/sqlseed-web/tests/test_web_request_security.py plugins/sqlseed-web/tests/test_supervisor.py plugins/sqlseed-web/tests/test_plugin_management.py::test_management_is_opt_in_and_normal_business_routes_remain_available plugins/sqlseed-web/tests/test_plugin_management.py::test_maintenance_rejects_all_business_apis -q`：13 passed，13.54s。
2. `pytest plugins/sqlseed-web/tests/test_supervised_plugins.py -q`：7 passed，0.77s。
3. `/tmp/sqlseed-web-cycle-review.py`：AST、公开 factory、4 模式结构、160 HTTP 差分全部通过。

真实 supervisor 测试使用 port=0、临时 SQLite 和隔离 metadata，验证业务→维护→业务进程替换、原端口与连接身份、原数据、用户安装 distribution 清单保持、父 IPC 断开后 worker 退出和环境锁释放；installer 仅为临时 metadata 边界，不安装包。未占用用户 8630、未改用户 settings/database/安装环境。唯一测试警告为依赖 Starlette 的 anyio BlockingPortal deprecation。

边界：本次没有重复全仓门禁、浏览器视觉或 Windows/POSIX 之外平台验证。工厂函数 `__module__` 自然变为私有实现模块，但已有公开导入路径和可调用对象保留；没有发现项目将原 app 模块的私有 helpers 或偶然导入名作为 API。调用参数和业务行为均按本次范围核验。

证据：`/tmp/sqlseed-web-cycle-review-result.json`、`/tmp/sqlseed-web-cycle-extra-review-result.json`、`/tmp/sqlseed-web-cycle-targeted-tests.log`、`/tmp/sqlseed-web-cycle-supervised-tests.log`。收尾核对测试时的三个工厂/worker文件 SHA256 与当前源码相同。
