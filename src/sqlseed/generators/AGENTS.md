# AGENTS.md — src/sqlseed/generators

## 作用域

- 本目录拥有 `DataProvider` Protocol、内置 Provider、Provider Registry，以及按批流式产出数据的 `DataStream`。

## 本目录规则

- Provider surface 是外部契约。`name`、`set_locale()`、`set_seed()`、`generate()` 以及 `generate_choice(choices)` 的兼容性要和测试保持一致。
- `faker` / `mimesis` 相关导入继续保持可选；缺依赖时允许 registry 延迟报错，但不能让 `import sqlseed` 失败。
- `ProviderRegistry.register_from_entry_points()` 和 `ensure_provider()` 是插件发现与按需加载边界。不要把非 Provider entry point 当成功路径，也不要把插件包硬编码进核心导入链。
- `DataStream` 自己维护局部 RNG，并在有 seed 时单独给 Provider 设 seed；不要引入新的模块级随机状态。
- `_apply_generator()` 只对 `choice` 和 `foreign_key` 做本地特判；其余未知生成器应继续抛 `UnknownGeneratorError`，不要悄悄改成静默字符串回退。
- 回溯、null_ratio、transform ctx 和 batch yield 顺序都属于可观察行为，改动前先看 `tests/test_generators/test_stream.py` 与相关 orchestrator 集成测试。

## 评审热点

- `stream.py` 同时承载 UNIQUE 回溯、外键值池、局部随机源和 transform 调用，属于生成链路的高风险热区。
- `registry.py` 既处理内置 Provider，也处理 entry point 自动发现；错误处理过硬会拖垮可选插件。
- Provider 的 locale / seed 语义要跨 `BaseProvider`、`FakerProvider`、`MimesisProvider` 对齐。

## 验证

- 生成器层：`pytest tests/test_generators`
- 关联行为：`pytest tests/test_mapper.py tests/test_orchestrator.py tests/test_relation.py`
