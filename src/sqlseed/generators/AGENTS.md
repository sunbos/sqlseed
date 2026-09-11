# Providers 与 generator dispatch

本目录把 generator spec 转成数据值；不得导入 `sqlseed.core`。`BaseProvider` 当前用 counter 与 seeded RNG 合成 placeholder；Faker 提供 locale 数据，Mimesis 是可选 provider。

## 扩展入口

- [_protocol.py](_protocol.py)：`DataProvider` 定义 `name/set_locale/set_seed/generate`；自定义 provider 不要求继承基类。
- [_dispatch.py](_dispatch.py)：`GENERATOR_MAP`、`GeneratorDispatchMixin.generate()`、`verify_dispatch_sync()`；generator 名称以该表为准。
- [base_provider.py](base_provider.py)：`_gen_<type>()` 的共同实现；[faker_provider.py](faker_provider.py)、[mimesis_provider.py](mimesis_provider.py) 覆盖有真实 locale 数据的能力。
- [registry.py](registry.py)：provider 注册、按需加载与 `sqlseed` entry point 发现；需区分返回的 provider class/instance 与其他插件对象。
- 日期/时间、字符串与 JSON 公用逻辑分别在 [_datetime_utils.py](_datetime_utils.py)、[_string_helpers.py](_string_helpers.py)、[_json_helpers.py](_json_helpers.py)。

## 合约与可复现性

- 新 generator 同步 `GENERATOR_MAP` 与 `_gen_*` 实现，使所有 provider 通过覆盖或继承支持它；未知类型抛 `UnknownGeneratorError`，不要把参数错误也改成未知类型。
- 新随机逻辑使用 provider 的 `self._rng` 或已经 `set_seed()` 的 native RNG；不要引入全局 RNG 破坏 seed。
- provider 只实现 `set_seed`，调度由 `DataStream.__init__` 管理；不要在注册或每次 generate 时重置 seed。
- `exclude_values` 有界重试耗尽后返回最后值，由上层 UNIQUE solver 回溯；保留 unhashable 值的处理，不能改成无限重试。
- 配置 preferred provider 与实际加载失败处理分开：registry 总有 `base`，orchestrator 当前遇到不可用 provider 直接降级到 `base` 并更新 default，并非自动逐级 fallback chain。
- Mimesis optional import 必须保留 `ImportError` guard；Faker、rstr 是 required dependencies。现有 Faker/Mimesis 在模块级通过 `importlib.import_module()` 加 guard 探测，勿无依据改为强制 function-level import。

## Locale 与格式

- Mimesis native locale 用短码（`en`、`zh`）；`set_locale()` 会转换常见 Faker-style 值，不能把任意 `en_XX` 直接传给 Mimesis enum。
- Faker 在 init/locale 切换时探测缺失方法，并在实例上安装 BaseProvider fallback；切回支持的 locale 必须清理旧遮蔽，不能等 fill 中途崩溃。
- `phone` 默认保留 provider 的 locale 格式；显式 `mask` 提供统一格式。精确长度 CHECK 在上层改成 pattern，不要让 native phone 伪装成固定长度。
- 日期/时间边界处理优先复用 `_datetime_utils.py`，避免不同 provider 各自实现不一致的参数解释。

## 验证与同步

从仓库根执行 `pytest tests/test_generators/`；dispatch 变更重点检查 `test_dispatch_sync.py` 与 `test_dispatch_exclude.py`。

修改 `_dispatch.py` 后同步 [README.md](../../../README.md) 与 [README.zh-CN.md](../../../README.zh-CN.md) 的 generator 表，执行 `python scripts/sync_docs.py`、`pytest tests/test_doc_sync.py tests/test_architecture.py`。新 provider 的发布注册使用根 `pyproject.toml` 的 `project.entry-points."sqlseed"`。
