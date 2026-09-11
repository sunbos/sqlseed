# DataOrchestrator 编排边界

`DataOrchestrator` 是多个 mixin 组成的 package，通过 `from sqlseed.core.orchestrator import DataOrchestrator` 导入。不要恢复单文件实现，也不要把其他 mixin 的职责堆进 generation。

## 职责分配

| 文件 | 修改范围 |
| --- | --- |
| [_common.py](_common.py) | `CoreCtx`、`ExtCtx` shared dataclasses 与 `_is_db_url()`；不是 mixin |
| [_connection.py](_connection.py) | `ConnectionMixin`：初始化、adapter 创建、属性、连接与关闭、context manager、`from_config()` |
| [_specs.py](_specs.py) | `SpecResolverMixin`：配置解析、CHECK adaptation、mapping、enrichment、UNIQUE/FK、AI hook/template pool、stream 构造 |
| [_generation.py](_generation.py) | `GenerationMixin`：`fill_table()`、`preview_table()`、batch 写入、自引用 FK 第二阶段；`fill` 是 alias |
| [_query.py](_query.py) | `QueryMixin`：schema/mapping 查询、报告、table order、`execute/query/fetch_one` |
| [__init__.py](__init__.py) | 组合 mixin 并暴露 `DataOrchestrator` |

## 生命周期与写入

- 共享状态存放在 `self._core` / `self._ext`，经 `_connection.py` 的属性访问。新 mixin 依赖同步维护 `TYPE_CHECKING` 下的 host interface 声明。
- DB 操作前确保 `_ensure_connected()`，使用 adapter 而非旁路创建连接；表操作保留 `validate_table_name()`。
- `_preflight_generation(table_names)` 在任何请求表清空/写入前验证所有名称、表存在性及 FK 支持边界；不得把缺表的空 FK metadata 当作可执行表。`fill_table` 单表和 `fill_from_config` 全表调用它，preview 在 spec 解析前校验 FK。不支持的 FK 抛 `ConfigurationError`；单表缺表/运行时 DB 错误仍进入 `GenerationResult.errors`，多表预检失败直接抛出并阻止整个循环。多表插件若自行清空/循环写入，也必须在首次副作用前调用该预检。预检不代表整个生成事务原子提交。
- 预检返回请求名称到 catalog 名称的映射；SQLite 仅折叠 ASCII 大小写，生成、FK pool 和多表拓扑排序使用 catalog 身份，PostgreSQL 保持精确匹配。配置中同一表的多个大小写别名在首次写入前拒绝。
- 公开 `get_topological_table_order()` 用同一 catalog 身份排序，但返回调用方请求的名称拼写；不能让 adapter 规范化的 FK 与未规范化的请求名称错失依赖边。
- `_ensure_connected()` 加载插件 hook 后再装载用户 custom mappings；保留用户规则优先级。
- 请求的 provider 不可用时，当前实现会直接降级到 `base` 并更新 registry default；不是自动逐级尝试 mimesis → faker → base。locale 无效时使用该 provider 的安全默认值。
- provider 仅由 `DataStream` 播种；表达式与 self-FK 后处理使用本次 seed 的独立 RNG，不写全局 random。沿 batch iterator 写入，保留 before/after insert hook、metrics、progress 的现有顺序。
- `fill_table(progress=...)` 接收调用方管理生命周期的 `ProgressBackend`；默认 `None` 由 core 创建并关闭 backend，MCP 等调用方可传 `NullProgressBackend`。
- `fill_table()` 无论成功或失败都在 `finally` 中调用 `restore_settings()` 恢复优化设置；生产异常使用 `sqlalchemy.exc.*`，不以 `sqlite3.*` 替代。
- `GenerationResult.errors` 表达 fill 失败；不要把捕获的异常变成成功结果。只对可忽略的辅助操作使用 `contextlib.suppress()`。
- `SQLAlchemyAdapter.batch_insert()` 的事务覆盖单次调用；fill 会多次调用它，不要宣称整个 fill 原子提交。

## spec 顺序与 CHECK hard truth

- `_resolve_specs()` 保留顺序：schema → 用户 CHECK clamp → mapping → enrichment/schema fallback → UNIQUE adjustment → 单列 FK → composite FK → composite PK 修正。
- 用户 source params 与单列 literal CHECK 相交则 clamp 并提示，无交集则 `ConfigurationError`；不替用户猜跨列或 OR 关系。
- 非 user-configured 且非 `skip` 的 spec 遇到单列 `CHECK IN (...)`，应以 CHECK enum 为准，包括 `title → sentence` 等名称命中，以及值集合不一致的 `choice`。
- 非 user-configured `phone`/`string` 遇到 `LENGTH(col) = N`，升级为 `pattern`、`regex: [0-9]{N}`；已有 `string.charset` 的例外保留。provider 的 locale phone 格式不能保证长度。
- zero-config boundary notice 排除已识别的 enum 与 exact-length CHECK；不要提示这些已处理约束仍需 AI。
- composite PK 中无自增默认值的 INTEGER 列不能沿用单列 INTEGER PK 的 `skip`；保留已解析的 FK spec。
- `_build_stream()` 将已支持的跨列比较 CHECK 转成 `inequality_constraints`；DAG、composite UNIQUE、CHECK 重试约束必须一起传入 stream。
- `_prepare_specs()` 通过 hook 应用 AI suggestions；核心不直接 import `sqlseed_ai`。用户显式配置列需继续受到保护。

## 自引用 FK

- 仅引擎因空父表自动把可空 self-ref FK 设为 `null_ratio=1.0` 的 spec 标记为延后关联；显式全 NULL 与追加到非空表不能触发第二阶段。生成完成后 `_post_fill_self_ref_fks()` 再关联已生成 PK，并同步相关条件列以满足 CHECK。
- 自引用第二阶段使用本次 seed 的独立 `random.Random`，不得重播种 provider 或全局 RNG；seed=None 保留原随机来源。
- 调整第二阶段前阅读 [../relation.py](../relation.py) 的空父表、自引用、composite FK 分支及已有回归；不要把两阶段策略合成随机整数生成。
- 保留 shared pool 注册与 `sqlseed_shared_pool_loaded` hook 的调用；DBAPI placeholder 按 SQLite/PostgreSQL dialect 选择。

## 验证

从仓库根运行 `pytest tests/test_orchestrator.py tests/test_orchestrator_adapter.py tests/test_core/test_orchestrator_schema_fallback.py tests/test_relation.py tests/test_public_api.py`，针对 CHECK 变更补跑 `pytest tests/test_core/test_check_adapt.py tests/test_core/test_stream.py`。
