# 核心生成引擎

本目录负责 schema inference、column mapping、CHECK 解析、流式生成与跨表关系。编排入口是 package；改连接或 fill 流程前继续读 [orchestrator/AGENTS.md](orchestrator/AGENTS.md)。

## 修改入口

| 工作 | 入口与职责 |
| --- | --- |
| 列映射优先级 | [mapper.py](mapper.py)：`ColumnMapper`、`GeneratorSpec` |
| schema 与唯一性分类 | [schema.py](schema.py)：`SchemaInferrer`；[features.py](features.py)：跨数据库结构特征 |
| 单列 CHECK | [check_parser.py](check_parser.py)、[check_adapt.py](check_adapt.py)、[schema_fallback.py](schema_fallback.py) |
| FK、shared pool、表排序 | [relation.py](relation.py)：`RelationResolver`、`SharedPool` |
| derived columns 与表达式 | [column_dag.py](column_dag.py)、[expression.py](expression.py) |
| 生成、回溯与 UNIQUE | [stream.py](stream.py)、[constraints.py](constraints.py)、[unique_adjuster.py](unique_adjuster.py) |
| 本地 enum enrichment | [enrichment.py](enrichment.py)：不调用 LLM |
| 插件与用户 transform | [plugin_mediator.py](plugin_mediator.py)、[transform.py](transform.py) |

## 映射与 CHECK

- 保留 mapper 的优先级：自增 PK → user config → exact match → default/nullability → pattern match → CamelCase 转换后的 exact/pattern 重试 → nullable fallback → type fallback。自定义规则优先于对应 builtin 规则。
- 显式 `faker_method`/`mimesis_method` 可无 generator；mapper 用内部 `__native__` spec 保留该 source，不能落入 nullable/default skip。native 参数不做通用 UNIQUE 扩域；stream 持续调用匹配方法，由 ConstraintSolver 检查重复，未知方法/非法参数明确失败。
- `CheckConstraintParser` 用 sqlglot AST 处理确定的单列 literal CHECK；无法解析时返回 `None`，不猜测业务关系。列名仅折叠 ASCII 大小写，不能把 SQLite 中不同的非 ASCII 列（如 `Ä` / `ä`）合并。
- 长度等值支持 `LENGTH(col) = N` 及反向写法；仅将同列 `col IS NULL OR LENGTH(col) = N` 识别为可空长度约束，不能推广到其他 OR 或不同列 NULL guard。
- `CheckAdapter.adapt_user_configs()` 在 mapping 前收紧 source-column 参数；重叠域 clamp 并提示，无交集抛 `ConfigurationError`。derived、跨列、OR、列引用不属于该适配器范围。
- `SchemaFallbackGenerator` 只作 schema semantics 补充。enum 与 exact-length CHECK 对非 user mapping 的强约束例外保存在 [orchestrator/AGENTS.md](orchestrator/AGENTS.md)，改 fallback 时一并检查。
- 普通跨列比较另由 orchestrator 提取到 `DataStream.inequality_constraints` 做逐行验证；不要把它和单列 CHECK adaptation 的范围混为一谈。

## 生成与约束

- 写入沿用 `DataStream.generate()` 的 batch iterator，不预先收集全部待生成行；`batch_size` 必须为正整数，生成阶段不得扩大用户给定的批大小。未交付 batch 因取消/预算/生成异常而丢弃时，释放其中原始值的 UNIQUE 预留，保留已交付 batch 的登记。
- `DataStream` 可选 `max_attempts` 按实例累计行尝试与列候选次数（跨 batch 和 `generate()` 调用）；默认 `None` 保留原重试上限。`cancel_check` 为合作式 guard，取消抛 `GenerationCancelledError` 并保留原始 reason，不能当普通生成失败重试；无法中断正在运行的 provider/expression/transform。
- seed 由 `DataStream.__init__` 管理，仅 `seed is not None` 时调用 provider 的 `set_seed()`；不要在 orchestrator 重复播种。
- 保留 DAG 顺序、UNIQUE 登记与失败回溯的配合；`composite_unique_constraints` 约束元组，不要求每一列独立唯一。
- composite PRIMARY KEY 由 `SchemaInferrer.detect_composite_unique_constraints()` 作为组合 UNIQUE 上报；不要将所有 PK 列送入单列 UNIQUE 调整。
- nullable UNIQUE skip / choice 的 integer 类型回退按 CHECK 选择值域；type mapper 的默认 `[0, 999999]` 不是用户限制，负数及大整数 CHECK 可替换它，单边 CHECK 的自由端须留足采样空间。显式 integer 用户范围不能套用此扩展规则。
- UNIQUE string 的采样容量使用 `resolve_charset()` 返回字符的去重数量，别名与自定义字符集不能假定为 62。零字符只支持固定零长度的单个空串；单字符按既有长度区间计算容量，不足时明确报错，不无限扩长度。
- 仅完整索引推导无条件 UNIQUE；`IndexInfo.is_partial=True` 的条件唯一性交给数据库写入约束，不运行通用 WHERE 求值器。mapper 使用 `ColumnInfo.is_rowid_alias` 区分真实隐式 ID 与普通 INTEGER PK。
- 表达式通过 `ExpressionEngine` 的 simpleeval sandbox 和 `SAFE_FUNCTIONS` 执行。处理 `ExpressionTimeoutError`；线程 timeout 默认 5 秒，超时线程无法被杀死。
- `PluginMediator` 只保留通用 batch transform 与 template pool；AI suggestion 通过 `sqlseed_apply_ai_suggestions` hook。返回值语义见 [../plugins/AGENTS.md](../plugins/AGENTS.md)。

## FK 与 shared pool

- 表排序使用 `RelationResolver.topological_sort()`；循环 FK 以带 warning 的断环处理，优先选剩余依赖可空的表，不改成一遇环就报错。
- 空父表且 FK 可空时保留 `foreign_key` 的 `null_ratio=1.0`，不要升级成随机整数；自引用两阶段处理见 orchestrator 指导。
- composite FK 的父表来源优先于重叠的单列 FK，并清理妨碍 FK 的 `derive_from`。SQLite 两列 FK 从最多 100000 条父元组中整对抽样，第二节点通过内部依赖复用本行所选元组，不能用首列标量 lookup 压缩合法组合；每个可空成员仍保留 NULL 语义，SQLAlchemy 内部读取保留列类型；父元组 NULL 成员只在对应子列可空时保留，非空候选池过滤后为空时明确报配置错误。三列及以上 composite FK、PostgreSQL composite FK、反射到显式 schema 的 FK 在生成/清表前抛 `ConfigurationError`；不得恢复独立采样 fallback。SQLite 两列协调并不保证子表其他 CHECK 或重叠约束一定满足。
- FK metadata cache 随 orchestrator 生命周期；改缓存清理或 shared pool 更新前检查 `RelationResolver.clear_cache()` 与 `register_shared_pool()`。

## 验证

命令从仓库根执行。

- 通用范围：`pytest tests/test_core/ tests/test_mapper.py tests/test_mapper_camelcase.py tests/test_schema.py tests/test_relation.py`。
- UNIQUE 回归使用真实 `ColumnMapper` 和 `ColumnInfo`，断言算出的 `GeneratorSpec.params`。保留非 exact-match 名称与非空 default 的覆盖；参考 [TestAdjustChoiceFallback](../../../tests/test_core/test_unique_adjuster.py)，避免只验证 mock 调用。
- 修改 `mapper.py` 同步 README/CLAUDE 的规则表；修改 `expression.py` 同步两种语言 README 的 `SAFE_FUNCTIONS` 表，遵循根级文档同步流程。
