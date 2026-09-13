# Providers 与 generator dispatch

**核验日期：** 2026-09-14

本目录把 generator spec 转成数据值，承接[核心包规则](../AGENTS.md)；不得导入 `sqlseed.core`。`BaseProvider` 用 counter 与 seeded RNG 合成 primitive/placeholder，Faker 提供 locale 数据，Mimesis 是可选 provider。

## 扩展入口

- [_protocol.py](_protocol.py)：`DataProvider` 定义 `name/set_locale/set_seed/generate`；自定义 provider 不要求继承基类。
- [_dispatch.py](_dispatch.py)：`GENERATOR_MAP`、`GeneratorDispatchMixin.generate()`、`verify_dispatch_sync()`；generator 名称以该表为准。
- [base_provider.py](base_provider.py)：`_gen_<type>()` 的共同实现；[faker_provider.py](faker_provider.py)、[mimesis_provider.py](mimesis_provider.py) 覆盖有真实 locale 数据的能力。
- [_native_provider.py](_native_provider.py)：共享 native provider 的浮点边界与日期方法；各 provider 保留自己的 native 抽样来源，不能为共用实现改变 counter 或 seed 序列。
- [registry.py](registry.py)：provider 注册、按需加载与 `sqlseed` entry point 发现；需区分返回的 provider class/instance 与其他插件对象。
- 日期/时间、字符串与 JSON 公用逻辑分别在 [_datetime_utils.py](_datetime_utils.py)、[_string_helpers.py](_string_helpers.py)、[_json_helpers.py](_json_helpers.py)。
- [_datetime_methods.py](_datetime_methods.py) 用普通函数 factory 绑定日期方法的计数政策，保留完整关键字签名和 `get_type_hints()`。Base 实现即使绑定到 native 实例也推进 placeholder counter；native 实现不推进。`timestamp` 必须动态委托实例当前的 `_gen_datetime`，不能直接 alias 某一固定函数。

## 合约与可复现性

- 新 generator 同步 `GENERATOR_MAP` 与 `_gen_*` 实现，使所有 provider 通过覆盖或继承支持它；未知类型抛 `UnknownGeneratorError`，不要把参数错误也改成未知类型。
- 新随机逻辑使用 provider 的 `self._rng` 或已经 `set_seed()` 的 native RNG；不要引入全局 RNG 破坏 seed。
- provider 只实现 `set_seed`，调度由 `DataStream.__init__` 管理；不要在注册或每次 generate 时重置 seed。
- `exclude_values` 有界重试耗尽后返回最后值，由上层 UNIQUE solver 回溯；保留 unhashable 值的处理，不能改成无限重试。
- 配置 preferred provider 与实际加载失败处理分开：registry 总有 `base`，orchestrator 当前遇到不可用 provider 直接降级到 `base` 并更新 default，并非自动逐级 fallback chain。
- Mimesis optional import 必须保留 `ImportError` guard；Faker、rstr 是 required dependencies。现有 Faker/Mimesis 在模块级通过 `importlib.import_module()` 加 guard 探测，勿无依据改为强制 function-level import。
- registry 可用性依据 native 模块的实际 import 结果；仅发现安装位置不能证明依赖可导入。缺失 provider 的错误与安装提示仍由 `ensure_provider()` 给出。

## 参数与值域

- float 先验证有限端点、顺序及指定 `precision` 下是否存在值；舍入结果必须落在用户闭区间内。单个合法网格点直接返回，不能消耗额外 RNG；保持已有默认 seed 序列。
- `text` 的反向长度边界明确失败，短文本与精确长度也必须成立；不能依赖 locale 库的默认最短长度。
- JSON schema 的递归对象、数组和标量共用 `_json_helpers.py`，返回序列化 JSON 文档；字符串与布尔值不可被转成错误的 JSON 类型。
- `bytes(folder=...)` 的缺目录/无匹配文件抛 `ConfigurationError`，不能作为可重试生成错误吞掉；合成 JPEG 的 Pillow 是可选依赖，缺失时保留 PNG fallback。

## Locale 与格式

- Mimesis native locale 用短码（`en`、`zh`）；`set_locale()` 会转换常见 Faker-style 值，不能把任意 `en_XX` 直接传给 Mimesis enum。
- Faker 在 init/locale 切换时探测缺失方法，并在实例上安装 BaseProvider fallback；切回支持的 locale 必须清理旧遮蔽，不能等 fill 中途崩溃。
- `phone` 默认保留 provider 的 locale 格式；显式 `mask` 提供统一格式。精确长度 CHECK 在上层改成 pattern，不要让 native phone 伪装成固定长度。
- 日期/时间边界处理优先复用 `_datetime_utils.py`，避免不同 provider 各自实现不一致的参数解释。

## 验证与同步

从仓库根执行 `pytest tests/test_generators/`；dispatch 变更重点检查 `test_dispatch_sync.py` 与 `test_dispatch_exclude.py`，provider 共用实现还需核对 `test_datetime_policy.py`、`test_parameter_bounds_regressions.py`、`test_generator_quality_regressions.py` 和 `test_dependency_availability_regressions.py`。

修改 `_dispatch.py` 后同步 [docs/guide.md](../../../docs/guide.md#generators) 的完整 generator 表及自动生成的数量，执行 `python scripts/sync_docs.py`、`pytest tests/test_doc_sync.py tests/test_architecture.py`。新 provider 的发布注册使用根 `pyproject.toml` 的 `project.entry-points."sqlseed"`；测试约定见 [tests/test_generators/AGENTS.md](../../../tests/test_generators/AGENTS.md)。
